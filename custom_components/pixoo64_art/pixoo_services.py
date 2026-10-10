"""
Core Services for Pixoo64 Media Album Art
"""
import aiohttp
import asyncio
import base64
import json
import logging
import math
import random
import re
import time
import textwrap
import colorsys
import urllib.parse
import difflib
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageStat, ImageChops, ImageOps, UnidentifiedImageError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url

try:
    from bidi.algorithm import get_display
    bidi_support = True
except ImportError:
    bidi_support = False

try:
    from unidecode import unidecode
except ImportError:
    HEBREW_MAP = {
        'א': 'A', 'ב': 'B', 'ג': 'G', 'ד': 'D', 'ה': 'H', 'ו': 'V', 'ז': 'Z',
        'ח': 'Ch', 'ט': 'T', 'י': 'Y', 'כ': 'K', 'ך': 'K', 'ל': 'L', 'מ': 'M',
        'ם': 'M', 'נ': 'N', 'ן': 'N', 'ס': 'S', 'ע': 'A', 'פ': 'P', 'ף': 'F',
        'צ': 'Ts', 'ץ': 'Ts', 'ק': 'K', 'ר': 'R', 'ש': 'Sh', 'ת': 'T'
    }
    def unidecode(text: str) -> str:
        res = []
        for ch in text:
            res.append(HEBREW_MAP.get(ch, ch))
        return "".join(res)

_LOGGER = logging.getLogger(__name__)

HEBREW = r"\u0590-\u05FF"
ARABIC = r"\u0600-\u06FF|\u0750-\u077F|\u08A0-\u08FF|\uFB50-\uFDFF|\uFE70-\uFEFF|\u0621-\u06FF"
BIDI_REGEX = re.compile(f"[{HEBREW}|{ARABIC}]")
COLOR_PALETTE = [
    (255, 51, 51), (255, 99, 71), (255, 140, 0), (255, 215, 0), (255, 255, 0),                   
    (173, 255, 47), (127, 255, 0), (50, 205, 50), (0, 255, 255), (0, 191, 255), 
    (30, 144, 255), (238, 130, 238), (255, 0, 255), (255, 20, 147), (255, 255, 255)                                 
]

def get_bidi(text):
    if not bidi_support or not text: return text
    return get_display(text)

def has_bidi(text):
    if not text: return False
    return bool(BIDI_REGEX.search(text))

def ensure_rgb(img):
    try:
        if img and img.mode != "RGB": img = img.convert("RGB")
        return img
    except (UnidentifiedImageError, OSError): return None

def _resize_image_sync(image_data: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(BytesIO(image_data))
        img.load() 
        if img.mode != "RGB": img = img.convert("RGB")
        img = img.resize((34, 34), Image.Resampling.BILINEAR)
        return img
    except Exception:
        return None

# =========================================================================
# CONFIGURATION
# =========================================================================

class Config:
    def __init__(self, entry):
        data = entry.data
        options = entry.options
        
        def get_val(key, default=None):
            return options.get(key, data.get(key, default))

        self.temperature_sensor = get_val("temperature_entity")
        self.media_player = get_val("media_player", "media_player.living_room")
        self.pixoo_ip = get_val("pixoo_ip")
        self.pixoo_url = f"http://{self.pixoo_ip}:80/post" if self.pixoo_ip else None
        self.pollinations = get_val("pollinations_key", "")
        self.ai_fallback = get_val("ai_model", "black-forest-labs/flux.1-schnell")
        self.spotify_client_id = get_val("spotify_client_id", "")
        self.spotify_client_secret = get_val("spotify_client_secret", "")
        self.musicbrainz = get_val("musicbrainz_enabled", True)
        self.internet_archive = get_val("internet_archive_enabled", True)
        self.audiodb_enabled = get_val("audiodb_enabled", True)
        self.prefetch_enabled = get_val("prefetch_enabled", False)
        self.tidal_client_id = get_val("tidal_client_id", "")
        self.tidal_client_secret = get_val("tidal_client_secret", "")
        self.lastfm = get_val("lastfm_key", "")
        self.discogs = get_val("discogs_token", "")
        self.wled_ip = get_val("wled_ip", "")
        self.light_entity = get_val("light_entity", [])
        self.only_at_night = get_val("only_at_night", True)
        self.tv_mode = get_val("tv_mode", False)
        self.artist_slide = False
        self.vinyl_mode = False
        self.cassette_mode = False
        self.analog_clock = False
        
        self.show_text = False
        self.clean_title = True
        self.text_bg = True
        self.top_text = False
        self.overlay_top = True
        self.overlay_align = "Clock Right, Temp Left"
        self.special_mode_spotify_slider = False
        self.force_font_color = None
        self.burned = False
        self.crop_borders = True
        self.crop_extra = False
        self.images_cache = 40
        self.full_control = False
        self.contrast = False
        self.sharpness = False
        self.colors = False
        self.kernel = False
        self.special_mode = False
        self.info = False
        self.show_clock = False
        self.clock_align = "Right"
        self.temperature = False
        self.tv_icon_pic = False
        self.spotify_slide = False
        self.limit_color = None
        self.show_lyrics = False
        self.lyrics_font = 2
        self.lyrics_sync = 0.0
        self.progress_bar_enabled = True
        self.progress_bar_character = "-"
        self.progress_bar_font = 190
        self.progress_bar_resolution = 21
        self.progress_bar_color = "match"
        self.progress_bar_y_offset = 64
        self.force_ai = False
        self.image_filter = "None"
        self.playlist_prefetch_range = get_val("playlist_prefetch_range", "Disabled")
        self.default_font = ImageFont.load_default()

# =========================================================================
# PIXOO HARDWARE DEVICE
# =========================================================================

class PixooDevice:
    def __init__(self, config: "Config", session: aiohttp.ClientSession): 
        self.config = config
        self.session = session
        self.select_index: Optional[int] = None 
        self.headers = {"Content-Type": "application/json", "Accept": "*/*", "Connection": "keep-alive", "User-Agent": "PixooClient/1.0"}
        self._last_payload_str: Optional[str] = None
        self._last_send_time: float = 0.0
        self._send_lock = asyncio.Lock()

    async def send_command(self, payload_command: dict, retries: int = 3) -> bool: 
        if self.session.closed or not self.config.pixoo_url: return False
        
        async with self._send_lock:
            try:
                current_payload_str = json.dumps(payload_command, sort_keys=True)
                now = time.monotonic()
                if (current_payload_str == self._last_payload_str) and (now - self._last_send_time < 0.5): 
                    return True
                self._last_payload_str = current_payload_str
                self._last_send_time = now
            except Exception: pass 

            for attempt in range(1, retries + 1):
                try:
                    async with self.session.post(self.config.pixoo_url, headers=self.headers, json=payload_command, timeout=5) as response:
                        if response.status == 200:
                            await asyncio.sleep(0.08)
                            return True
                except Exception:
                    if attempt < retries: await asyncio.sleep(0.15 * attempt)
            return False

    async def get_current_channel_index(self) -> int: 
        if self.session.closed or not self.config.pixoo_url: return 0
        try:
            async with self.session.post(self.config.pixoo_url, headers=self.headers, json={"Command": "Channel/GetIndex"}, timeout=5) as response:
                response_data = await response.json()
                return response_data.get('SelectIndex', 0)
        except Exception: return 0

    async def get_screen_on_state(self) -> bool: 
        if self.session.closed or not self.config.pixoo_url: 
            return True
        try:
            async with self.session.post(
                self.config.pixoo_url, 
                headers=self.headers, 
                json={"Command": "Channel/GetAllConf"}, 
                timeout=4
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("LightSwitch", 1) == 1
        except Exception:
            pass
        return True

# =========================================================================
# IMAGE FILTER SERVICE
# =========================================================================

class ImageFilterService:
    """Applies artistic pre-scale and post-scale pixel filters using PIL."""

    @staticmethod
    def apply_pre_scale(img: Image.Image, filter_mode: str) -> Image.Image:
        if not filter_mode or filter_mode == "None":
            return img

        try:
            if filter_mode == "Vibrant":
                img = ImageEnhance.Color(img).enhance(1.45)
                img = ImageEnhance.Contrast(img).enhance(1.15)
            elif filter_mode == "Retro Arcade":
                img = ImageEnhance.Color(img).enhance(1.25)
                img = ImageEnhance.Contrast(img).enhance(1.20)
            elif filter_mode == "Crisp & Sharp":
                img = ImageEnhance.Contrast(img).enhance(1.10)
            elif filter_mode == "Noir B&W":
                img = ImageOps.grayscale(img).convert("RGB")
                img = ImageEnhance.Contrast(img).enhance(1.35)
            elif filter_mode == "Cyberpunk Neon":
                img = ImageOps.autocontrast(img, cutoff=2)
                img = ImageEnhance.Color(img).enhance(1.80)
                img = ImageEnhance.Contrast(img).enhance(1.30)
        except Exception as e:
            _LOGGER.debug("Pre-scale filter error: %s", e)
        return img

    @staticmethod
    def apply_post_scale(img: Image.Image, filter_mode: str) -> Image.Image:
        if not filter_mode or filter_mode == "None":
            return img

        try:
            if filter_mode == "Vibrant":
                img = ImageEnhance.Sharpness(img).enhance(1.25)
            elif filter_mode == "Retro Arcade":
                img = ImageOps.posterize(img, bits=3)
            elif filter_mode == "Crisp & Sharp":
                img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=170, threshold=2))
            elif filter_mode == "Noir B&W":
                img = ImageEnhance.Sharpness(img).enhance(1.20)
            elif filter_mode == "Cyberpunk Neon":
                img = img.filter(ImageFilter.EDGE_ENHANCE)
        except Exception as e:
            _LOGGER.debug("Post-scale filter error: %s", e)
        return img

# =========================================================================
# COLOR SCIENCE & PALETTE ANALYZER
# =========================================================================

class ColorAnalyzer:
    @staticmethod
    def get_image_palette(img: Image.Image) -> list:
        quantized = img.quantize(colors=16, method=2)
        palette = quantized.getpalette()
        candidates = []
        if palette:
            raw_colors = [tuple(palette[i:i+3]) for i in range(0, len(palette)//3 * 3, 3)]
            for rgb in raw_colors:
                r, g, b = rgb
                h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
                if s > 0.2 and v > 0.15: candidates.append(rgb)
        if len(candidates) < 3: 
            candidates.extend([(0, 255, 255), (255, 0, 255), (50, 255, 50), (255, 255, 0), (255, 140, 0)])
        return candidates

    @classmethod
    def get_optimal_font_color(cls, img: Image.Image, config: "Config") -> str:
        if getattr(config, 'force_font_color', None): 
            return config.force_font_color
            
        small_thumb = img.resize((25, 25), Image.Resampling.NEAREST)
        colors_raw = small_thumb.getcolors(maxcolors=625) or []
        
        def vibrancy_score(item):
            count, rgb = item
            r, g, b = rgb[:3]
            h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
            return (s * v * v) * (math.log(count) + 1)

        sorted_vibrant = sorted(colors_raw, key=vibrancy_score, reverse=True)
        chosen_dominant_color = None
        for _, color in sorted_vibrant:
            rgb = color[:3]
            h, s, v = colorsys.rgb_to_hsv(rgb[0]/255, rgb[1]/255, rgb[2]/255)
            if s > 0.15 and 0.15 < v < 0.95:
                chosen_dominant_color = rgb
                break
        
        if not chosen_dominant_color and colors_raw:
            for count, color in sorted(colors_raw, key=lambda x: x[0], reverse=True):
                if sum(color[:3]) > 50:
                    chosen_dominant_color = color[:3]
                    break

        if getattr(config, 'text_bg', False):
            if chosen_dominant_color:
                r, g, b = chosen_dominant_color
                h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                nr, ng, nb = colorsys.hsv_to_rgb(h, max(0.4, min(s, 1.0)), 1.0)
                return f'#{int(nr*255):02x}{int(ng*255):02x}{int(nb*255):02x}'
            return "#00ffff"
        else:
            return "#ffffff"

    @classmethod
    def extract_image_values(cls, img: Image.Image, config: "Config") -> dict:
        analysis_img = img.resize((50, 50), Image.Resampling.NEAREST)
        palette = cls.get_image_palette(analysis_img) 
        
        if getattr(config, 'text_bg', False):
             prime_color = palette[0] if palette else (255, 255, 0)
             h, s, v = colorsys.rgb_to_hsv(prime_color[0]/255, prime_color[1]/255, prime_color[2]/255)
             r, g, b = colorsys.hsv_to_rgb(h, max(0.5, s), 1.0)
             hex_color = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
             most_common_color_alternative_rgb = prime_color
        else:
             most_common_color_alternative_rgb = palette[0] if palette else (0,0,0)
             hex_color = '#ffffff'

        brightness = int(sum(most_common_color_alternative_rgb) / 3)
        brightness_lower_part = round(1 - brightness / 255, 2) if 0 <= brightness <= 255 else 0
        font_color = cls.get_optimal_font_color(analysis_img, config)

        return {
            'font_color': font_color, 
            'brightness_lower_part': brightness_lower_part, 
            'background_color_rgb': most_common_color_alternative_rgb,
            'background_color': hex_color
        }

# =========================================================================
# IMAGE CROPPER
# =========================================================================

class ImageCropper:
    @classmethod
    def crop_image_borders(cls, img: Image.Image, config: "Config", radio_logo: bool) -> Image.Image:
        if radio_logo or not getattr(config, 'crop_borders', False):
            return img

        if (getattr(config, 'crop_extra', False) or getattr(config, 'special_mode', False)) and not getattr(config, 'vinyl_mode', False): 
            return cls._perform_extra_subject_crop(img)

        return cls._perform_standard_crop(img)

    @classmethod
    def _perform_standard_crop(cls, img: Image.Image) -> Image.Image:
        orig_w, orig_h = img.size
        if orig_w < 20 or orig_h < 20:
            return img

        proxy_dim = 120
        scale = proxy_dim / float(max(orig_w, orig_h))
        pw = max(10, int(orig_w * scale))
        ph = max(10, int(orig_h * scale))
        proxy = img.resize((pw, ph), Image.Resampling.BILINEAR)
        if proxy.mode != "RGB":
            proxy = proxy.convert("RGB")

        pixels = proxy.load()
        border_pixels = []
        for x in range(pw):
            border_pixels.append(pixels[x, 0])
            border_pixels.append(pixels[x, ph - 1])
        for y in range(1, ph - 1):
            border_pixels.append(pixels[0, y])
            border_pixels.append(pixels[pw - 1, y])

        r_med = sorted(p[0] for p in border_pixels)[len(border_pixels) // 2]
        g_med = sorted(p[1] for p in border_pixels)[len(border_pixels) // 2]
        b_med = sorted(p[2] for p in border_pixels)[len(border_pixels) // 2]
        bg_ref = (r_med, g_med, b_med)

        diff = ImageChops.difference(proxy, Image.new("RGB", (pw, ph), bg_ref))
        gray = ImageOps.grayscale(diff)
        mask = gray.point(lambda p: 255 if p > 25 else 0)

        bbox = mask.getbbox()
        if not bbox:
            return img

        scale_to_orig = 1.0 / scale
        min_x = int(round(bbox[0] * scale_to_orig))
        min_y = int(round(bbox[1] * scale_to_orig))
        max_x = int(round(bbox[2] * scale_to_orig))
        max_y = int(round(bbox[3] * scale_to_orig))

        w = max_x - min_x
        h = max_y - min_y

        if w >= orig_w * 0.98 and h >= orig_h * 0.98:
            return img

        is_pillarbox = (min_y <= int(orig_h * 0.02) and max_y >= int(orig_h * 0.98)) and (min_x > int(orig_w * 0.02) or max_x < int(orig_w * 0.98))
        is_letterbox = (min_x <= int(orig_w * 0.02) and max_y >= int(orig_w * 0.98)) and (min_y > int(orig_h * 0.02) or max_y < int(orig_h * 0.98))

        if is_pillarbox or is_letterbox:
            crop_dim = min(w, h)
        else:
            crop_dim = min(max(w, h), min(orig_w, orig_h))

        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        half = crop_dim / 2.0
        left = int(max(0, min(cx - half, orig_w - crop_dim)))
        top = int(max(0, min(cy - half, orig_h - crop_dim)))

        return img.crop((left, top, left + crop_dim, top + crop_dim))

    @classmethod
    def _refine_box_to_photo_edges(cls, img: Image.Image, rough_box: Tuple[int, int, int, int], bg_color: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
        orig_w, orig_h = img.size
        rx1, ry1, rx2, ry2 = rough_box
        pixels = img.load()
        br, bg, bb = bg_color

        cx = (rx1 + rx2) // 2
        cy = (ry1 + ry2) // 2

        x_start = int(rx1 + (rx2 - rx1) * 0.25)
        x_end = int(rx2 - (rx2 - rx1) * 0.25)
        x_len = max(1, x_end - x_start)

        exact_y1 = ry1
        search_limit_top = max(0, ry1 - int(orig_h * 0.1))
        for y in range(cy, search_limit_top, -1):
            diff_sum = 0
            for x in range(x_start, x_end):
                r, g, b = pixels[x, y]
                diff_sum += max(abs(r - br), abs(g - bg), abs(b - bb))
            if diff_sum / x_len < 10.0:
                exact_y1 = y + 1
                break

        exact_y2 = ry2
        search_limit_bot = min(orig_h, ry2 + int(orig_h * 0.1))
        for y in range(cy, search_limit_bot):
            diff_sum = 0
            for x in range(x_start, x_end):
                r, g, b = pixels[x, y]
                diff_sum += max(abs(r - br), abs(g - bg), abs(b - bb))
            if diff_sum / x_len < 10.0:
                exact_y2 = y - 1
                break

        y_start = int(ry1 + (ry2 - ry1) * 0.25)
        y_end = int(ry2 - (ry2 - ry1) * 0.25)
        y_len = max(1, y_end - y_start)

        exact_x1 = rx1
        search_limit_left = max(0, rx1 - int(orig_w * 0.1))
        for x in range(cx, search_limit_left, -1):
            diff_sum = 0
            for y in range(y_start, y_end):
                r, g, b = pixels[x, y]
                diff_sum += max(abs(r - br), abs(g - bg), abs(b - bb))
            if diff_sum / y_len < 10.0:
                exact_x1 = x + 1
                break

        exact_x2 = rx2
        search_limit_right = min(orig_w, rx2 + int(orig_w * 0.1))
        for x in range(cx, search_limit_right):
            diff_sum = 0
            for y in range(y_start, y_end):
                r, g, b = pixels[x, y]
                diff_sum += max(abs(r - br), abs(g - bg), abs(b - bb))
            if diff_sum / y_len < 10.0:
                exact_x2 = x - 1
                break

        return exact_x1, exact_y1, exact_x2, exact_y2

    @classmethod
    def _inspect_and_unwrap_container(cls, comp: dict, proxy: Image.Image, pw: int, ph: int) -> Optional[Tuple[Tuple[int, int, int], list]]:
        is_spanning_stripe = (comp['h'] > ph * 0.70 and comp['w'] < pw * 0.40) or (comp['w'] > pw * 0.70 and comp['h'] < ph * 0.40)
        is_large_box = comp['area'] > int((pw * ph) * 0.15)
        
        if not (is_spanning_stripe or is_large_box):
            return None

        pixels = proxy.load()
        comp_pixels = comp['pixels']

        buckets = Counter((pixels[x, y][0] // 16, pixels[x, y][1] // 16, pixels[x, y][2] // 16) for x, y in comp_pixels)
        top_bucket, top_count = buckets.most_common(1)[0]
        dominance = top_count / float(len(comp_pixels))

        if dominance < 0.35:
            return None

        matching_colors = [pixels[x, y] for x, y in comp_pixels if (pixels[x, y][0] // 16, pixels[x, y][1] // 16, pixels[x, y][2] // 16) == top_bucket]
        r_med = sorted(c[0] for c in matching_colors)[len(matching_colors) // 2]
        g_med = sorted(c[1] for c in matching_colors)[len(matching_colors) // 2]
        b_med = sorted(c[2] for c in matching_colors)[len(matching_colors) // 2]
        container_bg = (r_med, g_med, b_med)

        inner_mask_set = set()
        for x, y in comp_pixels:
            pr, pg, pb = pixels[x, y]
            diff = max(abs(pr - r_med), abs(pg - g_med), abs(pb - b_med))
            if diff > 25:
                inner_mask_set.add((x, y))

        if not inner_mask_set:
            return None

        visited = set()
        inner_comps = []
        for x, y in inner_mask_set:
            if (x, y) not in visited:
                c_pix = []
                queue = [(x, y)]
                visited.add((x, y))
                while queue:
                    cx, cy = queue.pop()
                    c_pix.append((cx, cy))
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nx, ny = cx + dx, cy + dy
                        if (nx, ny) in inner_mask_set and (nx, ny) not in visited:
                            visited.add((nx, ny))
                            queue.append((nx, ny))

                xs = [p[0] for p in c_pix]
                ys = [p[1] for p in c_pix]
                w = max(xs) - min(xs) + 1
                h = max(ys) - min(ys) + 1
                area = len(c_pix)
                if area >= int((pw * ph) * 0.003):
                    inner_comps.append({
                        'area': area,
                        'min_x': min(xs), 'max_x': max(xs),
                        'min_y': min(ys), 'max_y': max(ys),
                        'w': w, 'h': h,
                        'pixels': c_pix
                    })

        if inner_comps:
            return container_bg, inner_comps

        return None

    @classmethod
    def _find_subject_box(cls, comps: list, pw: int, ph: int) -> Tuple[int, int, int, int]:
        def comp_score(c):
            w, h, area = c['w'], c['h'], c['area']
            solidity = area / float(w * h)
            aspect = min(w, h) / float(max(w, h))
            center_x = (c['min_x'] + c['max_x']) / 2.0
            center_y = (c['min_y'] + c['max_y']) / 2.0
            dist = math.hypot(center_x - (pw / 2.0), center_y - (ph / 2.0)) / (pw / 2.0)
            return area * (solidity ** 1.2) * (aspect ** 0.8) / (1.0 + dist * 0.5)

        scored_comps = sorted(comps, key=comp_score, reverse=True)
        primary = scored_comps[0]

        cur_min_x, cur_max_x = primary['min_x'], primary['max_x']
        cur_min_y, cur_max_y = primary['min_y'], primary['max_y']

        for other in scored_comps[1:]:
            if other['area'] < primary['area'] * 0.15:
                continue

            dx = max(0, max(cur_min_x - other['max_x'], other['min_x'] - cur_max_x))
            dy = max(0, max(cur_min_y - other['max_y'], other['min_y'] - cur_max_y))
            dist = max(dx, dy)

            if dist <= 6:
                new_min_x = min(cur_min_x, other['min_x'])
                new_max_x = max(cur_max_x, other['max_x'])
                new_min_y = min(cur_min_y, other['min_y'])
                new_max_y = max(cur_max_y, other['max_y'])
                new_w = new_max_x - new_min_x + 1
                new_h = new_max_y - new_min_y + 1
                new_aspect = min(new_w, new_h) / float(max(new_w, new_h))

                if new_aspect >= 0.45:
                    cur_min_x, cur_max_x = new_min_x, new_max_x
                    cur_min_y, cur_max_y = new_min_y, new_max_y

        return cur_min_x, cur_min_y, cur_max_x, cur_max_y

    @classmethod
    def _perform_extra_subject_crop(cls, img: Image.Image) -> Image.Image:
        orig_w, orig_h = img.size
        if orig_w < 20 or orig_h < 20:
            return img

        proxy_dim = 120
        scale = proxy_dim / float(max(orig_w, orig_h))
        pw = max(10, int(orig_w * scale))
        ph = max(10, int(orig_h * scale))
        proxy = img.resize((pw, ph), Image.Resampling.BILINEAR)
        if proxy.mode != "RGB":
            proxy = proxy.convert("RGB")

        pixels = proxy.load()
        border_pixels = []
        for x in range(pw):
            border_pixels.append(pixels[x, 0])
            border_pixels.append(pixels[x, ph - 1])
        for y in range(1, ph - 1):
            border_pixels.append(pixels[0, y])
            border_pixels.append(pixels[pw - 1, y])

        r_med = sorted(p[0] for p in border_pixels)[len(border_pixels) // 2]
        g_med = sorted(p[1] for p in border_pixels)[len(border_pixels) // 2]
        b_med = sorted(p[2] for p in border_pixels)[len(border_pixels) // 2]
        bg_ref = (r_med, g_med, b_med)

        diff = ImageChops.difference(proxy, Image.new("RGB", (pw, ph), bg_ref))
        gray = ImageOps.grayscale(diff)
        mask = gray.point(lambda p: 255 if p > 25 else 0)

        mask_clean = mask.filter(ImageFilter.MedianFilter(3))
        mask_pixels = list(mask_clean.getdata())
        visited = [False] * (pw * ph)
        comps = []

        for y in range(ph):
            y_off = y * pw
            for x in range(pw):
                idx = y_off + x
                if mask_pixels[idx] > 0 and not visited[idx]:
                    comp_pixels = []
                    queue = [(x, y)]
                    visited[idx] = True
                    while queue:
                        cx, cy = queue.pop()
                        comp_pixels.append((cx, cy))
                        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            nx, ny = cx + dx, cy + dy
                            if 0 <= nx < pw and 0 <= ny < ph:
                                n_idx = ny * pw + nx
                                if mask_pixels[n_idx] > 0 and not visited[n_idx]:
                                    visited[n_idx] = True
                                    queue.append((nx, ny))

                    xs = [p[0] for p in comp_pixels]
                    ys = [p[1] for p in comp_pixels]
                    w = max(xs) - min(xs) + 1
                    h = max(ys) - min(ys) + 1
                    area = len(comp_pixels)
                    density = area / float(w * h)
                    is_outer_frame = (w > pw * 0.75 and h > ph * 0.75 and density < 0.25)

                    if area >= int((pw * ph) * 0.005) and not is_outer_frame:
                        comps.append({
                            'area': area,
                            'min_x': min(xs), 'max_x': max(xs),
                            'min_y': min(ys), 'max_y': max(ys),
                            'w': w, 'h': h,
                            'pixels': comp_pixels
                        })

        if not comps:
            return cls._perform_standard_crop(img)

        comps.sort(key=lambda c: c['area'], reverse=True)
        container_result = cls._inspect_and_unwrap_container(comps[0], proxy, pw, ph)

        if container_result:
            target_bg_color, candidate_comps = container_result
        else:
            target_bg_color, candidate_comps = bg_ref, comps

        is_typography = False
        if not container_result:
            max_comp_area = comps[0]['area']
            if max_comp_area <= int((pw * ph) * 0.07):
                px = proxy.load()
                comp_colors = [px[x, y] for c in candidate_comps for x, y in c['pixels']]
                q_colors = set((c[0] // 16, c[1] // 16, c[2] // 16) for c in comp_colors)
                
                min_bx = min(c['min_x'] for c in candidate_comps)
                max_bx = max(c['max_x'] for c in candidate_comps)
                min_by = min(c['min_y'] for c in candidate_comps)
                max_by = max(c['max_y'] for c in candidate_comps)
                scale_to_orig = 1.0 / scale
                ox1 = max(0, int(round(min_bx * scale_to_orig)))
                oy1 = max(0, int(round(min_by * scale_to_orig)))
                ox2 = min(orig_w, int(round(max_bx * scale_to_orig)) + 1)
                oy2 = min(orig_h, int(round(max_by * scale_to_orig)) + 1)
                
                crop_sample = img.crop((ox1, oy1, ox2, oy2))
                sample_colors = list(crop_sample.getdata())
                orig_q_colors = set((c[0] // 16, c[1] // 16, c[2] // 16) for c in sample_colors)
                
                if len(orig_q_colors) < 120 and len(q_colors) < 60:
                    is_typography = True

        if is_typography:
            sub_min_x = min(c['min_x'] for c in candidate_comps)
            sub_max_x = max(c['max_x'] for c in candidate_comps)
            sub_min_y = min(c['min_y'] for c in candidate_comps)
            sub_max_y = max(c['max_y'] for c in candidate_comps)

            scale_to_orig = 1.0 / scale
            orig_sub_w = (sub_max_x - sub_min_x + 1) * scale_to_orig
            orig_sub_h = (sub_max_y - sub_min_y + 1) * scale_to_orig
            cx = ((sub_min_x + sub_max_x) / 2.0) * scale_to_orig
            cy = ((sub_min_y + sub_max_y) / 2.0) * scale_to_orig

            content_dim = max(orig_sub_w, orig_sub_h)
            padding_factor = 1.45
            crop_dim = int(content_dim * padding_factor)
            max_allowed = min(orig_w, orig_h)
            crop_dim = min(crop_dim, max_allowed)
            crop_dim = max(10, crop_dim)

            half = crop_dim / 2.0
            left = int(max(0, min(cx - half, orig_w - crop_dim)))
            top = int(max(0, min(cy - half, orig_h - crop_dim)))

            return img.crop((left, top, left + crop_dim, top + crop_dim))

        sub_min_x, sub_min_y, sub_max_x, sub_max_y = cls._find_subject_box(candidate_comps, pw, ph)

        scale_to_orig = 1.0 / scale
        rough_box = (
            int(round(sub_min_x * scale_to_orig)),
            int(round(sub_min_y * scale_to_orig)),
            int(round(sub_max_x * scale_to_orig)),
            int(round(sub_max_y * scale_to_orig))
        )

        x1, y1, x2, y2 = cls._refine_box_to_photo_edges(img, rough_box, target_bg_color)
        sub_w = x2 - x1
        sub_h = y2 - y1

        crop_dim = min(sub_w, sub_h)
        inset = max(1, int(crop_dim * 0.01))
        crop_dim = max(10, crop_dim - (inset * 2))

        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        half = crop_dim / 2.0

        left = int(max(x1, min(cx - half, x2 - crop_dim)))
        top = int(max(y1, min(cy - half, y2 - crop_dim)))

        return img.crop((left, top, left + crop_dim, top + crop_dim))

# =========================================================================
# IMAGE PROCESSOR (ORCHESTRATOR & CACHING)
# =========================================================================

class ImageProcessor:
    def __init__(self, hass: HomeAssistant, config: "Config", session: aiohttp.ClientSession):
        self.hass = hass
        self.config = config
        self.session = session
        self.image_cache: OrderedDict[str, dict] = OrderedDict()
        self.raw_image_cache: OrderedDict[str, bytes] = OrderedDict()
        self._prefetch_tasks: dict = {}
        self.cache_size: int = min(getattr(config, 'images_cache', 40), 40)
        self.cropper = ImageCropper()
        self.color_analyzer = ColorAnalyzer()
        self.filter_service = ImageFilterService()
        

    def shutdown(self):
        pass

    async def async_prefetch_url(self, picture: str, media_data: "MediaData" = None):
        if not picture: return
        if picture.startswith('http'): url = picture
        else:
            try: base_url = get_url(self.hass)
            except Exception: base_url = "http://127.0.0.1:8123"
            url = f"{base_url}{picture}"
            
        if url in self.raw_image_cache or url in self._prefetch_tasks:
            return

        task = asyncio.create_task(self.get_raw_image_data(url))
        self._prefetch_tasks[url] = task
        try:
            await task
        finally:
            self._prefetch_tasks.pop(url, None)

    async def get_raw_image_data(self, url: str) -> Optional[bytes]:
        if not url: return None
        if not url.startswith('http'):
            try: base_url = get_url(self.hass)
            except Exception: base_url = "http://127.0.0.1:8123"
            url = f"{base_url}{url}"

        if url in self._prefetch_tasks:
            try: await self._prefetch_tasks[url]
            except Exception: pass

        if url in self.raw_image_cache:
            self.raw_image_cache.move_to_end(url)
            return self.raw_image_cache[url]

        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            api_key = getattr(self.config, 'pollinations', "")
            if "pollinations.ai" in url and api_key:
                headers["Authorization"] = f"Bearer {str(api_key).strip()}"

            async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 200:
                    image_data = await response.read()
                    if len(self.raw_image_cache) >= self.cache_size:
                        self.raw_image_cache.popitem(last=False)
                    self.raw_image_cache[url] = image_data
                    return image_data
        except Exception as e:
            _LOGGER.debug("Failed to download raw image data for %s: %s", url, e)
        return None

    async def get_image(self, picture: Optional[str], media_data: "MediaData", spotify_slide: bool = False) -> Optional[dict]:
        if not picture: return None
        current_filter = getattr(self.config, 'image_filter', 'None')
        cache_key = f"{picture}_{media_data.artist}_{media_data.title}_{current_filter}" if getattr(self.config, 'burned', False) else f"{picture}_{current_filter}"
        use_cache = not spotify_slide and not getattr(media_data, 'playing_tv', False)
        cached_data = None

        if use_cache and cache_key in self.image_cache:
            self.image_cache.move_to_end(cache_key)
            cached_data = self.image_cache[cache_key]
        else:
            image_data = await self.get_raw_image_data(picture)
            if image_data:
                cached_data = await self.process_image_data(image_data, media_data)
                if cached_data and not spotify_slide:
                    if len(self.image_cache) >= self.cache_size: 
                        self.image_cache.popitem(last=False)
                    self.image_cache[cache_key] = cached_data

        if not cached_data: return None
        
        final_img = cached_data['pil_image'].copy()
        final_img = self.text_clock_img(final_img, cached_data, media_data)
        
        return {'base64_image': self.gbase64(final_img), **cached_data}

    async def process_image_data(self, image_data: bytes, media_data: "MediaData") -> Optional[dict]:
        try:
            return await self.hass.async_add_executor_job(
                self._process_image, image_data, media_data
            )
        except Exception as e:
            _LOGGER.error("Error executing image process job: %s", e)
            return None

    def _process_image(self, image_data: bytes, media_data: "MediaData") -> Optional[dict]:
        try:
            with Image.open(BytesIO(image_data)) as img:
                img.load()
                img = ensure_rgb(img)
                if img is None:
                    return None

                img = self.fixed_size(img)
                radio_logo = getattr(media_data, 'radio_logo', False)
                clean_img = self.crop_image_borders(img, radio_logo)

                val_dict = self.img_values(clean_img)
                palette = self.get_image_palette(clean_img)

                def _rgb_to_hex(c):
                    return f"#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x}"

                color1 = _rgb_to_hex(palette[0]) if len(palette) > 0 else "#FFFFFF"
                color2 = _rgb_to_hex(palette[1]) if len(palette) > 1 else color1
                color3 = _rgb_to_hex(palette[2]) if len(palette) > 2 else color2

                display_img = clean_img.copy()
                filter_mode = getattr(self.config, 'image_filter', 'None')
                display_img = self.filter_service.apply_pre_scale(display_img, filter_mode)
                display_img = display_img.resize((64, 64), Image.Resampling.BILINEAR)

                if getattr(self.config, 'special_mode', False):
                    display_img = self.special_mode(display_img)

                if getattr(self.config, 'burned', False):
                    display_img = self._draw_burned_text(display_img, media_data.artist, media_data.title)

                display_img = self.filter_service.apply_post_scale(display_img, filter_mode)

                clean_64 = clean_img.resize((64, 64), Image.Resampling.BILINEAR)
                is_analog = getattr(self.config, 'analog_clock', False)
                final_pil = clean_64 if is_analog else display_img

                return {
                    'pil_image': final_pil,
                    'clean_image': clean_64,
                    'font_color': val_dict.get('font_color', '#FFFFFF'),
                    'brightness_lower_part': val_dict.get('brightness_lower_part', 0.5),
                    'background_color_rgb': val_dict.get('background_color_rgb', (0, 0, 0)),
                    'background_color': val_dict.get('background_color', '#000000'),
                    'color1': color1,
                    'color2': color2,
                    'color3': color3,
                }
        except Exception as e:
            _LOGGER.error("Error in _process_image: %s", e)
            return None

    process_image = _process_image

    def _draw_burned_text(self, img: Image.Image, artist: str, title: str) -> Image.Image:
        if not (artist or title): 
            return img
        thumb = img.resize((16, 16), Image.Resampling.BICUBIC)
        pixels = list(thumb.getdata())
        bg = tuple(sum(ch) // len(pixels) for ch in zip(*pixels))  
        
        def contrast(c1, c2):
            def _lum(c):
                r,g,b = [v/255 for v in c]
                r = r/12.92 if r<=0.03928 else ((r+0.055)/1.055)**2.4
                g = g/12.92 if g<=0.03928 else ((g+0.055)/1.055)**2.4
                b = b/12.92 if b<=0.03928 else ((b+0.055)/1.055)**2.4
                return 0.2126*r + 0.7152*g + 0.0722*b
            l1, l2 = _lum(c1)+0.05, _lum(c2)+0.05
            return max(l1,l2)/min(l1,l2)
            
        palette = COLOR_PALETTE.copy()
        random.shuffle(palette)
        artist_rgb = title_rgb = None
        for cand in palette:
            if contrast(cand, bg) > 4.5:
                if not artist_rgb: artist_rgb = cand
                elif not title_rgb: title_rgb = cand; break
                
        if not artist_rgb: artist_rgb = (255, 255, 255)
        if not title_rgb: title_rgb = (255, 255, 0)

        artist_shadow = (*tuple(255 - c for c in artist_rgb), 180)
        title_shadow  = (*tuple(255 - c for c in title_rgb), 180)

        img_copy = img.copy().convert("RGBA")
        layer = ImageDraw.Draw(img_copy)
        font = self.config.default_font
        max_w = img.width - 4
        
        def _wrap(text):
            if not text: return []
            words = text.split()
            lines, cur = [], ""
            for w in words:
                test = f"{cur} {w}".strip() if cur else w
                if layer.textbbox((0,0), test, font=font)[2] <= max_w: 
                    cur = test
                else:
                    if cur: lines.append(cur)
                    cur = w
            if cur: lines.append(cur)
            return lines

        artist_lines = _wrap(artist)
        title_lines = _wrap(title)
        
        if not artist_lines and not title_lines: 
            return img.convert("RGB")

        y = max(2, (img.height - ((len(artist_lines) + len(title_lines)) * 11 + 4)) // 2)

        for line in artist_lines:
            line_to_draw = get_bidi(line) if has_bidi(line) else line
            w = layer.textbbox((0,0), line_to_draw, font=font)[2]
            x = (img.width - w) // 2
            layer.text((x + 1, y + 1), line_to_draw, font=font, fill=artist_shadow)
            layer.text((x, y), line_to_draw, font=font, fill=(*artist_rgb, 255))
            y += 11

        if artist_lines and title_lines: 
            y += 4

        for line in title_lines:
            line_to_draw = get_bidi(line) if has_bidi(line) else line
            w = layer.textbbox((0,0), line_to_draw, font=font)[2]
            x = (img.width - w) // 2
            layer.text((x + 1, y + 1), line_to_draw, font=font, fill=title_shadow)
            layer.text((x, y), line_to_draw, font=font, fill=(*title_rgb, 255))
            y += 11

        return img_copy.convert("RGB")

    def text_clock_img(self, img: Image.Image, cached_data: dict, media_data: "MediaData") -> Image.Image:
        if getattr(self.config, 'special_mode', False):
            return img

        if getattr(self.config, 'show_lyrics', False) and len(media_data.lyrics) > 0 and not getattr(media_data, 'playing_tv', False):
            if getattr(self.config, 'text_bg', False) and not getattr(media_data, 'playing_radio', False):
                stat = ImageStat.Stat(img.convert("L"))
                mean_lum = stat.mean[0] if stat.mean else 100.0
                factor = max(0.25, min(0.55, 1.0 - (mean_lum / 220.0)))
                img = ImageEnhance.Brightness(img).enhance(factor)
                img = ImageEnhance.Contrast(img).enhance(0.65)
            return img

        is_top = getattr(self.config, 'overlay_top', True)
        y_start, y_end = (2, 9) if is_top else (55, 62)
        align_mode = getattr(self.config, 'overlay_align', 'Clock Right, Temp Left')

        if bool(getattr(self.config, 'show_clock', False) and getattr(self.config, 'text_bg', False)):
            if align_mode == "Clock Left, Temp Right":
                lpc_clock = (2, y_start, 21, y_end)
            elif align_mode == "Centered" and not getattr(self.config, 'temperature', False):
                lpc_clock = (21, y_start, 43, y_end)
            elif align_mode == "Centered":
                lpc_clock = (35, y_start, 62, y_end)
            else: 
                lpc_clock = (43, y_start, 62, y_end)

            clock_crop = img.crop(lpc_clock)
            stat = ImageStat.Stat(clock_crop.convert("L"))
            factor = max(0.2, 1.0 - (stat.mean[0] / 200.0))
            img.paste(ImageEnhance.Brightness(clock_crop).enhance(factor), lpc_clock)

        if bool(getattr(self.config, 'temperature', False) and getattr(self.config, 'text_bg', False)):
            if align_mode == "Clock Left, Temp Right":
                lpc_temp = (47, y_start, 63, y_end)
            elif align_mode == "Centered" and not getattr(self.config, 'show_clock', False):
                lpc_temp = (23, y_start, 41, y_end)
            else: 
                lpc_temp = (2, y_start, 18, y_end)

            temp_crop = img.crop(lpc_temp)
            stat = ImageStat.Stat(temp_crop.convert("L"))
            factor = max(0.2, 1.0 - (stat.mean[0] / 200.0))
            img.paste(ImageEnhance.Brightness(temp_crop).enhance(factor), lpc_temp)

        if getattr(self.config, 'text_bg', False) and getattr(self.config, 'show_text', False) and not getattr(media_data, 'playing_tv', False) and not getattr(self.config, 'burned', False):
            lpc = (0, 0, 64, 16) if getattr(self.config, 'top_text', False) else (0, 48, 64, 64)
            lower_part_img = img.crop(lpc)
            stat = ImageStat.Stat(lower_part_img.convert("L"))
            mean_lum = stat.mean[0] if stat.mean else 100.0
            factor = max(0.1, min(0.35, 1.0 - (mean_lum / 180.0)))
            img.paste(ImageEnhance.Brightness(lower_part_img).enhance(factor), lpc)

        return img

    
    def crop_image_borders(self, img: Image.Image, radio_logo: bool) -> Image.Image:
        return self.cropper.crop_image_borders(img, self.config, radio_logo)

    def img_values(self, img: Image.Image) -> dict:
        return self.color_analyzer.extract_image_values(img, self.config)

    def get_image_palette(self, img: Image.Image) -> list:
        return self.color_analyzer.get_image_palette(img)

    def get_optimal_font_color(self, img: Image.Image) -> str:
        return self.color_analyzer.get_optimal_font_color(img, self.config)

    def special_mode(self, img: Image.Image) -> Image.Image:
        if img is None: return None
        output_size = (64, 64)
        album_size = (34, 34) if getattr(self.config, 'show_text', False) else (56, 56)
        album_art = img.resize(album_size, Image.Resampling.BILINEAR)

        try:
            left_color = album_art.getpixel((0, album_size[1] // 2))
            right_color = album_art.getpixel((album_size[0] - 1, album_size[1] // 2))
        except Exception:
            left_color = (100, 100, 100)
            right_color = (150, 150, 150)

        if album_size == (34, 34):
            gradient_source = Image.new("RGB", (2, 1))
            gradient_source.putpixel((0, 0), left_color)
            gradient_source.putpixel((1, 0), right_color)
            background = gradient_source.resize(output_size, Image.Resampling.BILINEAR)
        else:
            dark_background_color = (
                min(left_color[0], right_color[0]) // 2,
                min(left_color[1], right_color[1]) // 2,
                min(left_color[2], right_color[2]) // 2
            )
            background = Image.new('RGB', output_size, dark_background_color)

        x = (output_size[0] - album_size[0]) // 2
        y = 8 
        background.paste(album_art, (x, y))
        return background

    def fixed_size(self, img: Image.Image) -> Image.Image:
        width, height = img.size
        if width == height: return img
        elif height < width:
            border_size = (width - height) // 2
            try: background_color = img.getpixel((0, 0))
            except Exception: background_color = (0, 0, 0)
            new_img = Image.new("RGB", (width, width), background_color)
            new_img.paste(img, (0, border_size))
            return new_img
        else:
            new_size = min(width, height)
            left = (width - new_size) // 2
            top = (height - new_size) // 2
            return img.crop((left, top, left + new_size, top + new_size))


    def gbase64(self, img: Image.Image) -> Optional[str]:
        try:
            if img.size != (64, 64):
                img = img.resize((64, 64), Image.Resampling.BILINEAR)

            if img.mode != "RGB":
                img = img.convert("RGB")

            raw_data = img.tobytes()
            b64 = base64.b64encode(raw_data)
            return b64.decode("utf-8")
        except Exception as e:
            _LOGGER.error("Error converting image to base64: %s", e)
            return None

    async def process_slide_image(self, image_data: bytes, media_data: "MediaData") -> Optional[str]:
        try:
            return await self.hass.async_add_executor_job(
                self._process_slide_image_sync, 
                image_data, media_data
            )
        except Exception as e:
            _LOGGER.error("Error executing slide image job: %s", e)
            return None

    def _process_slide_image_sync(self, image_data: bytes, media_data: "MediaData") -> Optional[str]:
        try:
            with Image.open(BytesIO(image_data)) as img:
                img = ensure_rgb(img)
                img = self.fixed_size(img)
                
                # Apply filter to slides
                filter_mode = getattr(self.config, 'image_filter', 'None')
                img = self.filter_service.apply_pre_scale(img, filter_mode)
                
                img = img.resize((64, 64), Image.Resampling.BILINEAR)

                if getattr(self.config, 'special_mode', False):
                    img = self.special_mode(img)

                img = self.filter_service.apply_post_scale(img, filter_mode)

                cached_data = {}
                img = self.text_clock_img(img, cached_data, media_data)

                return self.gbase64(img)
        except Exception:
            return None

    def generate_vinyl_frames(self, pil_image: Image.Image, media_data: "MediaData") -> List[str]:
        return VinylRenderer.render_frames(pil_image, self, media_data)

    def generate_cassette_frames(self, pil_image: Image.Image, media_data: "MediaData") -> List[str]:
        return CassetteRenderer.render_frames(pil_image, self, media_data)

    def generate_analog_clock_frame(self, pil_image: Image.Image, media_data: "MediaData") -> Optional[str]:
        try:
            clean_canvas = pil_image.copy()
            clock_img = AnalogClockRenderer.render(clean_canvas)
            
            filter_mode = getattr(self.config, 'image_filter', 'None')
            clock_img = self.filter_service.apply_post_scale(clock_img, filter_mode)
            clock_img = self.text_clock_img(clock_img, {}, media_data)
            return self.gbase64(clock_img)
        except Exception as e:
            _LOGGER.error("Error generating analog clock frame: %s", e)
            return None

# =========================================================================
# VINTAGE CASSETTE TAPE ANIMATION RENDERER (MICRO-PIXEL FONT & TRANSLIT)
# =========================================================================

class MicroPixelFont:
    """Ultra-compact 3x5 pixel font bitmap engine (3px wide, 5px high).
    Fits perfectly on retro cassette labels allowing multiple crisp text lines."""

    GLYPHS = {
        ' ': [0, 0, 0],
        'A': [0x1E, 0x05, 0x1E], 'B': [0x1F, 0x15, 0x0A], 'C': [0x0E, 0x11, 0x11],
        'D': [0x1F, 0x11, 0x0E], 'E': [0x1F, 0x15, 0x11], 'F': [0x1F, 0x05, 0x01],
        'G': [0x0E, 0x11, 0x1D], 'H': [0x1F, 0x04, 0x1F], 'I': [0x11, 0x1F, 0x11],
        'J': [0x08, 0x10, 0x0F], 'K': [0x1F, 0x04, 0x1B], 'L': [0x1F, 0x10, 0x10],
        'M': [0x1F, 0x02, 0x1F], 'N': [0x1F, 0x06, 0x1F], 'O': [0x0E, 0x11, 0x0E],
        'P': [0x1F, 0x05, 0x02], 'Q': [0x0E, 0x11, 0x1E], 'R': [0x1F, 0x05, 0x1A],
        'S': [0x12, 0x15, 0x09], 'T': [0x01, 0x1F, 0x01], 'U': [0x0F, 0x10, 0x0F],
        'V': [0x07, 0x18, 0x07], 'W': [0x1F, 0x08, 0x1F], 'X': [0x1B, 0x04, 0x1B],
        'Y': [0x03, 0x1C, 0x03], 'Z': [0x19, 0x15, 0x13],
        '0': [0x0E, 0x15, 0x0E], '1': [0x08, 0x1F, 0x00], '2': [0x19, 0x15, 0x12],
        '3': [0x11, 0x15, 0x0A], '4': [0x07, 0x04, 0x1F], '5': [0x17, 0x15, 0x09],
        '6': [0x0E, 0x15, 0x09], '7': [0x01, 0x1D, 0x03], '8': [0x0A, 0x15, 0x0A],
        '9': [0x02, 0x15, 0x0E],
        '-': [0x04, 0x04, 0x04], '.': [0x00, 0x10, 0x00], "'": [0x00, 0x03, 0x00],
        '&': [0x0A, 0x15, 0x12], '/': [0x10, 0x0C, 0x03], ':': [0x00, 0x0A, 0x00],
        '(': [0x0E, 0x11, 0x00], ')': [0x00, 0x11, 0x0E], '!': [0x00, 0x17, 0x00],
        '?': [0x01, 0x15, 0x02]
    }

    @classmethod
    def get_text_width(cls, text: str) -> int:
        if not text:
            return 0
        return len(text) * 4 - 1

    @classmethod
    def draw_text(cls, draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: tuple):
        cur_x = x
        for ch in text.upper():
            glyph = cls.GLYPHS.get(ch, cls.GLYPHS.get('?'))
            if glyph:
                for col_idx, col_bits in enumerate(glyph):
                    for row_idx in range(5):
                        if (col_bits >> row_idx) & 1:
                            draw.point((cur_x + col_idx, y + row_idx), fill=color)
            cur_x += 4


class CassetteRenderer:
    """Generates an authentic 6-frame looping vintage audio cassette animation
    utilizing full-width micro-pixel text and album color science for the cassette accents."""

    @classmethod
    def render_frames(cls, base_img: Image.Image, image_processor: "ImageProcessor", media_data: "MediaData") -> List[str]:
        frames_b64 = []
        try:
            # 1. Extract dominant color palette from album art for cassette styling
            palette = image_processor.get_image_palette(base_img)
            accent_color = palette[0] if palette else (185, 148, 62)

            shell_color = (20, 20, 22)
            label_bg = (242, 240, 232)
            window_bg = (14, 14, 16)
            spool_outer = (225, 225, 225)

            left_cx, right_cx = 22, 33
            spool_cy = 32
            r_spool = 6
            total_frames = 6

            # Max text width across the full label width (columns 6 to 57 = 52 pixels width)
            max_px = 52
            title_text = cls._prepare_text(media_data.title, max_px)
            artist_text = cls._prepare_text(media_data.artist, max_px)

            for f in range(total_frames):
                canvas = Image.new("RGB", (64, 64), (6, 6, 8))
                draw = ImageDraw.Draw(canvas)

                # Cassette body & corner screws
                draw.rectangle([1, 1, 62, 62], fill=shell_color)
                for sx, sy in [(3, 3), (60, 3), (3, 60), (60, 60)]:
                    draw.point((sx, sy), fill=(160, 160, 170))
                    draw.point((sx + 1, sy), fill=(100, 100, 110))

                # Top Label Area (Full width from x: 4 to 59)
                draw.rectangle([4, 3, 59, 18], fill=label_bg)
                draw.line([(4, 10), (59, 10)], fill=(210, 45, 45), width=1) # Red stripe

                # Full-width micro text lines centered or left-aligned on the label
                MicroPixelFont.draw_text(draw, 6, 4, title_text, (20, 45, 110))
                MicroPixelFont.draw_text(draw, 6, 12, artist_text, (35, 35, 40))

                # Center Acrylic Window & Tape
                draw.rectangle([13, 21, 50, 42], fill=window_bg)
                draw.rectangle([13, 21, 50, 42], outline=(40, 40, 45), width=1)
                for mx in [29, 31, 33, 35]:
                    draw.line([(mx, 26), (mx, 37)], fill=(75, 75, 80), width=1)

                # Rotating Spools / Cogs (6-tooth drive hubs)
                rot_deg = f * 10.0
                rad = math.radians(rot_deg)

                for scx in [left_cx, right_cx + 9]:
                    draw.ellipse([scx - r_spool, spool_cy - r_spool, scx + r_spool, spool_cy + r_spool], fill=spool_outer)
                    draw.ellipse([scx - 3, spool_cy - 3, scx + 3, spool_cy + 3], fill=(8, 8, 10))

                    for tooth_idx in range(6):
                        t_angle = rad + (tooth_idx * math.pi / 3.0)
                        tx = scx + int(round(math.cos(t_angle) * 4.5))
                        ty = spool_cy + int(round(math.sin(t_angle) * 4.5))
                        draw.point((tx, ty), fill=(30, 30, 35))

                # Bottom Accent Bar tinted with album color palette
                draw.rectangle([4, 45, 59, 49], fill=accent_color)
                MicroPixelFont.draw_text(draw, 6, 45, "MIX", (255, 255, 255))
                MicroPixelFont.draw_text(draw, 49, 45, "90", (255, 255, 255))

                # Bottom tape head well
                draw.polygon([(11, 62), (18, 52), (45, 52), (52, 62)], fill=(28, 28, 32))
                draw.line([(18, 52), (45, 52)], fill=(45, 45, 50), width=1)
                draw.ellipse([23, 55, 27, 59], fill=(6, 6, 8))
                draw.ellipse([36, 55, 40, 59], fill=(6, 6, 8))
                draw.point((32, 57), fill=(120, 120, 125))

                # Filters & text overlays
                filter_mode = getattr(image_processor.config, 'image_filter', 'None')
                canvas = image_processor.filter_service.apply_post_scale(canvas, filter_mode)
                canvas = image_processor.text_clock_img(canvas, {}, media_data)

                b64 = image_processor.gbase64(canvas)
                if b64:
                    frames_b64.append(b64)

        except Exception as e:
            _LOGGER.error("Error generating vintage cassette animation frames: %s", e)

        return frames_b64

    @staticmethod
    def _prepare_text(raw_text: str, max_px: int) -> str:
        if not raw_text:
            return ""
        translit = unidecode(str(raw_text)).strip()
        translit = re.sub(r'[^a-zA-Z0-9\s\-\.\'\&\/\:\(\)\!\?]', '', translit)
        max_chars = max(3, (max_px + 1) / 4)
        if len(translit) > max_chars:
            return f"{translit[:int(max_chars) - 2].strip()}.."
        return translit
    

class VinylRenderer:
    """Generates an ultra-smooth 32-frame spinning vinyl turntable animation
    with translucent grooves, soft glossy sheen reflection on Extra Crop, and proportional 1:5 tonearm tracking."""

    @classmethod
    def render_frames(cls, base_img: Image.Image, image_processor: "ImageProcessor", media_data: "MediaData") -> List[str]:
        frames_b64 = []
        try:
            crop_mode = getattr(image_processor.config, 'crop_mode', None)
            if not crop_mode:
                if getattr(image_processor.config, 'crop_extra', False):
                    crop_mode = "Extra Crop"
                elif getattr(image_processor.config, 'crop_borders', False):
                    crop_mode = "Crop"
                else:
                    crop_mode = "No Crop"

            total_frames = 32

            if crop_mode == "Extra Crop":
                cx, cy = 32, 32
                record_radius = 32
                deck_bg = (8, 8, 10)
                show_arm = False
                sheen_r1 = 30
                sheen_r2 = 21

                art_full = base_img.resize((64, 64), Image.Resampling.BILINEAR)
                disc_mask = Image.new("L", (64, 64), 0)
                ImageDraw.Draw(disc_mask).ellipse([0, 0, 63, 63], fill=255)

                groove_overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                g_draw = ImageDraw.Draw(groove_overlay)
                
                g_draw.ellipse([0, 0, 63, 63], outline=(0, 0, 0, 70), width=1)
                
                for r in [28, 24, 20, 16, 12]:
                    g_draw.ellipse([32 - r, 32 - r, 32 + r, 32 + r], outline=(0, 0, 0, 45), width=1)
                
                g_draw.ellipse([25, 25, 39, 39], outline=(0, 0, 0, 60), width=1)

            elif crop_mode == "Crop":
                cx, cy = 32, 32
                record_radius = 29
                label_diam = 26
                deck_bg = (14, 14, 16)
                show_arm = False
                grooves = [28, 26, 24, 22, 20, 18, 16, 14]
                sheen_r1 = 27
                sheen_r2 = 18

                center_crop = base_img.resize((label_diam, label_diam), Image.Resampling.BILINEAR)
                label_mask = Image.new("L", (label_diam, label_diam), 0)
                ImageDraw.Draw(label_mask).ellipse([0, 0, label_diam - 1, label_diam - 1], fill=255)

            else:  # "No Crop"
                cx, cy = 30, 32
                record_radius = 27
                label_diam = 24
                deck_bg = (14, 14, 16)
                show_arm = True
                grooves = [26, 24, 22, 20, 18, 16, 14]
                sheen_r1 = 25
                sheen_r2 = 19

                center_crop = base_img.resize((label_diam, label_diam), Image.Resampling.BILINEAR)
                label_mask = Image.new("L", (label_diam, label_diam), 0)
                ImageDraw.Draw(label_mask).ellipse([0, 0, label_diam - 1, label_diam - 1], fill=255)

            track_num = getattr(media_data, 'track_number', 1) or 1
            queue_total = getattr(media_data, 'queue_total', 0) or 0

            if queue_total > 1:
                progress = max(0.0, min(1.0, (track_num - 1) / max(1, queue_total - 1)))
                side_index = min(4, max(0, int(progress * 5)))
            else:
                side_index = 0

            base_needle_x = 51 - (side_index * 2)
            base_needle_y = 31 + int(round(side_index * 0.5))

            for i in range(total_frames):
                angle = i * (360.0 / total_frames)
                canvas = Image.new("RGB", (64, 64), deck_bg)

                sheen_wobble = math.sin(i * 2.0 * math.pi / total_frames) * 6.0

                if crop_mode == "Extra Crop":
                    rotated_art = art_full.rotate(-angle, resample=Image.Resampling.BILINEAR).convert("RGBA")
                    
                    rotated_art.alpha_composite(groove_overlay)

                    sheen_layer = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                    s_draw = ImageDraw.Draw(sheen_layer)

                    sheen_alpha_main = int(85 + math.sin(i * math.pi / (total_frames / 2.0)) * 25)  
                    sheen_alpha_sub = int(45 + math.sin(i * math.pi / (total_frames / 2.0)) * 15)   

                    color_main = (255, 255, 255, sheen_alpha_main)
                    color_sub = (230, 240, 255, sheen_alpha_sub)

                    s_draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(118 + sheen_wobble), int(152 + sheen_wobble), fill=color_main, width=2)
                    s_draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(298 + sheen_wobble), int(332 + sheen_wobble), fill=color_main, width=2)
                    s_draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(124 - sheen_wobble), int(146 - sheen_wobble), fill=color_sub, width=2)
                    s_draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(304 - sheen_wobble), int(326 - sheen_wobble), fill=color_sub, width=2)

                    rotated_art.alpha_composite(sheen_layer)

                    canvas.paste(rotated_art.convert("RGB"), (0, 0), disc_mask)
                    draw = ImageDraw.Draw(canvas)

                else:
                    draw = ImageDraw.Draw(canvas)
                    draw.ellipse([cx - record_radius - 1, cy - record_radius - 1, cx + record_radius + 1, cy + record_radius + 1], fill=(28, 28, 32))
                    draw.ellipse([cx - record_radius, cy - record_radius, cx + record_radius, cy + record_radius], fill=(16, 16, 18))

                    for r in grooves:
                        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(25, 25, 28), width=1)

                    rotated_label = center_crop.rotate(-angle, resample=Image.Resampling.BILINEAR)
                    canvas.paste(rotated_label, (cx - (label_diam // 2), cy - (label_diam // 2)), label_mask)

                    sheen_brightness = int(50 + math.sin(i * math.pi / (total_frames / 2.0)) * 12)
                    sheen_color_main = (sheen_brightness, sheen_brightness, sheen_brightness + 8)
                    sheen_color_sub = (sheen_brightness - 12, sheen_brightness - 12, sheen_brightness - 6)

                    draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(118 + sheen_wobble), int(152 + sheen_wobble), fill=sheen_color_main, width=2)
                    draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(298 + sheen_wobble), int(332 + sheen_wobble), fill=sheen_color_main, width=2)
                    draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(124 - sheen_wobble), int(146 - sheen_wobble), fill=sheen_color_sub, width=2)
                    draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(304 - sheen_wobble), int(326 - sheen_wobble), fill=sheen_color_sub, width=2)

                draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(10, 10, 12), outline=(180, 180, 190))

                if show_arm:
                    arm_wobble_x = int(round(math.sin(i * 2.0 * math.pi / total_frames) * 0.6))
                    arm_wobble_y = int(round(math.cos(i * 2.0 * math.pi / total_frames) * 0.4))

                    needle_x = base_needle_x + arm_wobble_x
                    needle_y = base_needle_y + arm_wobble_y

                    draw.ellipse([55, 6, 61, 12], fill=(80, 80, 90), outline=(160, 160, 170))
                    draw.point((58, 9), fill=(220, 220, 230))
                    
                    joint_x = int(round(54 - (side_index * 1.0))) + (arm_wobble_x // 2)
                    joint_y = int(round(20 + (side_index * 0.8)))
                    draw.line([(57, 11), (joint_x, joint_y)], fill=(170, 170, 180), width=1)
                    draw.line([(joint_x, joint_y), (needle_x + 1, needle_y - 1)], fill=(190, 190, 200), width=1)

                    draw.rectangle([needle_x - 1, needle_y - 2, needle_x + 2, needle_y + 2], fill=(210, 210, 220))
                    draw.point((needle_x, needle_y + 1), fill=(235, 45, 45))

                filter_mode = getattr(image_processor.config, 'image_filter', 'None')
                canvas = image_processor.filter_service.apply_post_scale(canvas, filter_mode)
                canvas = image_processor.text_clock_img(canvas, {}, media_data)

                b64 = image_processor.gbase64(canvas)
                if b64:
                    frames_b64.append(b64)

        except Exception as e:
            _LOGGER.error("Error generating enhanced vinyl animation frames: %s", e)

        return frames_b64

# =========================================================================
# STANDALONE PROVIDERS
# =========================================================================

class MusicBrainzProvider:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self._last_query_time: float = 0.0

    async def get_album_art_url(self, artist: str, title: str) -> Optional[str]:
        now = time.monotonic()
        elapsed = now - self._last_query_time
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)
        self._last_query_time = time.monotonic()

        search_url = "https://musicbrainz.org/ws/2/release/"
        headers = { 
            "Accept": "application/json", 
            "User-Agent": "Pixoo64MediaArt/1.0 (https://github.com/idodov/pixoo64_art)" 
        }
        clean_artist = str(artist or "").replace('"', '').strip()
        clean_title = str(title or "").replace('"', '').strip()
        params = { "query": f'artist:"{clean_artist}" AND recording:"{clean_title}"', "fmt": "json" }
        
        try:
            async with self.session.get(search_url, params=params, headers=headers, timeout=10) as response: 
                if response.status != 200: return None
                data = await response.json()
                if not data.get("releases"): return None
                release_id = data["releases"][0]["id"]
                cover_art_url = f"https://coverartarchive.org/release/{release_id}"
                try: 
                    async with self.session.get(cover_art_url, headers=headers, timeout=15) as art_response: 
                        if art_response.status != 200: return None
                        art_data = await art_response.json()
                        for image in art_data.get("images", []):
                            if image.get("front", False):
                                return image.get("thumbnails", {}).get("250")
                        return None
                except Exception: return None
        except Exception: return None


class DiscogsProvider:
    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    async def search_album_art(self, artist: str, title: str) -> Optional[str]:
        token = getattr(self.config, 'discogs', None)
        if not token: return None

        base_url = "https://api.discogs.com/database/search"
        headers = { "User-Agent": "AlbumArtSearchApp/1.0", "Authorization": f"Discogs token={token}" }
        params = { "artist": artist, "track": title, "type": "release", "format": "album", "per_page": 5 }
        try:
            async with self.session.get(base_url, headers=headers, params=params, timeout=10) as response: 
                if response.status != 200: 
                    _LOGGER.warning("Discogs API returned status %s", response.status)
                    return None
                data = await response.json()
                results = data.get("results", [])
                if not results: return None
                return results[0].get("cover_image")
        except Exception as e: 
            _LOGGER.error("Discogs search exception: %s", e)
            return None


class LastFmProvider:
    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    def _is_valid_image(self, url: Optional[str]) -> bool:
        if not url or not isinstance(url, str): return False
        url = url.strip()
        if not url.startswith("http"): return False
        if "2a96cbd8b46e442fc41c2b86b821562f" in url or "default_album" in url: return False
        return True

    def _optimize_url(self, url: str) -> str:
        if url and "fastly.net" in url:
            return re.sub(r'/i/u/(?:\d+s|\d+x\d+)/', '/i/u/300x300/', url)
        return url

    def _extract_image_url(self, image_list: list) -> Optional[str]:
        if not isinstance(image_list, list): return None
        preferred_sizes = ["mega", "extralarge", "large", "medium"]
        for size in preferred_sizes:
            for item in image_list:
                if isinstance(item, dict) and item.get("size") == size:
                    img_url = item.get("#text", "")
                    if self._is_valid_image(img_url):
                        return self._optimize_url(img_url)

        for item in reversed(image_list):
            if isinstance(item, dict):
                img_url = item.get("#text", "")
                if self._is_valid_image(img_url):
                    return self._optimize_url(img_url)

        return None

    async def search_album_art(self, artist: str, title: str, album: Optional[str] = None) -> Optional[str]:
        clean_artist = str(artist or "").strip()
        clean_title = str(title or "").strip()
        clean_album = str(album or "").strip()
        api_key = str(getattr(self.config, 'lastfm', "") or "").strip()

        if not clean_artist or clean_artist == "Unknown Artist" or not api_key:
            return None

        base_url = "https://ws.audioscrobbler.com/2.0/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        if clean_album and clean_album != "Unknown Album":
            params = {
                "method": "album.getInfo", "api_key": api_key, "artist": clean_artist,
                "album": clean_album, "autocorrect": 1, "format": "json"
            }
            try:
                async with self.session.get(base_url, headers=headers, params=params, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        images = data.get("album", {}).get("image", [])
                        valid_url = self._extract_image_url(images)
                        if valid_url: return valid_url
            except Exception as e:
                _LOGGER.debug("Last.fm album.getInfo query error: %s", e)

        if clean_title and clean_title != "Unknown Track":
            params = {
                "method": "track.getInfo", "api_key": api_key, "artist": clean_artist,
                "track": clean_title, "autocorrect": 1, "format": "json"
            }
            try:
                async with self.session.get(base_url, headers=headers, params=params, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        track_data = data.get("track", {})
                        album_obj = track_data.get("album", {})
                        images = album_obj.get("image", [])
                        valid_url = self._extract_image_url(images)
                        if valid_url: return valid_url
                        
                        discovered_album = album_obj.get("title")
                        if discovered_album and discovered_album != clean_album:
                            alb_params = {
                                "method": "album.getInfo", "api_key": api_key, "artist": clean_artist,
                                "album": discovered_album, "autocorrect": 1, "format": "json"
                            }
                            async with self.session.get(base_url, headers=headers, params=alb_params, timeout=8) as alb_response:
                                if alb_response.status == 200:
                                    alb_data = await alb_response.json()
                                    alb_images = alb_data.get("album", {}).get("image", [])
                                    valid_url = self._extract_image_url(alb_images)
                                    if valid_url: return valid_url
            except Exception as e:
                _LOGGER.error("Last.fm search exception: %s", e)

        return None


class TidalProvider:
    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.token_cache: dict[str, Any] = {'token': None, 'expires': 0}

    def _format_uuid(self, val: Any) -> Optional[str]:
        if not val or not isinstance(val, str): return None
        cleaned = val.strip().replace("-", "").replace("/", "")
        if len(cleaned) == 32 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
            return f"{cleaned[:8]}/{cleaned[8:12]}/{cleaned[12:16]}/{cleaned[16:20]}/{cleaned[20:]}"
        return None

    def _ensure_320_resolution(self, url: str) -> str:
        if url and "resources.tidal.com" in url:
            return re.sub(r'\d+x\d+', '320x320', url)
        return url

    def _extract_image(self, item: dict) -> Optional[str]:
        if not isinstance(item, dict): return None
        attrs = item.get("attributes", {})

        for key in ["files", "imageLinks", "images"]:
            links = attrs.get(key)
            if isinstance(links, list) and links:
                for candidate in links:
                    if isinstance(candidate, dict):
                        href = candidate.get("href") or candidate.get("url")
                        meta = candidate.get("meta", {})
                        if (meta.get("width") == 320) or (href and "320x320" in href):
                            return self._ensure_320_resolution(href)
                for candidate in reversed(links):
                    if isinstance(candidate, dict):
                        href = candidate.get("href") or candidate.get("url")
                        if href and isinstance(href, str) and href.startswith("http"):
                            return self._ensure_320_resolution(href)

        for key in ["href", "url", "image", "picture"]:
            val = attrs.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return self._ensure_320_resolution(val)

        item_type = str(item.get("type", "")).lower()
        if item_type in ["artworks", "artwork", "coverart"]:
            uuid_path = self._format_uuid(item.get("id"))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        for cover_key in ["cover", "coverArt", "imageCover"]:
            uuid_path = self._format_uuid(attrs.get(cover_key))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        cover_data = item.get("relationships", {}).get("coverArt", {}).get("data")
        if isinstance(cover_data, dict):
            uuid_path = self._format_uuid(cover_data.get("id"))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"
        elif isinstance(cover_data, list):
            for entry in cover_data:
                if isinstance(entry, dict):
                    uuid_path = self._format_uuid(entry.get("id"))
                    if uuid_path:
                        return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        return None

    async def get_access_token(self) -> Optional[str]:
        if self.token_cache['token'] and time.time() < self.token_cache['expires']:
            return self.token_cache['token']
            
        client_id = str(self.config.tidal_client_id).strip()
        client_secret = str(self.config.tidal_client_secret).strip()
        if not client_id or not client_secret: return None

        url = "https://auth.tidal.com/v1/oauth2/token"
        auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        tidal_headers = { 
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/x-www-form-urlencoded" 
        }
        payload = { "grant_type": "client_credentials" }
        
        try:
            async with self.session.post(url, headers=tidal_headers, data=payload, timeout=10) as response: 
                if response.status != 200: 
                    _LOGGER.error("TIDAL Token Auth failed: %s", response.status)
                    return None
                response_json = await response.json()
                access_token = response_json["access_token"]
                expiry_time = time.time() + response_json.get("expires_in", 3600) - 60 
                self.token_cache = { 'token': access_token, 'expires': expiry_time }
                return access_token
        except Exception as e: 
            _LOGGER.error("TIDAL token exception: %s", e)
            return None

    async def get_album_art_url(self, artist: str, title: str) -> Optional[str]:
        access_token = await self.get_access_token()
        if not access_token: return None
        
        clean_artist = str(artist).strip() if artist and artist != "Unknown Artist" else ""
        clean_title = str(title).strip() if title and title != "Unknown Track" else ""
        query = f"{clean_artist} {clean_title}".strip()
        if len(query) < 2 or query == "-": return None
            
        headers = { 
            "Authorization": f"Bearer {access_token}", 
            "Accept": "application/vnd.api+json" 
        }
        search_url = "https://openapi.tidal.com/v2/searchResults"
        search_params = { 
            "countryCode": "US", 
            "filter[query]": query,
            "include": "tracks.albums.coverArt,albums.coverArt" 
        }
        
        try:
            async with self.session.get(search_url, headers=headers, params=search_params, timeout=10) as response: 
                if response.status != 200: return None
                search_data = await response.json()
                included_items = search_data.get("included", [])
                
                for inc in included_items:
                    if str(inc.get("type", "")).lower() in ["artworks", "artwork", "coverart"]:
                        img_url = self._extract_image(inc)
                        if img_url: return img_url

                for inc in included_items:
                    if str(inc.get("type", "")).lower() == "albums":
                        img_url = self._extract_image(inc)
                        if img_url: return img_url

                for inc in included_items:
                    img_url = self._extract_image(inc)
                    if img_url: return img_url

                text_response = json.dumps(search_data)
                url_match = re.search(r'https?://(?:resources|images)\.tidal\.com/images/[a-zA-Z0-9/_-]+(?:\.jpg|\.png)', text_response)
                if url_match:
                    return self._ensure_320_resolution(url_match.group(0))

                uuid_matches = re.findall(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', text_response)
                for u in uuid_matches:
                    formatted = self._format_uuid(u)
                    if formatted:
                        return f"https://resources.tidal.com/images/{formatted}/320x320.jpg"

                return None
        except Exception as e: 
            _LOGGER.warning("TIDAL search exception: %s", e)
            return None


class AiArtProvider:
    def __init__(self, config: "Config"):
        self.config = config

    def format_prompt_url(self, artist: Optional[str], title: str) -> Optional[str]:
        api_key = getattr(self.config, 'pollinations', "")
        if not api_key or not isinstance(api_key, str) or len(api_key.strip()) <= 5:
            _LOGGER.warning("Skipping AI Art generation: 'pollinations_key' is missing or invalid.")
            return None

        artist_name = artist if artist else 'Music' 
        clean_artist = artist_name.replace("/", " ").replace("\\", " ").strip()
        clean_title = title.replace("/", " ").replace("\\", " ").strip()
        
        prompts = [
            f"Vibrant pop art portrait of the musician {clean_artist} inspired by the song '{clean_title}', edge-to-edge full bleed, borderless, bold neon colors, high contrast flat colors for pixel display, strictly no text, no words, zero frames",           
            f"Edge-to-edge vibrant surreal artwork literally depicting the concept of '{clean_title}' by {clean_artist}, vivid high contrast colors, thick outlines, borderless full bleed, strictly no text, no letters, no frames",
            f"Retro synthwave portrait of {clean_artist} performing '{clean_title}', neon magenta and cyan, edge-to-edge borderless, pitch black background, high contrast lighting, absolutely no typography, no words, full bleed, no borders",
            f"Borderless minimalist illustration of the literal meaning of '{clean_title}' (by {clean_artist}), flat bold vibrant colors, edge-to-edge composition, zero borders, clear focal point suited for low resolution display, strictly no text, no typography",
            f"Moody graphic novel style portrait of the artist {clean_artist} singing '{clean_title}', vivid high contrast flat colors, edge-to-edge full bleed, borderless frame, strictly no text, no speech bubbles, zero typography",
            f"Colorful 16-bit style crisp illustration literally showing '{clean_title}' by {clean_artist}, vivid nostalgic palette, edge-to-edge borderless composition, zero text, no borders, no frames, strictly no typography, perfectly cropped",
            f"Luminous stained glass mosaic showing the literal meaning of '{clean_title}' by {clean_artist}, edge-to-edge borderless, saturated jewel tones, thick black outlines, full bleed, absolutely no text, no letters, zero frames",
            f"Vibrant vector portrait of {clean_artist} with elements from '{clean_title}', flat bold geometric shapes, edge-to-edge borderless design, high contrast palette for LED displays, strictly no text, no words, no borders",
            f"Japanese anime style vibrant scenery depicting '{clean_title}' by {clean_artist}, edge-to-edge borderless full bleed composition, highly saturated colors, high contrast, zero typography, no text, no borders, no letters",
            f"Bold colorful representation of {clean_artist} and the vibe of '{clean_title}', edge-to-edge borderless canvas, thick lines, neon and primary colors, flat design for pixel grid, strictly no text, no frames, zero words"
        ]
        
        song_signature = f"{clean_artist}_{clean_title}".lower()
        prompt_index = abs(hash(song_signature)) % len(prompts)
        selected_prompt = prompts[prompt_index]
        encoded_prompt = urllib.parse.quote(selected_prompt, safe='')
        
        seed = abs(hash(song_signature)) % 2147483647
        user_model = str(getattr(self.config, 'ai_fallback', 'black-forest-labs/flux.1-schnell') or 'black-forest-labs/flux.1-schnell').lower().strip()
        
        if user_model in ["turbo", "lightning"]:
            model = "inferenceport-ai/lightning-image-turbo"
        elif user_model in ["flux", "schnell"]:
            model = "black-forest-labs/flux.1-schnell"
        elif user_model == "vector":
            model = "recraft/recraft-v4.1-vector"
        else:
            model = user_model

        url_params = f"?model={model}&width=512&height=512&seed={seed}&nologo=true&key={api_key.strip()}"
        return f"https://gen.pollinations.ai/image/{encoded_prompt}{url_params}"


class InternetArchiveProvider:
    """Searches the Internet Archive (archive.org) for metadata and album/item cover art
    using their open public search and metadata APIs (no API key required)."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def search_artwork(self, artist: str, title: str) -> Optional[str]:
        clean_artist = str(artist or "").strip()
        clean_title = str(title or "").strip()
        if not clean_artist or not clean_title or clean_artist == "Unknown Artist":
            return None

        query = f'artist:( "{clean_artist}" ) AND title:( "{clean_title}" )'
        search_url = "https://archive.org/advancedsearch.php"
        params = {
            "q": query,
            "fl[]": "identifier",
            "rows": 3,
            "page": 1,
            "output": "json"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }

        try:
            async with self.session.get(search_url, params=params, headers=headers, timeout=8) as response:
                if response.status != 200:
                    return None
                
                data = await response.json(content_type=None)
                docs = data.get("response", {}).get("docs", [])
                if not docs:
                    return None

                for doc in docs:
                    identifier = doc.get("identifier")
                    if not identifier:
                        continue
                    
                    meta_url = f"https://archive.org/metadata/{identifier}"
                    async with self.session.get(meta_url, headers=headers, timeout=8) as meta_resp:
                        if meta_resp.status != 200:
                            continue
                        meta_data = await meta_resp.json(content_type=None)
                        files = meta_data.get("files", [])
                        
                        for file_info in files:
                            name = file_info.get("name", "").lower()
                            if name.endswith((".jpg", ".jpeg", ".png")) and ("cover" in name or "thumb" in name or "front" in name):
                                return f"https://archive.org/download/{identifier}/{file_info.get('name')}"
                        
                        for file_info in files:
                            name = file_info.get("name", "").lower()
                            if name.endswith((".jpg", ".jpeg", ".png")):
                                return f"https://archive.org/download/{identifier}/{file_info.get('name')}"

        except Exception as e:
            _LOGGER.debug("Internet Archive search exception: %s", e)

        return None

class TheAudioDbProvider:
    def __init__(self, session: aiohttp.ClientSession, config: "Config" = None):
        self.session = session
        self.config = config

    async def get_artist_images(self, artist: str) -> List[str]:
        if self.config and not getattr(self.config, 'audiodb_enabled', True):
            return []

        clean_artist = str(artist or "").strip()
        if not clean_artist or clean_artist == "Unknown Artist":
            return []
            
        raw_artists = [
            a.strip() for a in re.split(r'[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+', clean_artist, flags=re.IGNORECASE) 
            if a.strip()
        ]
        
        urls = []
        for a in raw_artists:
            url = f"https://www.theaudiodb.com/api/v1/json/123/search.php?s={urllib.parse.quote(a)}"
            try:
                async with self.session.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        artists_data = data.get("artists")
                        
                        if artists_data and isinstance(artists_data, list):
                            ad = artists_data[0]
                            for key in ["strArtistThumb", "strArtistFanart", "strArtistFanart2", "strArtistFanart3", "strArtistFanart4", "strArtistClearart", "strArtistWideThumb"]:
                                val = ad.get(key)
                                if val and isinstance(val, str) and val.startswith("http"):
                                    urls.append(val)
            except Exception as e:
                _LOGGER.debug("AudioDB search exception: %s", e)
        
        return list(OrderedDict.fromkeys(urls))
    
# =========================================================================
# FALLBACK COORDINATOR SERVICE
# =========================================================================

class FallbackService:
    def __init__(self, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession, spotify_service: "SpotifyService", pixoo_device: "PixooDevice"): 
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.spotify_service = spotify_service
        self.pixoo_device = pixoo_device
        self.fail_txt = False
        self.fallback = False
        self._artwork_cache: OrderedDict[str, dict] = OrderedDict()
        
        # Modularized Providers
        self.mb_provider = MusicBrainzProvider(session)
        self.discogs_provider = DiscogsProvider(config, session)
        self.lastfm_provider = LastFmProvider(config, session)
        self.tidal_provider = TidalProvider(config, session)
        self.ai_provider = AiArtProvider(config)
        self.ia_provider = InternetArchiveProvider(session)
        self.audiodb_provider = TheAudioDbProvider(session, config)

    async def get_musicbrainz_album_art_url(self, artist: str, title: str):
        return await self.mb_provider.get_album_art_url(artist, title)

    async def search_discogs_album_art(self, artist: str, title: str):
        return await self.discogs_provider.search_album_art(artist, title)

    async def search_lastfm_album_art(self, artist: str, title: str, album: Optional[str] = None):
        return await self.lastfm_provider.search_album_art(artist, title, album)

    async def get_tidal_album_art_url(self, artist: str, title: str):
        return await self.tidal_provider.get_album_art_url(artist, title)

    async def get_tidal_access_token(self):
        return await self.tidal_provider.get_access_token()

    async def play_artist_gallery_slide(self, pixoo_device: "PixooDevice", media_data: "MediaData") -> None:
        media_data.artist_slide_pass = False
        try:
            urls = getattr(media_data, 'slider_album_urls', None)
            if not urls:
                urls = await self.audiodb_provider.get_artist_images(media_data.artist)
                
            if not urls or len(urls) < 2:
                media_data.slider_error = "Not enough artist images found"
                return

            media_data.slider_album_urls = urls

            try:
                preview_raw = await self.image_processor.get_raw_image_data(urls[0])
                if preview_raw:
                    preview_b64 = await self.image_processor.process_slide_image(preview_raw, media_data)
                    if preview_b64:
                        await pixoo_device.send_command({
                            "Command": "Draw/CommandList", 
                            "CommandList": [
                                {"Command": "Draw/ResetHttpGifId"},
                                {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 1000, "PicData": preview_b64}
                            ]
                        })
            except Exception as e:
                _LOGGER.debug("Artist Slide preview error: %s", e)

            sem = asyncio.Semaphore(5)
            async def process_pipeline(url):
                async with sem:
                    try:
                        raw_data = await self.image_processor.get_raw_image_data(url)
                        if raw_data:
                            return await self.image_processor.process_slide_image(raw_data, media_data)
                    except Exception as err:
                        _LOGGER.error("Artist Slide pipeline error: %s", err)
                    return None

            tasks = [process_pipeline(u) for u in urls[:10]]
            frames_b64 = await asyncio.gather(*tasks)
            frames_b64 = [f for f in frames_b64 if f]

            if len(frames_b64) < 2:
                media_data.slider_error = "Failed to process enough frames"
                return

            media_data.artist_slide_pass = True
            media_data.slider_frames = len(frames_b64)
            
            await pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [{"Command": "Draw/ResetHttpGifId"}]
            })
            
            for pic_offset, b64_frame in enumerate(frames_b64):
                await pixoo_device.send_command({
                    "Command": "Draw/SendHttpGif", 
                    "PicNum": len(frames_b64), 
                    "PicWidth": 64, 
                    "PicOffset": pic_offset, 
                    "PicID": 0, 
                    "PicSpeed": 5000, 
                    "PicData": b64_frame
                })
        except Exception as e:
            media_data.slider_error = str(e)
            _LOGGER.error("Artist Gallery Slide Error: %s", e)

    async def prefetch_next_track(self, url: Optional[str], media_data: "MediaData"):
        await self.get_final_url(url, media_data)
        frames = 0
        if getattr(self.config, 'spotify_slide', False) and not getattr(media_data, 'radio_logo', False):
            frames = await self.spotify_service.prefetch_slider_data(media_data)
        elif getattr(self.config, 'artist_slide', False) and not getattr(media_data, 'radio_logo', False):
            urls = await self.audiodb_provider.get_artist_images(media_data.artist)
            media_data.slider_album_urls = urls
            frames = len(urls)
            for u in urls[:10]:
                await self.image_processor.async_prefetch_url(u, media_data)
        media_data.slider_frames = frames

    async def get_final_url(self, picture: Optional[str], media_data: "MediaData") -> Optional[dict]: 
        self.fail_txt = False
        self.fallback = False
        media_data.pic_url = None 
        
        if getattr(self.config, 'burned', False) or not media_data.album:
            song_cache_key = f"{media_data.artist}_{media_data.title}".strip().lower()
        else:
            song_cache_key = f"{media_data.artist}_{media_data.album}".strip().lower()

        is_spotify_slider = (
            getattr(self.config, 'spotify_slide', False) 
            and not getattr(media_data, 'radio_logo', False) 
            and not getattr(media_data, 'playing_tv', False)
        )
        is_artist_slider = (
            getattr(self.config, 'artist_slide', False) 
            and not getattr(media_data, 'radio_logo', False) 
            and not getattr(media_data, 'playing_tv', False)
        )
        
        if not is_spotify_slider and not is_artist_slider and getattr(self.config, 'force_ai', False) and getattr(self.config, 'pollinations', None) and not getattr(media_data, 'radio_logo', False) and not getattr(media_data, 'playing_tv', False):
            ai_res = await self._try_ai_generation(media_data)
            if ai_res:
                return ai_res
            _LOGGER.warning("Force AI generation failed; falling back to standard artwork.")

        if picture == "TV_IS_ON_ICON":
            media_data.pic_source = "Internal"
            media_data.pic_url = "TV Icon"
            tv_icon_img = self.create_tv_icon_image()
            tv_icon_base64 = self.image_processor.gbase64(tv_icon_img)
            return { 
                'base64_image': tv_icon_base64,
                'font_color': '#FF00FF',
                'brightness': 0.67,
                'brightness_lower_part': 0.5,
                'background_color': '#000000',
                'background_color_rgb': (0, 0, 0),
                'color1': '#000000',
                'color2': '#000000',
                'color3': '#000000'
            }

        if not getattr(self.config, 'force_ai', False) and song_cache_key in self._artwork_cache:
            cached = self._artwork_cache[song_cache_key]
            if not is_spotify_slider and not is_artist_slider or cached.get('source') in ["Spotify", "Spotify Artist", "Spotify (Artist Profile Image)", "Original"]:
                media_data.pic_url = cached['url']
                media_data.pic_source = cached['source']
                _LOGGER.debug("Reusing resolved artwork for '%s' from %s", song_cache_key, cached['source'])
                return cached['data']

        try:
            if picture and not (getattr(media_data, 'playing_radio', False) and not getattr(media_data, 'radio_logo', False)):
                is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
                result = await self.image_processor.get_image(picture, media_data, is_slide_pass)
                if result:
                    self._save_to_artwork_cache(song_cache_key, result, picture, "Original")
                    media_data.pic_source = "Original"
                    media_data.pic_url = picture
                    return result
        except Exception as e: 
            _LOGGER.error("Original picture processing failed: %s", e) 

        self.spotify_first_album = None
        self.spotify_artist_pic = None

        if getattr(self.config, 'spotify_client_id', None) and getattr(self.config, 'spotify_client_secret', None):
            try:
                album_id, first_album = await self.spotify_service.get_spotify_album_id(media_data)
                if first_album:
                    self.spotify_first_album = await self.spotify_service.get_spotify_album_image_url(first_album)
                if album_id:
                    image_url = await self.spotify_service.get_spotify_album_image_url(album_id)
                    if image_url:
                        is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
                        proc_res = await self.image_processor.get_image(image_url, media_data, is_slide_pass)
                        if proc_res:
                            self._save_to_artwork_cache(song_cache_key, proc_res, image_url, "Spotify")
                            media_data.pic_url = image_url
                            media_data.pic_source = "Spotify"
                            return proc_res
                self.spotify_artist_pic = await self.spotify_service.get_spotify_artist_image_url_by_name(media_data.artist)
            except Exception as e: 
                _LOGGER.error("Spotify fallback failed: %s", e) 

        if self.spotify_artist_pic:
            is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
            result = await self.image_processor.get_image(self.spotify_artist_pic, media_data, is_slide_pass)
            if result:
                self._save_to_artwork_cache(song_cache_key, result, self.spotify_artist_pic, "Spotify Artist")
                media_data.pic_source = "Spotify Artist"
                return result

        if self.spotify_first_album:
            is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
            result = await self.image_processor.get_image(self.spotify_first_album, media_data, is_slide_pass)
            if result:
                self._save_to_artwork_cache(song_cache_key, result, self.spotify_first_album, "Spotify (Artist Profile Image)")
                media_data.pic_url = self.spotify_first_album
                media_data.pic_source = "Spotify (Artist Profile Image)"
                return result

        if is_spotify_slider or is_artist_slider:
            media_data.pic_url = "Fallback Image"
            media_data.pic_source = "Internal"
            return self._get_fallback_black_image_data(media_data)

        tasks, providers = [], []
        if getattr(self.config, 'discogs', None):
            tasks.append(self.discogs_provider.search_album_art(media_data.artist, media_data.title))
            providers.append("Discogs")

        if getattr(self.config, 'lastfm', None):
            tasks.append(self.lastfm_provider.search_album_art(media_data.artist, media_data.title, media_data.album))
            providers.append("Last.FM")
            
        tidal_id = getattr(self.config, 'tidal_client_id', None)
        tidal_secret = getattr(self.config, 'tidal_client_secret', None)
        if tidal_id and tidal_secret:
            tasks.append(self.tidal_provider.get_album_art_url(media_data.artist, media_data.title))
            providers.append("TIDAL")
            
        if getattr(self.config, 'musicbrainz', False):
            tasks.append(self.mb_provider.get_album_art_url(media_data.artist, media_data.title))
            providers.append("MusicBrainz")

        if getattr(self.config, 'internet_archive', False):
            tasks.append(self.ia_provider.search_artwork(media_data.artist, media_data.title))
            providers.append("Internet Archive")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) or not result: continue
                provider_name = providers[i]
                is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
                proc_result = await self.image_processor.get_image(result, media_data, is_slide_pass)
                if proc_result:
                    self._save_to_artwork_cache(song_cache_key, proc_result, result, provider_name)
                    media_data.pic_url = result
                    media_data.pic_source = provider_name
                    return proc_result

        if not getattr(self.config, 'force_ai', False) and getattr(self.config, 'audiodb_enabled', True):
            audiodb_urls = await self.audiodb_provider.get_artist_images(media_data.artist)
            if audiodb_urls:
                for img_url in audiodb_urls:
                    is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
                    proc_result = await self.image_processor.get_image(img_url, media_data, is_slide_pass)
                    if proc_result:
                        self._save_to_artwork_cache(song_cache_key, proc_result, img_url, "TheAudioDB")
                        media_data.pic_url = img_url
                        media_data.pic_source = "TheAudioDB"
                        return proc_result

        if not getattr(self.config, 'force_ai', False) and getattr(self.config, 'pollinations', None):
            result = await self._try_ai_generation(media_data)
            if result: 
                if media_data.pic_url:
                    self._save_to_artwork_cache(song_cache_key, result, media_data.pic_url, "AI")
                media_data.pic_source = "AI"
                return result

        media_data.pic_url = "Fallback Image"
        media_data.pic_source = "Internal"
        return self._get_fallback_black_image_data(media_data)

    def _save_to_artwork_cache(self, key: str, data: dict, url: str, source: str):
        # Strict cap of 40 artwork resolutions in cache
        if len(self._artwork_cache) >= 40:
            self._artwork_cache.popitem(last=False)
        self._artwork_cache[key] = {
            'data': data,
            'url': url,
            'source': source
        }

    async def _try_ai_generation(self, media_data):
        ai_url = self.ai_provider.format_prompt_url(media_data.artist, media_data.title)
        if not ai_url: return None
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                is_slide_pass = getattr(media_data, 'spotify_slide_pass', False) or getattr(media_data, 'artist_slide_pass', False)
                result = await asyncio.wait_for(
                    self.image_processor.get_image(ai_url, media_data, is_slide_pass),
                    timeout=25
                )
                
                if result: 
                    _LOGGER.info("Successfully generated AI album art on attempt %s", attempt + 1)
                    media_data.pic_url = ai_url
                    media_data.pic_source = "AI"
                    return result
                    
            except asyncio.TimeoutError:
                _LOGGER.warning("AI generation timed out (Attempt %s/%s)", attempt + 1, max_retries + 1)
            except Exception as e:
                _LOGGER.warning("AI generation failed: %s (Attempt %s/%s)", e, attempt + 1, max_retries + 1)
            
            if attempt < max_retries: 
                await asyncio.sleep(1.5)
                
        return None

    def _get_fallback_black_image_data(self, media_data: Optional["MediaData"] = None) -> dict: 
        self.fail_txt = True
        self.fallback = True
        
        img = Image.new("RGB", (64, 64), (25, 25, 30)) 
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 63, 63], outline=(50, 50, 60), width=1)
        
        if media_data:
            artist = getattr(media_data, 'artist', 'Unknown Artist')
            title = getattr(media_data, 'title', 'Unknown Track')
            
            if artist == "Unknown Artist" and title == "Unknown Track":
                draw.ellipse([24, 34, 32, 42], fill=(150, 150, 150))
                draw.ellipse([38, 30, 46, 38], fill=(150, 150, 150))
                draw.line([(32, 38), (32, 18)], fill=(150, 150, 150), width=2)
                draw.line([(46, 34), (46, 14)], fill=(150, 150, 150), width=2)
                draw.line([(32, 18), (46, 14)], fill=(150, 150, 150), width=2)
                draw.line([(32, 19), (46, 15)], fill=(150, 150, 150), width=2)
            else:
                img = self.image_processor._draw_burned_text(img, artist, title)
                
        return { 
            'base64_image': self.image_processor.gbase64(img),
            'font_color': '#FFFFFF', 
            'brightness_lower_part': 0.5,
            'background_color': '#19191E', 
            'background_color_rgb': (25, 25, 30),
            'color1': '#19191E',
            'color2': '#19191E',
            'color3': '#19191E'
        }

    def create_tv_icon_image(self) -> Image.Image: 
        image_width = 300
        image_height = 300
        final_width = 64
        final_height = 64
        vertical_offset = 10
        black = (0, 0, 0)
        brown = (139, 69, 19)  
        screen_bg = (240, 240, 240) 
        white = (255, 255, 255)
        gray = (150, 150, 150)
        rainbow_colors = [
            (255, 0, 0),     
            (255, 165, 0),   
            (255, 255, 0),   
            (0, 255, 0),     
            (0, 0, 255),     
            (75, 0, 130),    
            (238, 130, 238)  
        ]
        image = Image.new("RGB", (image_width, image_height), black)
        draw = ImageDraw.Draw(image)
        tv_body_padding = 60 + vertical_offset  
        tv_body_rect = [
            tv_body_padding,
            tv_body_padding,
            image_width - tv_body_padding,
            image_height - tv_body_padding - 40
        ]
        tv_body_radius = 20
        draw.rounded_rectangle(tv_body_rect, tv_body_radius, fill=brown)
        screen_padding = tv_body_padding + 15 
        screen_rect = [
            screen_padding,
            screen_padding,
            image_width - screen_padding,
            tv_body_rect[3] - 15
        ]
        draw.rectangle(screen_rect, fill=screen_bg)
        num_bars = len(rainbow_colors)
        bar_width = (screen_rect[2] - screen_rect[0]) // num_bars
        start_x = screen_rect[0]
        for color in rainbow_colors:
            bar_rect = [
                start_x,
                screen_rect[1],
                start_x + bar_width,
                screen_rect[3]
            ]
            draw.rectangle(bar_rect, fill=color)
            start_x += bar_width
        antenna_color = gray
        antenna_thickness = 3
        antenna_length = 50
        antenna_base_x1 = image_width // 2 - 30
        antenna_base_x2 = image_width // 2 + 30
        antenna_base_y = tv_body_padding  
        draw.line(
            (antenna_base_x1, antenna_base_y, antenna_base_x1 - 20, antenna_base_y - antenna_length),
            fill=antenna_color, width=antenna_thickness
        )
        draw.line(
            (antenna_base_x2, antenna_base_y, antenna_base_x2 + 20, antenna_base_y - antenna_length),
            fill=antenna_color, width=antenna_thickness
        )
        highlight_color = white
        highlight_thickness = 4
        draw.line(
            (tv_body_rect[0], tv_body_rect[1], tv_body_rect[0] + 20, tv_body_rect[1]),
            fill=highlight_color, width=highlight_thickness
        )
        draw.line(
            (tv_body_rect[0], tv_body_rect[1], tv_body_rect[0], tv_body_rect[1] + 20),
            fill=highlight_color, width=highlight_thickness
        )
        image = image.resize((final_width, final_height), Image.Resampling.BILINEAR)
        return image
  
# =========================================================================
# SPOTIFY SERVICE
# =========================================================================

class SpotifyService:
    def __init__(self, config: "Config", session: aiohttp.ClientSession, image_processor: "ImageProcessor"): 
        self.config = config
        self.session = session
        self.image_processor = image_processor
        self.spotify_token_cache: dict[str, Any] = {'token': None, 'expires': 0}
        self.spotify_data: Optional[dict] = None 
        self._semaphore = asyncio.Semaphore(5)

    async def get_spotify_access_token(self) -> Optional[str]: 
        if self.spotify_token_cache['token'] and time.time() < self.spotify_token_cache['expires']:
            return self.spotify_token_cache['token']
            
        if not self.config.spotify_client_id or not self.config.spotify_client_secret: 
            return None

        url = "https://accounts.spotify.com/api/token"
        auth_string = base64.b64encode(f"{self.config.spotify_client_id}:{self.config.spotify_client_secret}".encode()).decode()
        spotify_headers = {
            "Authorization": f"Basic {auth_string}", 
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            async with self.session.post(url, headers=spotify_headers, data={"grant_type": "client_credentials"}, timeout=10) as response: 
                response.raise_for_status() 
                response_json = await response.json()
                access_token = response_json["access_token"]
                
                self.spotify_token_cache = {
                    'token': access_token, 
                    'expires': time.time() + response_json.get("expires_in", 3600) - 60
                }
                return access_token
        except aiohttp.ClientError as e:
            _LOGGER.error("Network error while fetching Spotify token: %s", e)
        except Exception as e:
            _LOGGER.error("Unexpected error fetching Spotify token: %s", e)
            
        return None

    async def _async_spotify_request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        token = await self.get_spotify_access_token()
        if not token: 
            return None
            
        url = f"https://api.spotify.com/v1/{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}", 
            "Content-Type": "application/json"
        }
        
        try:
            async with self.session.get(url, headers=headers, params=params, timeout=10) as response: 
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    self.spotify_token_cache = {'token': None, 'expires': 0}
        except aiohttp.ClientError as e:
            _LOGGER.error("Spotify API request failed for endpoint '%s': %s", endpoint, e)
        except Exception as e:
            _LOGGER.error("Unexpected error in Spotify API request for '%s': %s", endpoint, e)
            
        return None

    async def get_spotify_json(self, artist: str, title: str) -> Optional[dict]: 
        clean_title = re.sub(r'[\'\"()]', '', str(title or '')).strip()
        clean_artist = re.sub(r'[\'\"()]', '', str(artist or '')).strip()
        
        params = {
            "q": f'track:"{clean_title}" artist:"{clean_artist}"', 
            "type": "track", 
            "limit": 50
        }
        data = await self._async_spotify_request("search", params=params)
        if data and data.get('tracks', {}).get('items'):
            return data

        params_loose = {
            "q": f"{clean_artist} {clean_title}", 
            "type": "track", 
            "limit": 50
        }
        return await self._async_spotify_request("search", params=params_loose)

    async def get_spotify_artist_image_url_by_name(self, artist_name: str) -> Optional[str]: 
        if not artist_name: 
            return None
            
        primary_artist = re.split(r'[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+', artist_name, flags=re.IGNORECASE)[0].strip()
        params = {
            "q": f"artist:{primary_artist}", 
            "type": "artist", 
            "limit": 1
        }
        
        data = await self._async_spotify_request("search", params=params)
        
        if data and 'artists' in data and data['artists']['items']:
            artist_id = data['artists']['items'][0]['id']
            art_data = await self._async_spotify_request(f"artists/{artist_id}")
            
            if art_data and art_data.get('images'):
                return art_data['images'][0]['url']
                
        return None

    async def prepare_slider_for_media(self, media_data: "MediaData") -> list[str]:
        if getattr(media_data, 'slider_album_urls', None):
            return media_data.slider_album_urls

        media_data.slider_error = None
        spotify_json = await self.get_spotify_json(media_data.artist, media_data.title)
        if not spotify_json:
            media_data.slider_error = "Track not found on Spotify"
            return []

        self.spotify_data = spotify_json 

        artist_pic = await self.get_spotify_artist_image_url_by_name(media_data.artist)
        media_data.slider_artist_pic_url = artist_pic

        tracks = spotify_json.get('tracks', {}).get('items', [])
        albums = {}
        
        raw_artists = [
            a.strip().lower() 
            for a in re.split(r'[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+', media_data.artist, flags=re.IGNORECASE) 
            if a.strip()
        ]

        for track in tracks:
            album = track.get('album', {})
            album_id = album.get('id')
            album_artists = [a.get('name', '').strip().lower() for a in album.get('artists', [])]
            
            if any('various artists' in a for a in album_artists): 
                continue
                
            is_match = any(
                ra in aa or aa in ra
                for ra in raw_artists
                for aa in album_artists
            )
            if not is_match and len(raw_artists) > 0:
                continue
                
            if album_id and album_id not in albums: 
                albums[album_id] = album

        sorted_albums = sorted(
            albums.values(), 
            key=lambda x: (x.get("album_type") == "single", x.get("album_type") == "album"), 
            reverse=True
        )[:10]
        
        album_urls = [alb.get("images", [])[0]["url"] for alb in sorted_albums if alb.get("images")]
        media_data.slider_album_urls = album_urls
        media_data.slider_frames = len(album_urls)
        media_data.pic_url = album_urls
        media_data.pic_source = "Spotify (Slide)"
        
        if len(album_urls) < 2:
            media_data.slider_error = f"Found only {len(album_urls)} albums (minimum 2 needed)"
            
        return album_urls

    async def get_album_list(self, media_data: "MediaData", returntype: str = "url") -> list[str]: 
        if getattr(media_data, 'playing_tv', False): 
            return []
        return await self.prepare_slider_for_media(media_data)

    async def get_slide_img(self, picture: str, media_data: "MediaData") -> Optional[str]: 
        try:
            image_raw_data = await self.image_processor.get_raw_image_data(picture)
            if image_raw_data:
                return await self.image_processor.process_slide_image(image_raw_data, media_data)
        except Exception as e: 
            _LOGGER.error("Failed to process slide image: %s", e)
        return None

    async def prefetch_slider_data(self, media_data: "MediaData") -> int:
        urls = await self.prepare_slider_for_media(media_data)
        if media_data.slider_artist_pic_url:
            await self.image_processor.async_prefetch_url(media_data.slider_artist_pic_url, media_data)
        for url in urls:
            await self.image_processor.async_prefetch_url(url, media_data)
        return len(urls)

    async def send_pixoo_animation_frame(
        self, pixoo_device: "PixooDevice", command: str, pic_num: int, 
        pic_width: int, pic_offset: int, pic_id: int, pic_speed: int, pic_data: str
    ) -> None: 
        await pixoo_device.send_command({
            "Command": command, 
            "PicNum": pic_num, 
            "PicWidth": pic_width, 
            "PicOffset": pic_offset, 
            "PicID": pic_id, 
            "PicSpeed": pic_speed, 
            "PicData": pic_data
        })

    async def spotify_albums_slide(self, pixoo_device: "PixooDevice", media_data: "MediaData", prev_channel: int) -> None: 
        media_data.spotify_slide_pass = False 
        try:
            album_urls = getattr(media_data, 'slider_album_urls', None) or await self.prepare_slider_for_media(media_data)
            if not album_urls or len(album_urls) < 2: 
                return

            artist_pic_url = getattr(media_data, 'slider_artist_pic_url', None) or await self.get_spotify_artist_image_url_by_name(media_data.artist)
            if artist_pic_url:
                preview_b64 = await self.get_slide_img(artist_pic_url, media_data)
                if preview_b64:
                    await pixoo_device.send_command({
                        "Command": "Draw/CommandList", 
                        "CommandList": [
                            {"Command": "Draw/ResetHttpGifId"},
                            {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 1000, "PicData": preview_b64}
                        ]
                    })

            async def process_pipeline(url):
                async with self._semaphore:
                    try:
                        raw_data = await self.image_processor.get_raw_image_data(url)
                        if raw_data:
                            return await self.image_processor.process_slide_image(raw_data, media_data)
                    except Exception as err: 
                        _LOGGER.error("Slide image pipeline error: %s", err)
                    return None

            tasks = [process_pipeline(url) for url in album_urls[:10]]
            album_urls_b64 = await asyncio.gather(*tasks)
            album_urls_b64 = [res for res in album_urls_b64 if res]

            frames = len(album_urls_b64)
            if frames < 2: 
                media_data.slider_error = "Insufficient valid frames processed"
                return

            media_data.spotify_slide_pass = True
            media_data.slider_frames = frames
            
            await pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [{"Command": "Draw/ResetHttpGifId"}]
            })
            
            for pic_offset, b64_frame in enumerate(album_urls_b64):
                await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", frames, 64, pic_offset, 0, 5000, b64_frame)
                
        except Exception as e: 
            media_data.slider_error = str(e)
            _LOGGER.error("Spotify Albums Slide Animation Error: %s", e)

    def _build_preview_frame_sync(self, artist_img: Image.Image, media_data: "MediaData") -> Optional[str]:
        try:
            preview_canvas = Image.new("RGB", (64, 64), (0, 0, 0))
            preview_canvas.paste(artist_img, (16, 8)) 
            
            cached_data = {}
            preview_canvas = self.image_processor.text_clock_img(preview_canvas, cached_data, media_data)
            
            return self.image_processor.gbase64(preview_canvas)
        except Exception as e:
            _LOGGER.error("Error building preview frame: %s", e)
            return None

    def _build_animation_frames_sync(self, prepared_albums: list, media_data: "MediaData") -> list:
        try:
            pixoo_frames = []
            total_frames = min(len(prepared_albums), 10)
            x_pos = [1, 16, 51]

            for i in range(total_frames):
                canvas = Image.new("RGB", (64, 64), (0, 0, 0))
                l = (i - 1) % len(prepared_albums)
                c = i % len(prepared_albums)
                r = (i + 1) % len(prepared_albums)
                
                canvas.paste(prepared_albums[l]["inactive"], (x_pos[0], 8))
                canvas.paste(prepared_albums[c]["active"], (x_pos[1], 8))
                canvas.paste(prepared_albums[r]["inactive"], (x_pos[2], 8))
                
                cached_data = {}
                canvas = self.image_processor.text_clock_img(canvas, cached_data, media_data)
                
                frame_b64 = self.image_processor.gbase64(canvas)
                if frame_b64:
                    pixoo_frames.append(frame_b64)
                    
            return pixoo_frames
        except Exception as e:
            _LOGGER.error("Error building animation frames: %s", e)
            return []

    async def spotify_album_art_animation(self, pixoo_device: "PixooDevice", media_data: "MediaData", prev_channel: int) -> None: 
        if getattr(media_data, 'playing_tv', False): 
            return 
            
        media_data.spotify_slide_pass = False
        
        try:
            album_urls = getattr(media_data, 'slider_album_urls', None) or await self.prepare_slider_for_media(media_data)
            if not album_urls or len(album_urls) < 2: 
                return

            artist_img = None
            artist_pic_url = getattr(media_data, 'slider_artist_pic_url', None) or await self.get_spotify_artist_image_url_by_name(media_data.artist)
            
            if artist_pic_url:
                raw_data = await self.image_processor.get_raw_image_data(artist_pic_url)
                if raw_data:
                    artist_img = await self.image_processor.hass.async_add_executor_job(_resize_image_sync, raw_data)
                    
                    if artist_img:
                        preview_b64 = await self.image_processor.hass.async_add_executor_job(
                            self._build_preview_frame_sync, artist_img, media_data
                        )
                        
                        if preview_b64:
                            await pixoo_device.send_command({
                                "Command": "Draw/CommandList", 
                                "CommandList": [
                                    {"Command": "Draw/ResetHttpGifId"},
                                    {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 1000, "PicData": preview_b64}
                                ]
                            })

            def prepare_album_variants(raw_data):
                try:
                    img = Image.open(BytesIO(raw_data))
                    img.load()
                    img = img.convert("RGB")
                    img = img.resize((34, 34), Image.Resampling.BILINEAR)
                    
                    active = img.copy()
                    draw = ImageDraw.Draw(active)
                    draw.rectangle([0, 0, 33, 33], outline="black", width=1)
                    
                    inactive = img.filter(ImageFilter.GaussianBlur(2))
                    inactive = ImageEnhance.Brightness(inactive).enhance(0.5)
                    
                    return {"active": active, "inactive": inactive}
                except Exception as e: 
                    _LOGGER.error("Error preparing album variant: %s", e)
                    return None

            async def download(url):
                return await self.image_processor.get_raw_image_data(url)

            raw_datas = await asyncio.gather(*[download(u) for u in album_urls[:10]])
            raw_datas = [d for d in raw_datas if d]

            tasks = [self.image_processor.hass.async_add_executor_job(prepare_album_variants, d) for d in raw_datas]
            prepared_albums = await asyncio.gather(*tasks)
            prepared_albums = [a for a in prepared_albums if a]

            if artist_img:
                a_img = artist_img.copy()
                draw = ImageDraw.Draw(a_img)
                draw.rectangle([0, 0, 33, 33], outline="black", width=1)
                
                i_img = artist_img.filter(ImageFilter.GaussianBlur(2))
                i_img = ImageEnhance.Brightness(i_img).enhance(0.5)
                
                prepared_albums.insert(0, {"active": a_img, "inactive": i_img})

            if len(prepared_albums) < 3: 
                return

            pixoo_frames = await self.image_processor.hass.async_add_executor_job(
                self._build_animation_frames_sync, prepared_albums, media_data
            )
            
            if not pixoo_frames:
                return

            media_data.spotify_slide_pass = True 
            media_data.slider_frames = len(pixoo_frames)
            
            await pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [{"Command": "Draw/ResetHttpGifId"}]
            })
            
            for offset, frame in enumerate(pixoo_frames):
                await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", len(pixoo_frames), 64, offset, 0, 5000, frame)
            
        except Exception as e:
            media_data.slider_error = str(e)
            _LOGGER.error("Spotify Animation Error: %s", e)

    async def spotify_best_album(self, tracks: list[dict], artist: str) -> tuple[Optional[str], Optional[str]]: 
        best_album = None
        earliest_year = float('inf')
        preferred_types = ["single", "album", "compilation"]
        first_album_id = tracks[0]['album']['id'] if tracks else None 
        
        for track in tracks:
            album = track.get('album')
            album_type = album.get('album_type')
            release_date = album.get('release_date')
            
            year = int(release_date[:4]) if release_date and release_date[:4].isdigit() else float('inf') 
            artists = album.get('artists', [])
            album_artist = artists[0]['name'] if artists else ""
            
            if artist.lower() == album_artist.lower():
                if album_type in preferred_types:
                    if year < earliest_year: 
                        earliest_year = year
                        best_album = album
                elif year < earliest_year: 
                    earliest_year = year
                    best_album = album

        if best_album:
            return best_album['id'], first_album_id
        else:
            return None, first_album_id

    async def get_spotify_album_id(self, media_data: "MediaData") -> tuple[Optional[str], Optional[str]]: 
        try:
            self.spotify_data = None 
            response_json = await self.get_spotify_json(media_data.artist, media_data.title)
            
            if not response_json:
                return None, None
                
            self.spotify_data = response_json 
            tracks = response_json.get('tracks', {}).get('items', [])
            
            if tracks:
                best_album_id, first_album_id = await self.spotify_best_album(tracks, media_data.artist)
                return best_album_id, first_album_id
                
            return None, None 
        except Exception as e: 
            _LOGGER.error("Error retrieving Spotify Album ID: %s", e)
            return None, None

    async def get_spotify_album_image_url(self, album_id: str) -> Optional[str]: 
        if not album_id:
            return None
            
        response_json = await self._async_spotify_request(f"albums/{album_id}")
        
        if response_json and response_json.get('images'):
            return response_json['images'][0]['url'] 
            
        return None

# =========================================================================
# LYRICS PROVIDER
# =========================================================================

class LyricsProvider:
    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session 
        self.lyrics_cache: OrderedDict[str, list] = OrderedDict()
        self.visual_timeline: list[dict] = [] 
        self.current_song_key: Optional[str] = None
        self.current_frame_index: int = -1  
        self.filler_regex = re.compile(r"(?:[\s\W]+(?:oh+|ooh+|yeah|yea|woah|la+|na+)+[\W]*)+$", re.IGNORECASE)

    async def get_lyrics(self, artist: Optional[str], title: str, album: Optional[str] = None, duration: int = 0) -> list[dict]:
        if not artist or not title: return []
        new_key = f"{artist}|{title}".lower()
        if new_key == self.current_song_key: return self.lyrics_cache.get(new_key, [])
        self.visual_timeline = []
        self.current_song_key = new_key
        
        if new_key in self.lyrics_cache:
            self.lyrics_cache.move_to_end(new_key)
            raw_lyrics = self.lyrics_cache[new_key]
            self._build_visual_timeline(raw_lyrics) 
            return raw_lyrics

        fetched_lyrics = []
        base_url_get = "https://lrclib.net/api/get"
        params = { 'artist_name': artist, 'track_name': title }
        headers = {"User-Agent": "Pixoo64-HomeAssistant-Integration/1.0"}
        
        try:
            async with self.session.get(base_url_get, params=params, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('syncedLyrics'):
                        fetched_lyrics = self._parse_lrc(data['syncedLyrics'])
        except Exception: pass

        if not fetched_lyrics:
            try:
                base_url_search = "https://lrclib.net/api/search"
                search_params = {'q': f"{artist} {title}"}
                async with self.session.get(base_url_search, params=search_params, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        results = await response.json()
                        if results and isinstance(results, list):
                            best_candidate = None
                            best_score = 0
                            for item in results:
                                if not item.get('syncedLyrics'): continue
                                score = self._calculate_fuzzy_score(artist, title, float(duration) if duration else 0, item.get('artistName'), item.get('trackName'), item.get('duration'))
                                if score > 60 and score > best_score:
                                    best_score = score
                                    best_candidate = item
                            if best_candidate:
                                fetched_lyrics = self._parse_lrc(best_candidate['syncedLyrics'])
            except Exception: pass

        if len(self.lyrics_cache) >= 40: 
            self.lyrics_cache.popitem(last=False)
        self.lyrics_cache[new_key] = fetched_lyrics
        self._build_visual_timeline(fetched_lyrics)
        return fetched_lyrics

    def _calculate_fuzzy_score(self, src_artist, src_title, src_dur, tgt_artist, tgt_title, tgt_dur):
        if not tgt_artist or not tgt_title: return 0
        dur_diff = abs(src_dur - (tgt_dur or 0))
        if src_dur > 0 and dur_diff > 20: return 0 
        def norm(s): return str(s).lower().strip()
        seq_a = difflib.SequenceMatcher(None, norm(src_artist), norm(tgt_artist))
        seq_t = difflib.SequenceMatcher(None, norm(src_title), norm(tgt_title))
        similarity = (seq_a.ratio() * 0.4) + (seq_t.ratio() * 0.6)
        return (similarity * 100) - (dur_diff * 2)

    def _parse_lrc(self, lrc_text: str) -> list[dict]:
        if not lrc_text: return []
        parsed = []
        pattern = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')
        for line in lrc_text.split('\n'):
            match = pattern.match(line)
            if match:
                minutes, seconds, text = int(match.group(1)), float(match.group(2)), match.group(3).strip()
                if not text: continue
                parsed.append({'seconds': int(minutes * 60 + seconds + 0.5), 'lyrics': text})
        
        cleaned = []
        if not parsed: return []
        current_block = parsed[0].copy()
        for i in range(1, len(parsed)):
            if parsed[i]['seconds'] == current_block['seconds']:
                current_block['lyrics'] += "\n" + parsed[i]['lyrics']
            else:
                cleaned.append(current_block)
                current_block = parsed[i].copy()
        cleaned.append(current_block)
        return cleaned

    def _basic_wrap(self, text: str, width: int) -> list[str]:
        words = text.split() 
        lines, current_line, current_len = [], [], 0
        for word in words:
            word_len = len(word)
            space = 1 if current_line else 0
            if current_len + word_len + space <= width:
                current_line.append(word)
                current_len += word_len + space
            else:
                lines.append(current_line)
                current_line = [word]
                current_len = word_len
        if current_line: lines.append(current_line)
        return [" ".join(l) for l in lines]

    def _smart_wrap(self, text: str, width: int) -> list[str]:
        lines = self._basic_wrap(text, width)
        if len(lines) <= 6: return lines
        cleaned_text = self.filler_regex.sub("", text).strip()
        if len(cleaned_text) < len(text):
            lines = self._basic_wrap(cleaned_text, width)
            if len(lines) <= 6: return lines
        lines = self._basic_wrap(text, width + 2)
        if len(lines) <= 6: return lines
        return lines[:6]

    def _build_visual_timeline(self, raw_lyrics: list[dict]):
        self.visual_timeline = []
        self.current_frame_index = -1
        if not raw_lyrics: return
        n = len(raw_lyrics)
        for i in range(n):
            current = raw_lyrics[i]
            text, start_time = current['lyrics'], current['seconds']
            next_start = raw_lyrics[i+1]['seconds'] if i + 1 < n else start_time + 60.0 
            word_count = len(text.split())
            reading_duration = max(3.0, min(2.0 + (word_count * 0.4), 8.0))
            calculated_end_time = start_time + reading_duration
            gap_to_next = next_start - calculated_end_time
            end_time = next_start if 0 < gap_to_next < 2.5 else min(calculated_end_time, next_start)
            if end_time <= start_time: end_time = start_time + 1.0

            final_width = 10 if has_bidi(text) else 11
            layout_items = []
            raw_blocks = text.split('\n')
            final_render_lines = []

            for block_idx, block in enumerate(raw_blocks):
                if len(final_render_lines) >= 6: break
                wrapped = self._smart_wrap(block, final_width)
                slots_remaining = 6 - len(final_render_lines)
                if len(wrapped) > slots_remaining:
                    if slots_remaining == 1: wrapped = [" ".join(wrapped)]
                    else: wrapped = wrapped[:slots_remaining - 1] + [" ".join(wrapped[slots_remaining - 1:])]
                if has_bidi(text): wrapped = [get_bidi(line) for line in wrapped]
                for line_idx, line in enumerate(wrapped):
                    if line.strip(): final_render_lines.append((line.strip(), line_idx == 0 and block_idx > 0))

            if len(final_render_lines) >= 6: font_height, block_gap, current_y = 10, 0, 1
            else: 
                font_height, block_gap = 12, 2
                current_y = (64 - ((len(final_render_lines) * font_height) + (sum(1 for _, is_new in final_render_lines if is_new) * block_gap))) // 2
            
            for line_text, is_new_block in final_render_lines:
                if has_bidi(text): line_text = line_text.replace("(", "###TEMP###").replace(")", "(").replace("###TEMP###", ")")
                if is_new_block: current_y += block_gap
                layout_items.append({"y": current_y, "h": font_height, "dir": 1 if has_bidi(line_text) else 0, "text": line_text})
                current_y += font_height

            self.visual_timeline.append({'start': start_time, 'end': end_time, 'layout': layout_items})

    def get_refresh_plan(self, current_pos: float) -> tuple[Optional[list], float]:
        if not self.visual_timeline: return None, None
        active_index = -1
        if self.current_frame_index != -1 and self.current_frame_index < len(self.visual_timeline):
            frame = self.visual_timeline[self.current_frame_index]
            if frame['start'] <= current_pos < frame['end']: active_index = self.current_frame_index
        if active_index == -1:
            for i, frame in enumerate(self.visual_timeline):
                if frame['start'] <= current_pos < frame['end']:
                    active_index = i
                    break
                if frame['start'] > current_pos: break
        
        if active_index != -1:
            self.current_frame_index = active_index
            frame = self.visual_timeline[active_index]
            next_event_time = frame['end']
            if active_index + 1 < len(self.visual_timeline):
                next_start = self.visual_timeline[active_index + 1]['start']
                if next_start - next_event_time < 0.2: next_event_time = next_start
            return frame['layout'], max(0.1, next_event_time - current_pos)

        self.current_frame_index = -1
        next_event_time = -1
        for frame in self.visual_timeline:
            if frame['start'] > current_pos:
                next_event_time = frame['start']
                break
        
        if next_event_time != -1: return [], max(0.1, next_event_time - current_pos)
        return [], None

# =========================================================================
# MEDIA DATA MODEL
# =========================================================================

class TitleCleaner:
    def __init__(self):
        self._patterns = [
            re.compile(r'[\(\[][^)\]]*remaster(?:ed)?[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*remix(?:ed)?[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*version[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*feat.[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*live[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'^\d+\s*[\.-]\s*', re.IGNORECASE),
            re.compile(r'\.(mp3|m4a|wav|flac)$', re.IGNORECASE)
        ]

    def clean(self, title: str) -> str: 
        if not title: return title
        for pattern in self._patterns: 
            title = pattern.sub('', title)
        return ' '.join(title.split())


class MediaData:
    def __init__(self, hass: HomeAssistant, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession):
        self.hass = hass
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.lyrics_provider = LyricsProvider(self.config, self.session)
        self.title_cleaner = TitleCleaner()
        self.ai_provider = AiArtProvider(self.config)
        self.vinyl_frames_b64: list = []
        self.cassette_frames_b64: list = []
        
        self.prev_title: str = ""
        self.prev_artist: str = ""
        self.track_changed: bool = False 
        
        self.artist: str = ""
        self.title: str = ""
        self.title_original: str = ""
        self.album: Optional[str] = None
        self.lyrics: list = []
        self.picture: Optional[str] = None
        self.lyrics_font_color: str = "#FFA000"
        self.background_color: str = "#000000"
        self.show_progress_bar: bool = False
        self.playing_tv: bool = False
        self.playing_radio: bool = False
        self.radio_logo: bool = False
        self.pic_source: Optional[str] = None
        self.pic_url: Optional[str] = None
        self.media_position: float = 0.0
        self.media_duration: float = 0.0
        self.media_position_updated_at: Optional[datetime] = None
        self.temperature: Optional[str] = None
        
        # Dedicated Isolated Slider State
        self.spotify_slide_pass: bool = False
        self.artist_slide_pass: bool = False
        self.slider_frames: int = 0
        self.slider_album_urls: list[str] = []
        self.slider_artist_pic_url: Optional[str] = None
        self.slider_error: Optional[str] = None
        self.track_number: int = 1
        self.queue_total: int = 0

    def clean_title(self, title: str) -> str: 
        return self.title_cleaner.clean(title)

    def format_ai_image_prompt(self, artist: Optional[str], title: str) -> Optional[str]:
        return self.ai_provider.format_prompt_url(artist, title)

    async def update(self) -> Optional["MediaData"]:
        try:
            media_state_obj = self.hass.states.get(self.config.media_player)
            if not media_state_obj or media_state_obj.state not in ["playing", "on"]: 
                return None

            attributes = media_state_obj.attributes
            
            raw_title = attributes.get('media_title')
            raw_artist = attributes.get('media_artist')
            app_name = attributes.get('app_name')

            if self._is_tv_playing(raw_title, raw_artist, app_name, attributes):
                self._set_tv_state()
                return self

            if not raw_title or str(raw_title).strip() == "":
                if app_name and str(app_name).strip() != "": 
                    raw_title = app_name
                else: 
                    raw_title = "Unknown Track"

            if not raw_artist or str(raw_artist).strip() == "":
                if app_name and str(app_name).strip() != "" and raw_title != app_name: 
                    raw_artist = app_name
                else: 
                    raw_artist = "Unknown Artist"

            self._set_media_state(raw_title, raw_artist, attributes)
            self._evaluate_radio_mode(raw_title, raw_artist, attributes)
            await self._fetch_lyrics()

            self.track_changed = (self.title != self.prev_title or self.artist != self.prev_artist)
            if self.track_changed:
                self.slider_album_urls = []
                self.slider_artist_pic_url = None
                self.slider_frames = 0
                self.spotify_slide_pass = False
                self.slider_error = None

            self.prev_title, self.prev_artist = self.title, self.artist
            return self
            
        except Exception as e:
            _LOGGER.error("Error updating Media Data: %s", e)
            return None

    def _is_tv_playing(self, title: str, artist: str, app_name: str, attributes: dict) -> bool:
        app_lower = str(app_name or "").lower()
        title_lower = str(title or "").lower()
        source_lower = str(attributes.get('source') or "").lower()
        channel_lower = str(attributes.get('media_channel') or "").lower()

        is_tv_detected = (
            title == "TV" or title_lower == "tv" or app_lower == "tv" or 
            source_lower == "tv" or channel_lower == "tv" or 
            "netflix" in app_lower or "youtube" in app_lower or 
            "disney" in app_lower or "live tv" in app_lower or 
            "audio return channel" in source_lower
        )

        return is_tv_detected and (
            not artist or artist == "TV" or title == "TV" or 
            "netflix" in app_lower or "youtube" in app_lower or source_lower == "tv"
        )

    def _set_tv_state(self):
        self.artist = "TV"
        self.title = "TV"
        self.title_original = "TV"
        self.playing_tv = True
        self.picture = "TV_IS_ON_ICON" if getattr(self.config, 'tv_mode', False) else "TV_IS_ON"
        self.lyrics = []
        self.show_progress_bar = False
        
        self.track_changed = (self.title != self.prev_title or self.artist != self.prev_artist)
        self.prev_title, self.prev_artist = self.title, self.artist

    def _set_media_state(self, raw_title: str, raw_artist: str, attributes: dict):
        self.playing_tv = False
        self.title_original = raw_title
        self.title = self.clean_title(raw_title) if self.config.clean_title else raw_title
        self.artist = raw_artist if raw_artist else ""
        self.album = attributes.get('album_name') or attributes.get('media_album_name') or ""
        
        original_picture = attributes.get('entity_picture')
        if original_picture and (re.match(r'^[a-zA-Z]:\\', original_picture) or original_picture.startswith("file://")): 
            original_picture = None
        self.picture = original_picture
        
        try:
            self.media_position = float(attributes.get('media_position', 0))
            self.media_duration = float(attributes.get('media_duration', 0))
        except (ValueError, TypeError): 
            pass

        self.show_progress_bar = self.config.progress_bar_enabled and self.media_duration > 0

        pos_updated_at_str = attributes.get('media_position_updated_at')
        if isinstance(pos_updated_at_str, datetime): 
            self.media_position_updated_at = pos_updated_at_str
        elif pos_updated_at_str: 
            self.media_position_updated_at = datetime.fromisoformat(pos_updated_at_str.replace('Z', '+00:00'))
        else: 
            self.media_position_updated_at = None

        raw_track = attributes.get('media_track')
        if raw_track is not None:
            try:
                self.track_number = int(raw_track)
            except (ValueError, TypeError):
                self.track_number = 1
        else:
            self.track_number = 1

    def _evaluate_radio_mode(self, raw_title: str, raw_artist: str, attributes: dict):
        media_content_id = attributes.get('media_content_id')
        media_channel = attributes.get('media_channel')
        
        if media_channel and media_content_id and (
            media_content_id.startswith("x-rincon") or 
            media_content_id.startswith("aac://http") or 
            media_content_id.startswith("rtsp://")
        ): 
            self.playing_radio = True
            self.radio_logo = (
                'https://tunein' in str(media_content_id) or 
                raw_title == media_channel or 
                raw_title == raw_artist or 
                raw_artist == media_channel or 
                raw_artist == 'Live' or 
                raw_artist is None
            )
        else:
            self.playing_radio = False
            self.radio_logo = False

    async def _fetch_lyrics(self):
        if getattr(self.config, 'show_lyrics', False) and not getattr(self.config, 'special_mode', False) and not self.playing_tv and not self.playing_radio:
            self.lyrics = await self.lyrics_provider.get_lyrics(self.artist, self.title_original, self.album, int(self.media_duration))
        else:
            self.lyrics = []

# =========================================================================
# NOTIFICATION ICON RENDERER
# =========================================================================

class NotificationIconRenderer:
    @staticmethod
    def draw_v(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.line([(cx-8, cy), (cx-2, cy+8), (cx+10, cy-8)], fill=color, width=3)

    @staticmethod
    def draw_x(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        s = 7
        draw.line([(cx-s, cy-s), (cx+s, cy+s)], fill=color, width=3)
        draw.line([(cx+s, cy-s), (cx-s, cy+s)], fill=color, width=3)

    @staticmethod
    def draw_info(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.ellipse([cx-9, cy-9, cx+9, cy+9], outline=color, width=1)
        draw.rectangle([cx-1, cy-2, cx+1, cy+5], fill=color) 
        draw.rectangle([cx-1, cy-5, cx+1, cy-4], fill=color)

    @staticmethod
    def draw_success(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.line([(cx-6, cy), (cx-2, cy+6), (cx+7, cy-5)], fill=color, width=2)

    @staticmethod
    def draw_alert(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.arc([cx-6, cy-5, cx+6, cy+5], 180, 0, fill=color, width=1)
        draw.line([(cx-6, cy), (cx-8, cy+6)], fill=color, width=1)
        draw.line([(cx+6, cy), (cx+8, cy+6)], fill=color, width=1)
        draw.line([(cx-8, cy+6), (cx+8, cy+6)], fill=color, width=1)
        clapper_x = cx + (2 if frame_num == 1 else 0)
        draw.line([(clapper_x-1, cy+6), (clapper_x+1, cy+6)], fill=color, width=1)
        draw.point((clapper_x, cy+8), fill=color)

    @staticmethod
    def draw_warning(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.polygon([(cx, cy-9), (cx-10, cy+8), (cx+10, cy+8)], outline=color, fill=None)
        draw.line([(cx, cy-3), (cx, cy+3)], fill=color, width=1)
        draw.point((cx, cy+5), fill=color)

    @staticmethod
    def draw_error(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        s = 5
        draw.line([(cx-s, cy-s), (cx+s, cy+s)], fill=color, width=2)
        draw.line([(cx+s, cy-s), (cx-s, cy+s)], fill=color, width=2)

    @staticmethod
    def draw_weather(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.ellipse([cx+2, cy-8, cx+8, cy-2], outline=(255, 215, 0), width=1)
        draw.arc([cx-8, cy-2, cx+2, cy+6], 90, 270, fill=color, width=1)
        draw.arc([cx-2, cy-4, cx+8, cy+6], 180, 0, fill=color, width=1)
        draw.line([(cx-8, cy+2), (cx+8, cy+2)], fill=color, width=1)

    @staticmethod
    def draw_attack(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.line([(cx, cy-9), (cx-3, cy-4)], fill=color, width=1)
        draw.line([(cx, cy-9), (cx+3, cy-4)], fill=color, width=1)
        draw.rectangle([cx-3, cy-4, cx+3, cy+4], outline=color, width=1)
        draw.line([(cx-3, cy+4), (cx-6, cy+8)], fill=color, width=1)
        draw.line([(cx+3, cy+4), (cx+6, cy+8)], fill=color, width=1)
        fire_color = (255, 165, 0) if frame_num == 0 else (255, 255, 0)
        draw.line([(cx-1, cy+4), (cx-1, cy+7)], fill=fire_color, width=1)
        draw.line([(cx+1, cy+4), (cx+1, cy+7)], fill=fire_color, width=1)

    @staticmethod
    def draw_wifi(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.point((cx, cy+6), fill=color)
        if frame_num >= 1: draw.arc([cx-4, cy, cx+4, cy+8], 225, 315, fill=color, width=1)
        if frame_num >= 2: draw.arc([cx-8, cy-4, cx+8, cy+4], 225, 315, fill=color, width=1)

    @staticmethod
    def draw_time(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.ellipse([cx-9, cy-9, cx+9, cy+9], outline=color, width=1)
        angle = frame_num * 90
        rad = math.radians(angle - 90)
        draw.line([(cx, cy), (cx + 6 * math.cos(rad), cy + 6 * math.sin(rad))], fill=color, width=1)

    @staticmethod
    def draw_boiler(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-5, cy-8, cx+5, cy+8], outline=color, width=1)
        draw.line([(cx+1, cy-4), (cx-2, cy), (cx+2, cy), (cx-1, cy+5)], fill=color, width=1)
        draw.point((cx, cy+6), fill=color)

    @staticmethod
    def draw_shutter(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-8, cy-8, cx+8, cy+8], outline=color, width=1)
        for y_line in range(cy-5, cy+7, 3):
            draw.line([(cx-6, y_line), (cx+6, y_line)], fill=color, width=1)

    @staticmethod
    def draw_car(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-9, cy, cx+9, cy+6], outline=color, width=1)
        draw.line([(cx-9, cy), (cx-5, cy-5), (cx+5, cy-5), (cx+9, cy)], fill=color, width=1)
        draw.ellipse([cx-7, cy+5, cx-4, cy+8], fill=color)
        draw.ellipse([cx+4, cy+5, cx+7, cy+8], fill=color)

    @staticmethod
    def draw_washer(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-8, cy-8, cx+8, cy+8], outline=color, width=1)
        draw.ellipse([cx-5, cy-5, cx+5, cy+5], outline=color, width=1)
        draw.point((cx+6, cy-6), fill=color) 

    @staticmethod
    def draw_trash(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.line([(cx-5, cy+8), (cx+5, cy+8), (cx+7, cy-4), (cx-7, cy-4), (cx-5, cy+8)], fill=color, width=1)
        draw.line([(cx-8, cy-4), (cx+8, cy-4)], fill=color, width=1)
        draw.rectangle([cx-2, cy-6, cx+2, cy-4], fill=color)

    @staticmethod
    def draw_door(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-6, cy-9, cx+6, cy+9], outline=color, width=1)
        draw.line([(cx-6, cy-9), (cx+2, cy-6)], fill=color, width=1)
        draw.line([(cx+2, cy-6), (cx+2, cy+9)], fill=color, width=1)
        draw.line([(cx+2, cy+9), (cx-6, cy+9)], fill=color, width=1)

    @staticmethod
    def draw_lock(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-6, cy-2, cx+6, cy+7], fill=color)
        draw.arc([cx-5, cy-8, cx+5, cy-1], 180, 0, fill=color, width=1)

    @staticmethod
    def draw_mail(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-9, cy-6, cx+9, cy+6], outline=color, width=1)
        draw.line([(cx-9, cy-6), (cx, cy+2), (cx+9, cy-6)], fill=color, width=1)

    @staticmethod
    def draw_battery(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-8, cy-4, cx+6, cy+4], outline=color, width=1)
        draw.rectangle([cx-7, cy-3, cx-2, cy+3], fill=color) 
        draw.rectangle([cx+6, cy-2, cx+8, cy+2], fill=color) 

    @staticmethod
    def draw_fire(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.polygon([(cx, cy-8), (cx+5, cy+2), (cx+3, cy+8), (cx-3, cy+8), (cx-5, cy+2)], outline=color, fill=None)
        draw.point((cx, cy+5), fill=color)

    @staticmethod
    def draw_water(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.polygon([(cx, cy-8), (cx+5, cy+2), (cx, cy+8), (cx-5, cy+2)], outline=color, fill=color)

    @staticmethod
    def draw_sleep(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.arc([cx-6, cy-6, cx+6, cy+6], 90, 270, fill=color, width=2)
        draw.line([(cx, cy-6), (cx, cy+6)], fill=color, width=1)

    @staticmethod
    def draw_phone(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.arc([cx-8, cy-4, cx+8, cy+12], 0, 180, fill=color, width=2)
        draw.rectangle([cx-9, cy-4, cx-6, cy], fill=color)
        draw.rectangle([cx+6, cy-4, cx+9, cy], fill=color)

    @staticmethod
    def draw_calendar(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-8, cy-7, cx+8, cy+8], outline=color, width=1)
        draw.line([(cx-8, cy-3), (cx+8, cy-3)], fill=color, width=1)
        draw.point((cx-4, cy+1), fill=color)
        draw.point((cx, cy+1), fill=color)
        draw.point((cx+4, cy+1), fill=color)
        draw.point((cx-4, cy+5), fill=color)
        draw.point((cx, cy+5), fill=color)

    @staticmethod
    def draw_camera(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.rectangle([cx-8, cy-5, cx+8, cy+6], outline=color, width=1)
        draw.rectangle([cx-2, cy-8, cx+2, cy-5], fill=color)
        draw.ellipse([cx-3, cy-2, cx+3, cy+4], outline=color, width=1)

    @staticmethod
    def draw_music(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.ellipse([cx-7, cy+3, cx-3, cy+7], fill=color)
        draw.ellipse([cx+3, cy+3, cx+7, cy+7], fill=color)
        draw.line([(cx-3, cy+5), (cx-3, cy-6)], fill=color, width=1)
        draw.line([(cx+7, cy+5), (cx+7, cy-6)], fill=color, width=1)
        draw.line([(cx-3, cy-6), (cx+7, cy-6)], fill=color, width=2)

    @staticmethod
    def draw_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=color)
        s = 7
        draw.line([(cx, cy-s), (cx, cy-s-2)], fill=color, width=1)
        draw.line([(cx, cy+s), (cx, cy+s+2)], fill=color, width=1)
        draw.line([(cx-s, cy), (cx-s-2, cy)], fill=color, width=1)
        draw.line([(cx+s, cy), (cx+s+2, cy)], fill=color, width=1)
        draw.point((cx-5, cy-5), fill=color)
        draw.point((cx+5, cy-5), fill=color)
        draw.point((cx-5, cy+5), fill=color)
        draw.point((cx+5, cy+5), fill=color)

    @staticmethod
    def draw_moon(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        draw.arc([cx-6, cy-6, cx+6, cy+6], 90, 270, fill=color, width=2)
        draw.line([(cx, cy-6), (cx, cy+6)], fill=color, width=1)

    _REGISTRY: Dict[str, Callable] = {
        "v": draw_v, "x": draw_x, "info": draw_info, "success": draw_success,
        "warning": draw_warning, "alert": draw_alert, "error": draw_error,
        "weather": draw_weather, "attack": draw_attack, "wifi": draw_wifi,
        "timer": draw_time, "time": draw_time, "boiler": draw_boiler,
        "shutter": draw_shutter, "car": draw_car, "washer": draw_washer,
        "trash": draw_trash, "door": draw_door, "lock": draw_lock,
        "mail": draw_mail, "battery": draw_battery, "fire": draw_fire,
        "water": draw_water, "sleep": draw_sleep, "phone": draw_phone,
        "calendar": draw_calendar, "camera": draw_camera, "music": draw_music,
        "sun": draw_sun, "moon": draw_moon
    }

    @classmethod
    def render_icon(cls, n_type: str, draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int = 0) -> None:
        fn = cls._REGISTRY.get(n_type)
        if fn:
            fn(draw, cx, cy, color, frame_num)

# =========================================================================
# NOTIFICATION MANAGER
# =========================================================================

class NotificationManager:
    THEMES = {
        "info":    {"color": (0, 191, 255), "hex": "#00BFFF"},   
        "success": {"color": (50, 205, 50), "hex": "#32CD32"},   
        "warning": {"color": (255, 165, 0), "hex": "#FFA500"},   
        "error":   {"color": (255, 69, 0),  "hex": "#FF4500"},   
        "text":    {"color": (255, 255, 255), "hex": "#FFFFFF"}, 
        
        "v":       {"color": (50, 205, 50), "hex": "#32CD32"},   
        "x":       {"color": (255, 0, 0),   "hex": "#FF0000"},   
        "alert":   {"color": (255, 69, 0),  "hex": "#FF4500"},   
        "weather": {"color": (135, 206, 235), "hex": "#87CEEB"}, 
        "attack":  {"color": (255, 0, 0),   "hex": "#FF0000"},   
        
        "boiler":  {"color": (255, 69, 0),  "hex": "#FF4500"},   
        "shutter": {"color": (192, 192, 192), "hex": "#C0C0C0"}, 
        "car":     {"color": (0, 255, 255), "hex": "#00FFFF"},   
        "washer":  {"color": (0, 191, 255), "hex": "#00BFFF"},   
        "trash":   {"color": (50, 205, 50), "hex": "#32CD32"},   
        "door":    {"color": (255, 215, 0), "hex": "#FFD700"},   
        "lock":    {"color": (255, 0, 0),   "hex": "#FF0000"},   
        "mail":    {"color": (255, 255, 224), "hex": "#FFFFE0"}, 
        "fire":    {"color": (255, 140, 0), "hex": "#FF8C00"},   
        "water":   {"color": (30, 144, 255), "hex": "#1E90FF"},  
        "battery": {"color": (220, 20, 60), "hex": "#DC143C"},   
        "wifi":    {"color": (255, 0, 0),   "hex": "#FF0000"},   
        
        "timer":   {"color": (255, 255, 255), "hex": "#FFFFFF"}, 
        "time":    {"color": (255, 255, 255), "hex": "#FFFFFF"}, 
        "phone":   {"color": (0, 255, 0),     "hex": "#00FF00"}, 
        "calendar":{"color": (255, 255, 0),   "hex": "#FFFF00"}, 
        "camera":  {"color": (192, 192, 192), "hex": "#C0C0C0"}, 
        "music":   {"color": (255, 105, 180), "hex": "#FF69B4"}, 
        "sun":     {"color": (255, 215, 0),   "hex": "#FFD700"}, 
        "moon":    {"color": (147, 112, 219), "hex": "#9370DB"}, 
        "sleep":   {"color": (147, 112, 219), "hex": "#9370DB"}, 
    }

    ANIMATIONS = {
        "alert":   (2, 200),  
        "phone":   (2, 200),  
        "attack":  (2, 500),  
        "error":   (2, 500),  
        "warning": (2, 500),  
        "weather": (2, 800),  
        "wifi":    (3, 300),  
        "timer":   (4, 150),  
        "time":    (4, 150),
        "music":   (2, 400),  
    }

    LAYOUTS = {
        1: {"icon_cy": 25, "text_start_y": 48}, 
        2: {"icon_cy": 20, "text_start_y": 40}, 
        3: {"icon_cy": 15, "text_start_y": 30}, 
        4: {"icon_cy": 11, "text_start_y": 22}  
    }

    def __init__(self, config: "Config", pixoo: "PixooDevice", image_processor: "ImageProcessor", hass: HomeAssistant):
        self.config = config
        self.pixoo = pixoo
        self.proc = image_processor
        self.hass = hass
        self.is_active = False

    async def display(self, event_data: dict):
        try:
            self.is_active = True
            
            message = event_data.get("message", "")
            notif_type = str(event_data.get("type", "text")).lower()
            duration = int(event_data.get("duration", 5))
            custom_color = event_data.get("color", None)

            if not message:
                return

            await self._trigger_buzzer(event_data)

            max_lines = 6 if notif_type == "text" else 4
            wrap_limit = 11 if has_bidi(message) else 12

            raw_lines = textwrap.wrap(message, width=wrap_limit)
            lines = [get_bidi(line) if has_bidi(line) else line for line in raw_lines]

            if len(lines) > max_lines: 
                lines = lines[:max_lines]
            if not lines: 
                lines = [""]
            
            line_count = len(lines)
            
            if notif_type == "text":
                total_text_height = line_count * 10
                text_start_y = (64 - total_text_height) // 2
                icon_cy = 0 
            else:
                layout = self.LAYOUTS.get(line_count, self.LAYOUTS[2])
                icon_cy = layout["icon_cy"]
                text_start_y = layout["text_start_y"]

            theme = self.THEMES.get(notif_type, self.THEMES["info"])
            hex_color = custom_color if custom_color else theme["hex"]
            rgb_color = self._hex_to_rgb(hex_color) if notif_type == "text" else theme["color"]

            anim_config = self.ANIMATIONS.get(notif_type, (1, 1000))
            total_frames = anim_config[0]
            anim_speed = anim_config[1]
            
            generated_frames_b64 = []
            for i in range(total_frames):
                bg_image = self._draw_background(notif_type, rgb_color, icon_cy, i)
                generated_frames_b64.append(self.proc.gbase64(bg_image))

            await self.pixoo.send_command({
                "Command": "Draw/CommandList",
                "CommandList": [
                    {"Command": "Channel/SetIndex", "SelectIndex": 4},
                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                    {"Command": "Draw/ClearHttpText"},
                    {"Command": "Draw/ResetHttpGifId"},
                ]
            })

            for i, b64_frame in enumerate(generated_frames_b64):
                await self.pixoo.send_command({
                    "Command": "Draw/SendHttpGif",
                    "PicNum": total_frames,
                    "PicWidth": 64,
                    "PicOffset": i,
                    "PicID": 0,
                    "PicSpeed": anim_speed,
                    "PicData": b64_frame
                })
                if total_frames > 1:
                    await asyncio.sleep(0.15)

            if total_frames > 1:
                await asyncio.sleep(0.75)
            else:
                await asyncio.sleep(0.1)

            text_items = self._create_text_items(lines, hex_color, text_start_y)
            if text_items:
                await self.pixoo.send_command({
                    "Command": "Draw/SendHttpItemList",
                    "ItemList": text_items
                })

            await asyncio.sleep(duration)

        except Exception as e:
            _LOGGER.error("Notification display error: %s", e)
        finally:
            self.is_active = False

    async def _trigger_buzzer(self, data: dict):
        if not data.get("play_buzzer", False):
            return

        active_time = int(data.get("buzzer_active", 500))
        off_time = int(data.get("buzzer_off", 500))
        total_time = int(data.get("buzzer_total", 3000))

        try:
            await self.pixoo.send_command({
                "Command": "Device/PlayBuzzer",
                "ActiveTimeInCycle": active_time,
                "OffTimeInCycle": off_time,
                "PlayTotalTime": total_time
            })
        except Exception as e:
            _LOGGER.warning("Failed to play buzzer: %s", e)

    @lru_cache(maxsize=64)
    def _draw_background(self, n_type: str, color: tuple, cy: int, frame_num: int = 0) -> Image.Image:
        img = Image.new("RGB", (64, 64), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle([0, 0, 63, 63], outline=color, width=1)
        if n_type == "text": 
            return img

        cx = 32
        shift_x, shift_y = 0, 0
        
        if n_type in ["alert", "phone"] and frame_num == 1:
            shift_x = -1 if n_type == "alert" else 1
        
        active_color = color
        if n_type == "attack" and frame_num == 1:
            active_color = (255, 255, 0)
        elif n_type in ["error", "warning"] and frame_num == 1:
            active_color = tuple(c // 2 for c in color)

        if n_type in ["weather", "music"] and frame_num == 1:
            shift_y = -1

        cx += shift_x
        cy += shift_y

        NotificationIconRenderer.render_icon(n_type, draw, cx, cy, active_color, frame_num)
        return img

    def _create_text_items(self, lines: list, color: str, start_y: int) -> list:
        items = []
        line_ids = set(25 + i for i in range(len(lines)))
        all_possible_ids = [1, 2, 3, 4, 5, 6, 10, 11, 20, 21, 22, 25, 26, 27, 28, 29, 30]
        
        for tid in all_possible_ids:
            if tid not in line_ids:
                items.append({
                    "TextId": tid, "type": 22, "x": 0, "y": 0, "dir": 0, "font": 190,
                    "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 1,
                    "TextString": "", "color": "#000000"
                })

        line_height = 10 
        for i, line in enumerate(lines):
            rtl = 1 if has_bidi(line) else 0
            items.append({
                "TextId": 25 + i, "type": 22, "x": 0, "y": start_y + (i * line_height),
                "dir": rtl, "font": 190, "TextWidth": 64, "Textheight": 16,
                "speed": 100, "align": 2, "TextString": line, "color": color
            })
        return items

    def _hex_to_rgb(self, hex_str: str) -> tuple:
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 3: hex_str = ''.join([c*2 for c in hex_str])
        try:
            return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
        except ValueError:
            return (255, 255, 255)

# =========================================================================
# PROGRESS BAR MANAGER
# =========================================================================

class ProgressBarManager:
    def __init__(self, config: "Config", hass: HomeAssistant):
        self.config = config
        self.hass = hass
        self.current_bar_str = ""

    def calculate(self, position: float, duration: float) -> tuple[str, float]:
        if duration <= 0: return "", None
        max_chars = self.config.progress_bar_resolution
        ratio = min(position / duration, 1.0)
        chars_needed = max(int(ratio * max_chars), 1)
        self.current_bar_str = self.config.progress_bar_character * chars_needed
        
        next_char_index = chars_needed + 1
        delay = None
        if next_char_index <= max_chars:
            target_time = (next_char_index / max_chars) * duration
            delay = max(target_time - position, 0.2)
        return self.current_bar_str, delay

    async def get_payload_item(self, media_data: "MediaData") -> list:
        if not self.config.progress_bar_enabled or not getattr(media_data, 'show_progress_bar', False) or not self.current_bar_str: return []
        color = getattr(media_data, 'lyrics_font_color', "#FFFFFF") if self.config.progress_bar_color == 'match' else self.config.progress_bar_color
        
        return [
            {"TextId": 20, "type": 22, "x": 0, "y": self.config.progress_bar_y_offset-7, "dir": 0, "font": self.config.progress_bar_font, "TextWidth": 64, "Textheight": 10, "speed": 100, "align": 1, "TextString": self.current_bar_str, "color": color},
            {"TextId": 21, "type": 22, "x": 1, "y": self.config.progress_bar_y_offset-7, "dir": 0, "font": self.config.progress_bar_font, "TextWidth": 64, "Textheight": 10, "speed": 100, "align": 1, "TextString": self.current_bar_str, "color": color}
        ]

class AnalogClockRenderer:
    """Renderer for classical analog clock on 64x64 pixel display with dimmed album art."""

    CENTER = (31.5, 31.5)
    RADIUS = 28.0

    # Colors
    COLOR_BEZEL = (90, 95, 105)
    COLOR_MAJOR_TICK = (255, 240, 200)
    COLOR_MINOR_TICK = (160, 165, 175)
    COLOR_OUTLINE = (0, 0, 0)
    COLOR_HOUR_HAND = (255, 255, 255)   
    COLOR_MINUTE_HAND = (255, 205, 50)
    COLOR_PIN = (230, 230, 235)

    @classmethod
    def render(cls, album_art: Image.Image, now: datetime | None = None) -> Image.Image:
        """Draw an analog clock frame over album art."""
        if now is None:
            now = datetime.now()

        base = Image.new("RGB", (64, 64), (0, 0, 0))

        art_64 = album_art.convert("RGBA").resize((64, 64), Image.Resampling.BILINEAR)
        dim_layer = Image.new("RGBA", (64, 64), (0, 0, 0, 135)) 
        dimmed_art = Image.alpha_composite(art_64, dim_layer)

        circle_mask = Image.new("L", (64, 64), 0)
        mask_draw = ImageDraw.Draw(circle_mask)
        cx, cy = cls.CENTER
        r = cls.RADIUS
        mask_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)

        base.paste(dimmed_art.convert("RGB"), (0, 0), circle_mask)

        draw = ImageDraw.Draw(base)

        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=cls.COLOR_BEZEL, width=1)

        cls._draw_ticks(draw, cx, cy, r)

        minute = now.minute
        hour = now.hour % 12
        second = now.second

        min_angle = (minute + second / 60.0) * 6.0
        hour_angle = (hour + minute / 60.0) * 30.0

        cls._draw_hand(
            draw, cx, cy, hour_angle, length=13.0, width=2,
            color=cls.COLOR_HOUR_HAND, outline_color=cls.COLOR_OUTLINE
        )

        cls._draw_hand(
            draw, cx, cy, min_angle, length=22.0, width=1,
            color=cls.COLOR_MINUTE_HAND, outline_color=cls.COLOR_OUTLINE
        )

        draw.ellipse([cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5], fill=cls.COLOR_PIN)
        draw.point((int(cx), int(cy)), fill=cls.COLOR_OUTLINE)

        return base

    @classmethod
    def _draw_ticks(cls, draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
        """Draw classical hour markers."""
        for h in range(12):
            angle_rad = math.radians(h * 30.0 - 90.0)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            if h % 3 == 0:
                r_in = r - 3.5
                r_out = r - 1.0
                x1 = cx + r_in * cos_a
                y1 = cy + r_in * sin_a
                x2 = cx + r_out * cos_a
                y2 = cy + r_out * sin_a
                draw.line([(x1, y1), (x2, y2)], fill=cls.COLOR_MAJOR_TICK, width=1)
            else:
                r_dot = r - 2.0
                x = int(round(cx + r_dot * cos_a))
                y = int(round(cy + r_dot * sin_a))
                draw.point((x, y), fill=cls.COLOR_MINOR_TICK)

    @classmethod
    def _draw_hand(
        cls,
        draw: ImageDraw.ImageDraw,
        cx: float,
        cy: float,
        angle_deg: float,
        length: float,
        width: int,
        color: tuple[int, int, int],
        outline_color: tuple[int, int, int],
    ) -> None:
        """Draw clock hand with shadow/outline for high visibility."""
        angle_rad = math.radians(angle_deg - 90.0)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        tip_x = cx + length * cos_a
        tip_y = cy + length * sin_a

        draw.line([(cx, cy), (tip_x, tip_y)], fill=outline_color, width=width + 2)
        draw.line([(cx, cy), (tip_x, tip_y)], fill=color, width=width)