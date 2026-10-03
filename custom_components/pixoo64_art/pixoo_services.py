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
from typing import Any, Dict, Optional, Tuple
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageStat, ImageChops, ImageOps, UnidentifiedImageError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url

try:
    from bidi.algorithm import get_display
    bidi_support = True
except ImportError:
    bidi_support = False

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
        self.tidal_client_id = get_val("tidal_client_id", "")
        self.tidal_client_secret = get_val("tidal_client_secret", "")
        self.lastfm = get_val("lastfm_key", "")
        self.discogs = get_val("discogs_token", "")
        self.wled_ip = get_val("wled_ip", "")
        self.light_entity = get_val("light_entity", [])
        self.only_at_night = get_val("only_at_night", True)
        self.tv_mode = get_val("tv_mode", False)
        
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
        self.images_cache = 25
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
        self.default_font = ImageFont.load_default()

class PixooDevice:
    def __init__(self, config: "Config", session: aiohttp.ClientSession): 
        self.config = config
        self.session = session
        self.select_index: Optional[int] = None 
        self.headers = {"Content-Type": "application/json", "Accept": "*/*", "Connection": "keep-alive", "User-Agent": "PixooClient/1.0"}
        self._last_payload_str: Optional[str] = None
        self._last_send_time: float = 0.0

    async def send_command(self, payload_command: dict, retries: int = 3) -> bool: 
        if self.session.closed or not self.config.pixoo_url: return False
        try:
            current_payload_str = json.dumps(payload_command, sort_keys=True)
            now = time.monotonic()
            if (current_payload_str == self._last_payload_str) and (now - self._last_send_time < 1.0): return True
            self._last_payload_str = current_payload_str
            self._last_send_time = now
        except Exception: pass 

        for attempt in range(1, retries + 1):
            try:
                async with self.session.post(self.config.pixoo_url, headers=self.headers, json=payload_command, timeout=5) as response:
                    if response.status == 200:
                        await asyncio.sleep(0.1)
                        return True
            except Exception:
                if attempt < retries: await asyncio.sleep(0.2 * attempt)
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

class ImageProcessor:
    def __init__(self, hass: HomeAssistant, config: "Config", session: aiohttp.ClientSession):
        self.hass = hass
        self.config = config
        self.session = session
        self.image_cache: OrderedDict[str, dict] = OrderedDict()
        self.raw_image_cache: OrderedDict[str, bytes] = OrderedDict()
        self._prefetch_tasks: dict = {}
        self.cache_size: int = config.images_cache

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
        cache_key = f"{picture}_{media_data.artist}_{media_data.title}" if getattr(self.config, 'burned', False) else picture
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
                    if len(self.image_cache) >= self.cache_size: self.image_cache.popitem(last=False)
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
                if not img: return None
                
                max_dimension = 320
                if max(img.size) > max_dimension:
                    scale_factor = max_dimension / max(img.size)
                    img = img.resize((int(img.width * scale_factor), int(img.height * scale_factor)), Image.Resampling.BILINEAR)

                if (getattr(self.config, 'crop_borders', False) or getattr(self.config, 'special_mode', False)) and not media_data.radio_logo:
                    img = self.crop_image_borders(img, media_data.radio_logo)

                img = self.fixed_size(img)
                
                if getattr(self.config, 'burned', False) and not media_data.radio_logo:
                    img = img.resize((64, 64), Image.Resampling.BILINEAR)
                    img = self._draw_burned_text(img, media_data.artist, media_data.title)
                
                if getattr(self.config, 'special_mode', False):
                    img = self.special_mode(img)

                img = img.resize((64, 64), Image.Resampling.BILINEAR)

                vals = self.img_values(img)
                return {
                    'pil_image': img, 
                    'font_color': vals['font_color'], 
                    'brightness_lower_part': vals['brightness_lower_part'], 
                    'background_color_rgb': vals['background_color_rgb'],
                    'background_color': vals['background_color']
                }
        except Exception:
            return None

    def img_values(self, img: Image.Image) -> dict:
        analysis_img = img.resize((50, 50), Image.Resampling.NEAREST)
        palette = self.get_image_palette(analysis_img) 
        
        if getattr(self.config, 'text_bg', False):
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
        font_color = self.get_optimal_font_color(analysis_img)

        return {
            'font_color': font_color, 
            'brightness_lower_part': brightness_lower_part, 
            'background_color_rgb': most_common_color_alternative_rgb,
            'background_color': hex_color
        }

    def get_image_palette(self, img: Image.Image) -> list:
        quantized = img.quantize(colors=16, method=2)
        palette = quantized.getpalette()
        candidates = []
        if palette:
            raw_colors = [tuple(palette[i:i+3]) for i in range(0, len(palette)//3 * 3, 3)]
            for rgb in raw_colors:
                r, g, b = rgb
                h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
                if s > 0.2 and v > 0.15: candidates.append(rgb)
        if len(candidates) < 3: candidates.extend([(0, 255, 255), (255, 0, 255), (50, 255, 50), (255, 255, 0), (255, 140, 0)])
        return candidates

    def get_optimal_font_color(self, img: Image.Image) -> str:
        if getattr(self.config, 'force_font_color', None): return self.config.force_font_color
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

        if getattr(self.config, 'text_bg', False):
            if chosen_dominant_color:
                r, g, b = chosen_dominant_color
                h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                nr, ng, nb = colorsys.hsv_to_rgb(h, max(0.4, min(s, 1.0)), 1.0)
                return f'#{int(nr*255):02x}{int(ng*255):02x}{int(nb*255):02x}'
            return "#00ffff"
        else:
            return "#ffffff"

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

    def crop_image_borders(self, img: Image.Image, radio_logo: bool) -> Image.Image:
        """Main entry for border cropping: handles standard, extra, and special mode."""
        if radio_logo or not getattr(self.config, 'crop_borders', False):
            return img

        if getattr(self.config, 'crop_extra', False) or getattr(self.config, 'special_mode', False): 
            return self._perform_extra_subject_crop(img)

        return self._perform_standard_crop(img)

    def _perform_standard_crop(self, img: Image.Image) -> Image.Image:
        """
        STANDARD CROP:
        Trims outer blank margins, letterbox/pillarbox bars, but PRESERVES the full
        album artwork design including typography, titles, and artist names.
        """
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

        # If content already fills 98% of both axes, no crop needed
        if w >= orig_w * 0.98 and h >= orig_h * 0.98:
            return img

        is_pillarbox = (min_y <= int(orig_h * 0.02) and max_y >= int(orig_h * 0.98)) and (min_x > int(orig_w * 0.02) or max_x < int(orig_w * 0.98))
        is_letterbox = (min_x <= int(orig_w * 0.02) and max_x >= int(orig_w * 0.98)) and (min_y > int(orig_h * 0.02) or max_y < int(orig_h * 0.98))

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

    def _refine_box_to_photo_edges(self, img: Image.Image, rough_box: Tuple[int, int, int, int], bg_color: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
        """
        Snaps the rough proxy coordinates to the exact pixel edges of the inner photo
        on the full-resolution image.
        """
        orig_w, orig_h = img.size
        rx1, ry1, rx2, ry2 = rough_box
        pixels = img.load()
        br, bg, bb = bg_color

        cx = (rx1 + rx2) // 2
        cy = (ry1 + ry2) // 2

        x_start = int(rx1 + (rx2 - rx1) * 0.25)
        x_end = int(rx2 - (rx2 - rx1) * 0.25)
        x_len = max(1, x_end - x_start)

        # 1. Exact Top Edge
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

        # 2. Exact Bottom Edge
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

        # 3. Exact Left Edge
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

        # 4. Exact Right Edge
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

    def _score_component(self, comp: dict, proxy: Image.Image, pw: int, ph: int) -> float:
        """Scores a component to identify the real photographic artwork over text, lines, or containers."""
        w, h, area = comp['w'], comp['h'], comp['area']
        if w <= 0 or h <= 0 or area <= 0:
            return 0.0

        solidity = area / float(w * h)
        aspect = min(w, h) / float(max(w, h))

        # Measure color variance (stddev) of the component's pixels
        pixels = proxy.load()
        r_vals, g_vals, b_vals = [], [], []
        for cx, cy in comp['pixels']:
            r, g, b = pixels[cx, cy]
            r_vals.append(r)
            g_vals.append(g)
            b_vals.append(b)

        n = len(r_vals)
        if n > 1:
            mean_r = sum(r_vals) / n
            mean_g = sum(g_vals) / n
            mean_b = sum(b_vals) / n
            var_rgb = (
                sum((x - mean_r) ** 2 for x in r_vals) +
                sum((x - mean_g) ** 2 for x in g_vals) +
                sum((x - mean_b) ** 2 for x in b_vals)
            ) / (3.0 * n)
            std_dev = math.sqrt(var_rgb)
        else:
            std_dev = 0.0

        center_x = (comp['min_x'] + comp['max_x']) / 2.0
        center_y = (comp['min_y'] + comp['max_y']) / 2.0
        dist_from_center = math.hypot(center_x - (pw / 2.0), center_y - (ph / 2.0)) / (pw / 2.0)

        # Real photos/album artwork have high solidity, balanced aspect ratio, rich color variance, and are centered
        variance_bonus = 1.0 + min(std_dev, 50.0) / 20.0
        score = area * (solidity ** 1.5) * (aspect ** 1.0) * variance_bonus / (1.0 + dist_from_center * 0.6)
        return score

    def _inspect_and_unwrap_container(self, comp: dict, proxy: Image.Image, pw: int, ph: int) -> Optional[Tuple[Tuple[int, int, int], list]]:
        """
        Detects if a component is a spanning container stripe/banner (like Sweet Dreams)
        and extracts the inner objects. Small centered photos (like Pet Shop Boys) are skipped.
        """
        is_spanning_stripe = (comp['h'] > ph * 0.70 and comp['w'] < pw * 0.40) or (comp['w'] > pw * 0.70 and comp['h'] < ph * 0.40)
        is_large_box = comp['area'] > int((pw * ph) * 0.15)
        
        if not (is_spanning_stripe or is_large_box):
            return None

        pixels = proxy.load()
        comp_pixels = comp['pixels']

        buckets = Counter((pixels[x, y][0] // 16, pixels[x, y][1] // 16, pixels[x, y][2] // 16) for x, y in comp_pixels)
        top_bucket, top_count = buckets.most_common(1)[0]
        dominance = top_count / float(len(comp_pixels))

        if dominance < 0.45:
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

    def _find_subject_box(self, comps: list, pw: int, ph: int) -> Tuple[int, int, int, int]:
        """
        Finds the primary subject and merges immediately adjacent companion parts
        (e.g., two people side-by-side) while excluding distant text or decorative lines.
        """
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
            # Ignore tiny specks/text (area < 15% of primary)
            if other['area'] < primary['area'] * 0.15:
                continue

            # Distance between component bounding boxes
            dx = max(0, max(cur_min_x - other['max_x'], other['min_x'] - cur_max_x))
            dy = max(0, max(cur_min_y - other['max_y'], other['min_y'] - cur_max_y))
            dist = max(dx, dy)

            # Only merge if components are closely touching/adjacent (gap <= 6 pixels)
            if dist <= 6:
                new_min_x = min(cur_min_x, other['min_x'])
                new_max_x = max(cur_max_x, other['max_x'])
                new_min_y = min(cur_min_y, other['min_y'])
                new_max_y = max(cur_max_y, other['max_y'])
                new_w = new_max_x - new_min_x + 1
                new_h = new_max_y - new_min_y + 1
                new_aspect = min(new_w, new_h) / float(max(new_w, new_h))

                # Ensure merging preserves a balanced rectangular/square shape
                if new_aspect >= 0.45:
                    cur_min_x, cur_max_x = new_min_x, new_max_x
                    cur_min_y, cur_max_y = new_min_y, new_max_y

        return cur_min_x, cur_min_y, cur_max_x, cur_max_y

    def _perform_extra_subject_crop(self, img: Image.Image) -> Image.Image:
        """
        EXTRA CROP:
        Strictly isolates the central primary photo, handles nested stripes/containers,
        unites multi-person subjects, and guarantees 0% outer border bleed.
        """
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
            return self._perform_standard_crop(img)

        # Check if the primary component is a container stripe/banner (like Sweet Dreams)
        comps.sort(key=lambda c: c['area'], reverse=True)
        container_result = self._inspect_and_unwrap_container(comps[0], proxy, pw, ph)

        if container_result:
            target_bg_color, candidate_comps = container_result
        else:
            target_bg_color, candidate_comps = bg_ref, comps

        # Find the subject bounding box (merges side-by-side persons, rejects distant text)
        sub_min_x, sub_min_y, sub_max_x, sub_max_y = self._find_subject_box(candidate_comps, pw, ph)

        scale_to_orig = 1.0 / scale
        rough_box = (
            int(round(sub_min_x * scale_to_orig)),
            int(round(sub_min_y * scale_to_orig)),
            int(round(sub_max_x * scale_to_orig)),
            int(round(sub_max_y * scale_to_orig))
        )

        # Refine boundaries directly against the immediate surrounding background
        x1, y1, x2, y2 = self._refine_box_to_photo_edges(img, rough_box, target_bg_color)

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

 
    
    def _perform_extra_crop(self, img: Image.Image) -> Image.Image:
        """Crops out borders and aggressively zooms in by 15% on the subject."""
        orig_w, orig_h = img.size
        top_b, bottom_b, left_b, right_b = self._detect_borders(img, tolerance=32)
        
        min_x = max(0, left_b)
        min_y = max(0, top_b)
        max_x = min(orig_w, orig_w - right_b)
        max_y = min(orig_h, orig_h - bottom_b)
        
        content_w = max_x - min_x
        content_h = max_y - min_y
        
        if content_w < 10 or content_h < 10:
            content_w, content_h = orig_w, orig_h
            min_x, min_y, max_x, max_y = 0, 0, orig_w, orig_h

        # Zoom in 15% deeper to eliminate any thin inner borders, text, or margins
        crop_dim = int(min(content_w, content_h) * 0.85)
        crop_dim = max(10, min(crop_dim, min(orig_w, orig_h)))
        
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        
        half = crop_dim / 2.0
        left = int(max(0, min(center_x - half, orig_w - crop_dim)))
        top = int(max(0, min(center_y - half, orig_h - crop_dim)))
        
        return img.crop((left, top, left + crop_dim, top + crop_dim))

    def _perform_border_crop(self, img_to_crop: Image.Image) -> Optional[Image.Image]:
        try:
            orig_w, orig_h = img_to_crop.size
            scale = 128 / max(orig_w, orig_h)
            proxy_w = int(orig_w * scale)
            proxy_h = int(orig_h * scale)
            
            proxy = img_to_crop.resize((proxy_w, proxy_h), Image.Resampling.BILINEAR)

            border_color = self.get_dominant_border_color(proxy)
            bbox = self._find_content_bounding_box(proxy, border_color, threshold=20)
            
            if not bbox:
                return img_to_crop 

            min_x, min_y, max_x, max_y = bbox
            content_w = max_x - min_x
            content_h = max_y - min_y
            
            crop_size = min(content_w, content_h)
            
            center_x = min_x + content_w // 2
            center_y = min_y + content_h // 2
            
            real_size = int(crop_size / scale)
            real_cx = int(center_x / scale)
            real_cy = int(center_y / scale)
            
            real_left = real_cx - (real_size // 2)
            real_top = real_cy - (real_size // 2)
            
            return self._balance_border(img_to_crop, img_to_crop, real_left, real_top, real_size, border_color, 40)

        except Exception as e:
            _LOGGER.error("Error in normal crop: %s", e)
            return img_to_crop

    def _draw_text_with_shadow(self, draw: ImageDraw.ImageDraw, xy: tuple, text: str, font: ImageFont.FreeTypeFont, text_color: tuple, shadow_color: tuple):
        x, y = xy
        draw.text((x + 1, y + 1), text, font=font, fill=shadow_color)
        draw.text((x, y + 1), text, font=font, fill=shadow_color)
        if shadow_color == (255, 255, 255, 128):
            draw.text((x + 1, y - 1), text, font=font, fill=shadow_color)
            draw.text((x - 1, y), text, font=font, fill=shadow_color)
        draw.text((x, y), text, font=font, fill=text_color)
    
    def _draw_burned_text(self, img: Image.Image, artist: str, title: str) -> Image.Image:
        if not (artist or title): return img
        
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
                
        if not artist_rgb: artist_rgb = (255,255,255)
        if not title_rgb: title_rgb = (255,255,0)

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
                if layer.textbbox((0,0), test, font=font)[2] <= max_w: cur = test
                else:
                    if cur: lines.append(cur)
                    cur = w
            if cur: lines.append(cur)
            return lines

        artist_lines = _wrap(artist)
        title_lines = _wrap(title)
        
        if not artist_lines and not title_lines: return img.convert("RGB")

        y = max(2, (img.height - ((len(artist_lines) + len(title_lines)) * 11 + 4)) // 2)

        for line in artist_lines:
            w = layer.textbbox((0,0), line, font=font)[2]
            x = (img.width - w) // 2
            self._draw_text_with_shadow(layer, (x, y), line, font, (*artist_rgb, 255), artist_shadow)
            y += 11
        if artist_lines and title_lines: y += 4
        for line in title_lines:
            w = layer.textbbox((0,0), line, font=font)[2]
            x = (img.width - w) // 2
            self._draw_text_with_shadow(layer, (x, y), line, font, (*title_rgb, 255), title_shadow)
            y += 11

        return img_copy.convert("RGB")

    def fixed_size(self, img: Image.Image) -> Image.Image:
        width, height = img.size
        if width == height: return img
        elif height < width:
            border_size = (width - height) // 2
            try: background_color = img.getpixel((0, 0))
            except Exception: background_color = (0, 0, 0)
            new_img = Image.new("RGB", (width, width), background_color)
            new_img.paste(img, (0, border_size))
            img = new_img
        elif width != height:
            new_size = min(width, height)
            left = (width - new_size) // 2
            top = (height - new_size) // 2
            img = img.crop((left, top, left + new_size, top + new_size))
        return img

    def text_clock_img(self, img: Image.Image, cached_data: dict, media_data: "MediaData") -> Image.Image:
        if getattr(self.config, 'special_mode', False):
            return img

        is_top = getattr(self.config, 'overlay_top', True)
        y_start, y_end = (2, 9) if is_top else (55, 62)
        align_mode = getattr(self.config, 'overlay_align', 'Clock Right, Temp Left')

        if bool(getattr(self.config, 'show_clock', False) and getattr(self.config, 'text_bg', False)) and not getattr(self.config, 'show_lyrics', False):
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

        if bool(getattr(self.config, 'temperature', False) and getattr(self.config, 'text_bg', False)) and not getattr(self.config, 'show_lyrics', False):
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

        if getattr(self.config, 'text_bg', False) and getattr(self.config, 'show_text', False) and not getattr(self.config, 'show_lyrics', False) and not getattr(media_data, 'playing_tv', False):
            lpc = (0, 0, 64, 16) if getattr(self.config, 'top_text', False) else (0, 48, 64, 64)
            lower_part_img = img.crop(lpc)
            stat = ImageStat.Stat(lower_part_img.convert("L"))
            factor = max(0.1, 1.0 - (stat.mean[0] / 180.0))
            img.paste(ImageEnhance.Brightness(lower_part_img).enhance(factor), lpc)

        return img

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
                img = img.resize((64, 64), Image.Resampling.BILINEAR)

                if getattr(self.config, 'special_mode', False):
                    img = self.special_mode(img)

                if getattr(self.config, 'show_lyrics', False) and not getattr(media_data, 'playing_radio', False) and not getattr(self.config, 'special_mode', False):
                    img = ImageEnhance.Brightness(img).enhance(0.55)
                    img = ImageEnhance.Contrast(img).enhance(0.5)

                cached_data = {}
                img = self.text_clock_img(img, cached_data, media_data)

                return self.gbase64(img)
        except Exception:
            return None

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
                
                # Cache the token and set expiration 60 seconds early to be safe
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
        """Generic wrapper for Spotify API requests handling tokens and errors."""
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
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            _LOGGER.error("Spotify API request failed for endpoint '%s': %s", endpoint, e)
        except Exception as e:
            _LOGGER.error("Unexpected error in Spotify API request for '%s': %s", endpoint, e)
            
        return None

    async def get_spotify_json(self, artist: str, title: str) -> Optional[dict]: 
        params = {
            "q": f"track: {title} artist: {artist}", 
            "type": "track", 
            "limit": 50
        }
        return await self._async_spotify_request("search", params=params)

    async def get_spotify_artist_image_url_by_name(self, artist_name: str) -> Optional[str]: 
        if not artist_name: 
            return None
            
        params = {
            "q": f"artist:{artist_name}", 
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

    async def get_album_list(self, media_data: "MediaData", returntype: str) -> list[str]: 
        if not self.spotify_data or getattr(media_data, 'playing_tv', False): 
            return []
            
        try:
            tracks = self.spotify_data.get('tracks', {}).get('items', [])
            albums = {} 
            
            for track in tracks:
                album = track.get('album', {})
                album_id = album.get('id')
                artists = album.get('artists', [])
                
                # Skip various artists and ensure primary artist matches
                if any(artist.get('name', '').lower() == 'various artists' for artist in artists): 
                    continue
                if media_data.artist.lower() not in [artist.get('name', '').lower() for artist in artists]: 
                    continue
                if album_id not in albums: 
                    albums[album_id] = album

            # Sort singles vs albums and slice the top 10
            sorted_albums = sorted(
                albums.values(), 
                key=lambda x: (x.get("album_type") == "single", x.get("album_type") == "album"), 
                reverse=True
            )[:10]
            
            album_urls = [album.get("images", [])[0]["url"] for album in sorted_albums if album.get("images")]
            media_data.pic_url = album_urls
            media_data.pic_source = "Spotify (Slide)"
            
            return album_urls
        except Exception as e: 
            _LOGGER.error("Failed to parse Spotify album list: %s", e)
            return []

    async def get_slide_img(self, picture: str, media_data: "MediaData") -> Optional[str]: 
        try:
            image_raw_data = await self.image_processor.get_raw_image_data(picture)
            if image_raw_data:
                return await self.image_processor.process_slide_image(image_raw_data, media_data)
        except Exception as e: 
            _LOGGER.error("Failed to process slide image: %s", e)
        return None

    async def prefetch_slider_data(self, media_data: "MediaData") -> int:
        response_json = await self.get_spotify_json(media_data.artist, media_data.title)
        if not response_json: 
            return 0
        
        artist_pic_url = await self.get_spotify_artist_image_url_by_name(media_data.artist)
        if artist_pic_url:
            await self.image_processor.async_prefetch_url(artist_pic_url, media_data)
            
        tracks = response_json.get('tracks', {}).get('items', [])
        albums = {}
        for track in tracks:
            album = track.get('album', {})
            album_id = album.get('id')
            artists = album.get('artists', [])
            
            if any(artist.get('name', '').lower() == 'various artists' for artist in artists): 
                continue
            if media_data.artist.lower() not in [artist.get('name', '').lower() for artist in artists]: 
                continue
            if album_id not in albums: 
                albums[album_id] = album
            
        sorted_albums = sorted(
            albums.values(), 
            key=lambda x: (x.get("album_type") == "single", x.get("album_type") == "album"), 
            reverse=True
        )[:10]
        
        album_urls = [album.get("images", [])[0]["url"] for album in sorted_albums if album.get("images")]
        
        for url in album_urls:
            await self.image_processor.async_prefetch_url(url, media_data)
            
        return len(album_urls)

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
            artist_pic_url = await self.get_spotify_artist_image_url_by_name(media_data.artist)
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

            album_urls = await self.get_album_list(media_data, returntype="url")
            if not album_urls: 
                return

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
                return

            media_data.spotify_slide_pass = True
            
            await pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [{"Command": "Draw/ResetHttpGifId"}]
            })
            
            for pic_offset, b64_frame in enumerate(album_urls_b64):
                await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", frames, 64, pic_offset, 0, 5000, b64_frame)
                
        except Exception as e: 
            _LOGGER.error("Spotify Albums Slide Animation Error: %s", e)

    def _build_preview_frame_sync(self, artist_img: Image.Image, media_data: "MediaData") -> Optional[str]:
        """Synchronous method to generate the preview frame without blocking the event loop."""
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
        """Synchronous method to stitch together album frames without blocking the event loop."""
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
            artist_img = None
            artist_pic_url = await self.get_spotify_artist_image_url_by_name(media_data.artist)
            
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

            album_urls = await self.get_album_list(media_data, returntype="url")
            if not album_urls: 
                return

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

            # Offload heavy stitching logic to executor
            pixoo_frames = await self.image_processor.hass.async_add_executor_job(
                self._build_animation_frames_sync, prepared_albums, media_data
            )
            
            if not pixoo_frames:
                return

            media_data.spotify_slide_pass = True 
            
            await pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [{"Command": "Draw/ResetHttpGifId"}]
            })
            
            for offset, frame in enumerate(pixoo_frames):
                await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", len(pixoo_frames), 64, offset, 0, 5000, frame)
            
        except Exception as e:
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

        if len(self.lyrics_cache) >= 100: self.lyrics_cache.popitem(last=False)
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

class TitleCleaner:
    """Utility class to sanitize track titles by removing unnecessary tags."""
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
    """Holds media state and handles fetching/parsing updates from Home Assistant."""
    def __init__(self, hass: HomeAssistant, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession):
        self.hass = hass
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.lyrics_provider = LyricsProvider(self.config, self.session)
        self.title_cleaner = TitleCleaner()
        
        # Internal State Tracking
        self.prev_title: str = ""
        self.prev_artist: str = ""
        self.track_changed: bool = False 
        
        # Media DTO Attributes
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
        self.spotify_slide_pass: bool = False
        self.slider_frames: int = 0

    def clean_title(self, title: str) -> str: 
        return self.title_cleaner.clean(title)

    async def update(self) -> Optional["MediaData"]:
        try:
            media_state_obj = self.hass.states.get(self.config.media_player)
            if not media_state_obj or media_state_obj.state not in ["playing", "on"]: 
                return None

            attributes = media_state_obj.attributes
            
            raw_title = attributes.get('media_title')
            raw_artist = attributes.get('media_artist')
            app_name = attributes.get('app_name')

            # 1. Check TV Mode
            if self._is_tv_playing(raw_title, raw_artist, app_name, attributes):
                self._set_tv_state()
                return self

            # 2. Validate valid Title / Artist (Fallback if missing)
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

            # 3. Parse and set general media state
            self._set_media_state(raw_title, raw_artist, attributes)
            
            # 4. Check Radio Mode
            self._evaluate_radio_mode(raw_title, raw_artist, attributes)

            # 5. Fetch Lyrics if applicable
            await self._fetch_lyrics()

            # 6. Update track change status
            self.track_changed = (self.title != self.prev_title or self.artist != self.prev_artist)
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

    def format_ai_image_prompt(self, artist: Optional[str], title: str) -> Optional[str]: 
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


class FallbackService:
    def __init__(self, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession, spotify_service: "SpotifyService", pixoo_device: "PixooDevice"): 
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.spotify_service = spotify_service
        self.pixoo_device = pixoo_device
        self.tidal_token_cache: dict[str, Any] = {'token': None, 'expires': 0}
        self.fail_txt = False
        self.fallback = False
        self._artwork_cache: OrderedDict[str, dict] = OrderedDict()
        self._last_mb_query: float = 0.0

    async def prefetch_next_track(self, url: Optional[str], media_data: "MediaData"):
        await self.get_final_url(url, media_data)
        frames = 0
        if getattr(self.config, 'spotify_slide', False) and not getattr(media_data, 'radio_logo', False):
            frames = await self.spotify_service.prefetch_slider_data(media_data)
        media_data.slider_frames = frames

    async def get_final_url(self, picture: Optional[str], media_data: "MediaData") -> Optional[dict]: 
        self.fail_txt = False
        self.fallback = False
        media_data.pic_url = None 
        
        if getattr(self.config, 'burned', False) or not media_data.album:
            song_cache_key = f"{media_data.artist}_{media_data.title}".strip().lower()
        else:
            song_cache_key = f"{media_data.artist}_{media_data.album}".strip().lower()
        
        if getattr(self.config, 'force_ai', False) and getattr(self.config, 'pollinations', None) and not getattr(media_data, 'radio_logo', False) and not getattr(media_data, 'playing_tv', False):
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
            media_data.pic_url = cached['url']
            media_data.pic_source = cached['source']
            _LOGGER.debug("Reusing resolved artwork for '%s' from %s", song_cache_key, cached['source'])
            return cached['data']

        try:
            if picture and not (getattr(media_data, 'playing_radio', False) and not getattr(media_data, 'radio_logo', False)):
                result = await self.image_processor.get_image(picture, media_data, getattr(media_data, 'spotify_slide_pass', False))
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
                        proc_res = await self.image_processor.get_image(image_url, media_data, getattr(media_data, 'spotify_slide_pass', False))
                        if proc_res:
                            self._save_to_artwork_cache(song_cache_key, proc_res, image_url, "Spotify")
                            media_data.pic_url = image_url
                            media_data.pic_source = "Spotify"
                            return proc_res
                self.spotify_artist_pic = await self.spotify_service.get_spotify_artist_image_url_by_name(media_data.artist)
            except Exception as e: 
                _LOGGER.error("Spotify fallback failed: %s", e) 
        
        tasks, providers = [], []
        if getattr(self.config, 'discogs', None):
            tasks.append(self.search_discogs_album_art(media_data.artist, media_data.title))
            providers.append("Discogs")

        if getattr(self.config, 'lastfm', None):
            tasks.append(self.search_lastfm_album_art(media_data.artist, media_data.title, media_data.album))
            providers.append("Last.FM")
            
        tidal_id = getattr(self.config, 'tidal_client_id', None)
        tidal_secret = getattr(self.config, 'tidal_client_secret', None)
        if tidal_id and tidal_secret:
            tasks.append(self.get_tidal_album_art_url(media_data.artist, media_data.title))
            providers.append("TIDAL")

            
        if getattr(self.config, 'musicbrainz', False):
            tasks.append(self.get_musicbrainz_album_art_url(media_data.artist, media_data.title))
            providers.append("MusicBrainz")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) or not result: continue
                provider_name = providers[i]
                proc_result = await self.image_processor.get_image(result, media_data, getattr(media_data, 'spotify_slide_pass', False))
                if proc_result:
                    self._save_to_artwork_cache(song_cache_key, proc_result, result, provider_name)
                    media_data.pic_url = result
                    media_data.pic_source = provider_name
                    return proc_result

        if self.spotify_artist_pic:
            result = await self.image_processor.get_image(self.spotify_artist_pic, media_data, getattr(media_data, 'spotify_slide_pass', False))
            if result:
                self._save_to_artwork_cache(song_cache_key, result, self.spotify_artist_pic, "Spotify Artist")
                media_data.pic_source = "Spotify Artist"
                return result

        if not getattr(self.config, 'force_ai', False) and getattr(self.config, 'pollinations', None):
            result = await self._try_ai_generation(media_data)
            if result: 
                if media_data.pic_url:
                    self._save_to_artwork_cache(song_cache_key, result, media_data.pic_url, "AI")
                media_data.pic_source = "AI"
                return result

        if self.spotify_first_album:
            result = await self.image_processor.get_image(self.spotify_first_album, media_data, getattr(media_data, 'spotify_slide_pass', False))
            if result:
                media_data.pic_url = self.spotify_first_album
                media_data.pic_source = "Spotify (Artist Profile Image)"
                return result

        media_data.pic_url = "Fallback Image"
        media_data.pic_source = "Internal"
        return self._get_fallback_black_image_data(media_data)

    def _save_to_artwork_cache(self, key: str, data: dict, url: str, source: str):
        if len(self._artwork_cache) >= 50:
            self._artwork_cache.popitem(last=False)
        self._artwork_cache[key] = {
            'data': data,
            'url': url,
            'source': source
        }

    async def _try_ai_generation(self, media_data):
        ai_url = media_data.format_ai_image_prompt(media_data.artist, media_data.title)
        if not ai_url: return None
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self.image_processor.get_image(ai_url, media_data, getattr(media_data, 'spotify_slide_pass', False)),
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
        
        # Create a dark slate background to make it look intentional
        img = Image.new("RGB", (64, 64), (25, 25, 30)) 
        draw = ImageDraw.Draw(img)
        
        # Add a subtle border
        draw.rectangle([0, 0, 63, 63], outline=(50, 50, 60), width=1)
        
        if media_data:
            artist = getattr(media_data, 'artist', 'Unknown Artist')
            title = getattr(media_data, 'title', 'Unknown Track')
            
            if artist == "Unknown Artist" and title == "Unknown Track":
                # Draw a minimalistic music note centered on the screen
                draw.ellipse([24, 34, 32, 42], fill=(150, 150, 150))
                draw.ellipse([38, 30, 46, 38], fill=(150, 150, 150))
                draw.line([(32, 38), (32, 18)], fill=(150, 150, 150), width=2)
                draw.line([(46, 34), (46, 14)], fill=(150, 150, 150), width=2)
                draw.line([(32, 18), (46, 14)], fill=(150, 150, 150), width=2)
                draw.line([(32, 19), (46, 15)], fill=(150, 150, 150), width=2)
            else:
                # Reuse the ImageProcessor's burned text logic to render the artist/title elegantly
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

    async def get_musicbrainz_album_art_url(self, ai_artist: str, ai_title: str) -> Optional[str]: 
            now = time.monotonic()
            elapsed = now - getattr(self, '_last_mb_query', 0.0)
            if elapsed < 1.1:
                await asyncio.sleep(1.1 - elapsed)
            self._last_mb_query = time.monotonic()
    
            search_url = "https://musicbrainz.org/ws/2/release/"
            headers = { 
                "Accept": "application/json", 
                "User-Agent": "Pixoo64MediaArt/1.0 (https://github.com/idodov/pixoo64_art)" 
            }
            clean_artist = str(ai_artist or "").replace('"', '').strip()
            clean_title = str(ai_title or "").replace('"', '').strip()
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

    async def search_discogs_album_art(self, ai_artist: str, ai_title: str) -> Optional[str]: 
        base_url = "https://api.discogs.com/database/search"
        headers = { "User-Agent": "AlbumArtSearchApp/1.0", "Authorization": f"Discogs token={self.config.discogs}" }
        params = { "artist": ai_artist, "track": ai_title, "type": "release", "format": "album", "per_page": 5 }
        try:
            async with self.session.get(base_url, headers=headers, params=params, timeout=10) as response: 
                if response.status != 200: 
                    _LOGGER.warning(f"Discogs API returned status {response.status}")
                    return None
                data = await response.json()
                results = data.get("results", [])
                if not results: return None
                return results[0].get("cover_image")
        except Exception as e: 
            _LOGGER.error(f"Discogs search exception: {e}")
            return None

    def _is_valid_lastfm_image(self, url: Optional[str]) -> bool:
        """Validate that the Last.fm image is not empty and not the default star placeholder."""
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        if not url.startswith("http"):
            return False
        # Last.fm returns this specific hash for empty/placeholder star artwork
        if "2a96cbd8b46e442fc41c2b86b821562f" in url or "default_album" in url:
            return False
        return True

    def _optimize_lastfm_url(self, url: str) -> str:
        """Upgrade Last.fm image URL to 300x300 resolution for optimal cropping and display."""
        if url and "fastly.net" in url:
            return re.sub(r'/i/u/(?:\d+s|\d+x\d+)/', '/i/u/300x300/', url)
        return url

    def _extract_lastfm_image_url(self, image_list: list) -> Optional[str]:
        """Extract the highest quality valid image from Last.fm image list."""
        if not isinstance(image_list, list):
            return None
            
        # Priority order: extralarge, mega, large, medium
        preferred_sizes = ["mega", "extralarge", "large", "medium"]
        
        # 1. Search by preferred size
        for size in preferred_sizes:
            for item in image_list:
                if isinstance(item, dict) and item.get("size") == size:
                    img_url = item.get("#text", "")
                    if self._is_valid_lastfm_image(img_url):
                        return self._optimize_lastfm_url(img_url)

        # 2. Fallback: Check in reverse (last valid image)
        for item in reversed(image_list):
            if isinstance(item, dict):
                img_url = item.get("#text", "")
                if self._is_valid_lastfm_image(img_url):
                    return self._optimize_lastfm_url(img_url)

        return None

    async def search_lastfm_album_art(self, ai_artist: str, ai_title: str, album: Optional[str] = None) -> Optional[str]: 
        clean_artist = str(ai_artist or "").strip()
        clean_title = str(ai_title or "").strip()
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
                "method": "album.getInfo",
                "api_key": api_key,
                "artist": clean_artist,
                "album": clean_album,
                "autocorrect": 1,
                "format": "json"
            }
            try:
                async with self.session.get(base_url, headers=headers, params=params, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        images = data.get("album", {}).get("image", [])
                        valid_url = self._extract_lastfm_image_url(images)
                        if valid_url:
                            _LOGGER.debug("Last.fm: Found album art via album.getInfo: %s", valid_url)
                            return valid_url
                    else:
                        err_text = await response.text()
                        _LOGGER.warning("Last.fm album.getInfo HTTP %s: %s", response.status, err_text)
            except Exception as e:
                _LOGGER.debug("Last.fm album.getInfo query error: %s", e)

        if clean_title and clean_title != "Unknown Track":
            params = {
                "method": "track.getInfo",
                "api_key": api_key,
                "artist": clean_artist,
                "track": clean_title,
                "autocorrect": 1,
                "format": "json"
            }
            try:
                async with self.session.get(base_url, headers=headers, params=params, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        track_data = data.get("track", {})
                        
                        album_obj = track_data.get("album", {})
                        images = album_obj.get("image", [])
                        valid_url = self._extract_lastfm_image_url(images)
                        if valid_url:
                            _LOGGER.debug("Last.fm: Found album art via track.getInfo: %s", valid_url)
                            return valid_url
                        
                        discovered_album = album_obj.get("title")
                        if discovered_album and discovered_album != clean_album:
                            alb_params = {
                                "method": "album.getInfo",
                                "api_key": api_key,
                                "artist": clean_artist,
                                "album": discovered_album,
                                "autocorrect": 1,
                                "format": "json"
                            }
                            async with self.session.get(base_url, headers=headers, params=alb_params, timeout=8) as alb_response:
                                if alb_response.status == 200:
                                    alb_data = await alb_response.json()
                                    alb_images = alb_data.get("album", {}).get("image", [])
                                    valid_url = self._extract_lastfm_image_url(alb_images)
                                    if valid_url:
                                        _LOGGER.debug("Last.fm: Found album art via discovered album: %s", valid_url)
                                        return valid_url
                    else:
                        err_text = await response.text()
                        _LOGGER.warning("Last.fm track.getInfo HTTP %s: %s", response.status, err_text)

            except Exception as e:
                _LOGGER.error("Last.fm search exception: %s", e)

        return None

    def _format_tidal_uuid(self, val: Any) -> Optional[str]:
        """Convert a Tidal artwork UUID into the directory structure used by Tidal CDN."""
        if not val or not isinstance(val, str):
            return None
        cleaned = val.strip().replace("-", "").replace("/", "")
        if len(cleaned) == 32 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
            return f"{cleaned[:8]}/{cleaned[8:12]}/{cleaned[12:16]}/{cleaned[16:20]}/{cleaned[20:]}"
        return None

    def _ensure_320_resolution(self, url: str) -> str:
        """Ensure Tidal CDN URL requests the optimal 320x320 resolution."""
        if url and "resources.tidal.com" in url:
            return re.sub(r'\d+x\d+', '320x320', url)
        return url

    def _extract_tidal_image(self, item: dict) -> Optional[str]:
        """Extract a cover art image URL targeting 320x320 resolution."""
        if not isinstance(item, dict):
            return None

        attrs = item.get("attributes", {})

        # 1. Check for files / imageLinks / images arrays
        for key in ["files", "imageLinks", "images"]:
            links = attrs.get(key)
            if isinstance(links, list) and links:
                # First pass: try finding explicit 320x320
                for candidate in links:
                    if isinstance(candidate, dict):
                        href = candidate.get("href") or candidate.get("url")
                        meta = candidate.get("meta", {})
                        if (meta.get("width") == 320) or (href and "320x320" in href):
                            return self._ensure_320_resolution(href)
                # Second pass: pick any valid url and transform it to 320x320
                for candidate in reversed(links):
                    if isinstance(candidate, dict):
                        href = candidate.get("href") or candidate.get("url")
                        if href and isinstance(href, str) and href.startswith("http"):
                            return self._ensure_320_resolution(href)

        # 2. Check for direct URL string in attributes
        for key in ["href", "url", "image", "picture"]:
            val = attrs.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return self._ensure_320_resolution(val)

        # 3. If item type is artworks/coverArt, its ID is the UUID on resources.tidal.com
        item_type = str(item.get("type", "")).lower()
        if item_type in ["artworks", "artwork", "coverart"]:
            uuid_path = self._format_tidal_uuid(item.get("id"))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        # 4. Check cover attribute in albums
        for cover_key in ["cover", "coverArt", "imageCover"]:
            uuid_path = self._format_tidal_uuid(attrs.get(cover_key))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        # 5. Check coverArt relationship in album/track
        cover_data = item.get("relationships", {}).get("coverArt", {}).get("data")
        if isinstance(cover_data, dict):
            uuid_path = self._format_tidal_uuid(cover_data.get("id"))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"
        elif isinstance(cover_data, list):
            for entry in cover_data:
                if isinstance(entry, dict):
                    uuid_path = self._format_tidal_uuid(entry.get("id"))
                    if uuid_path:
                        return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        return None

    async def get_tidal_album_art_url(self, artist: str, title: str) -> Optional[str]: 
        #_LOGGER.warning(f"-> TIDAL Search initiated for Artist: '{artist}', Title: '{title}'")
        
        base_url = "https://openapi.tidal.com/v2/"
        access_token = await self.get_tidal_access_token()
        if not access_token: 
            _LOGGER.warning("-> TIDAL Token failed to generate!")
            return None
        
        clean_artist = str(artist).strip() if artist and artist != "Unknown Artist" else ""
        clean_title = str(title).strip() if title and title != "Unknown Track" else ""
        query = f"{clean_artist} {clean_title}".strip()
        
        if len(query) < 2 or query == "-":
            return None
            
        headers = { 
            "Authorization": f"Bearer {access_token}", 
            "Accept": "application/vnd.api+json" 
        }
        
        search_url = f"{base_url}searchResults"
        search_params = { 
            "countryCode": "US", 
            "filter[query]": query,
            "include": "tracks.albums.coverArt,albums.coverArt" 
        }
        
        try:
            async with self.session.get(search_url, headers=headers, params=search_params, timeout=10) as response: 
                if response.status != 200:
                    err = await response.text()
                    _LOGGER.warning(f"-> TIDAL HTTP {response.status}: {err}")
                    return None
                
                search_data = await response.json()
                included_items = search_data.get("included", [])
                
                # Priority 1: Check included artworks directly
                for inc in included_items:
                    if str(inc.get("type", "")).lower() in ["artworks", "artwork", "coverart"]:
                        img_url = self._extract_tidal_image(inc)
                        if img_url:
                            #_LOGGER.warning(f"-> TIDAL SUCCESS via included artwork (320x320): {img_url}")
                            return img_url

                # Priority 2: Check included albums
                for inc in included_items:
                    if str(inc.get("type", "")).lower() == "albums":
                        img_url = self._extract_tidal_image(inc)
                        if img_url:
                            #_LOGGER.warning(f"-> TIDAL SUCCESS via included album (320x320): {img_url}")
                            return img_url

                # Priority 3: Check any other included items
                for inc in included_items:
                    img_url = self._extract_tidal_image(inc)
                    if img_url:
                        #_LOGGER.warning(f"-> TIDAL SUCCESS via included resource (320x320): {img_url}")
                        return img_url

                # Priority 4: Regex search for direct Tidal CDN URL anywhere in the JSON
                text_response = json.dumps(search_data)
                url_match = re.search(r'https?://(?:resources|images)\.tidal\.com/images/[a-zA-Z0-9/_-]+(?:\.jpg|\.png)', text_response)
                if url_match:
                    img_url = self._ensure_320_resolution(url_match.group(0))
                    #_LOGGER.warning(f"-> TIDAL SUCCESS via text regex (320x320): {img_url}")
                    return img_url

                # Priority 5: Search for any standalone UUID in the response
                uuid_matches = re.findall(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', text_response)
                for u in uuid_matches:
                    formatted = self._format_tidal_uuid(u)
                    if formatted:
                        img_url = f"https://resources.tidal.com/images/{formatted}/320x320.jpg"
                        #_LOGGER.warning(f"-> TIDAL SUCCESS via extracted UUID (320x320): {img_url}")
                        return img_url

                _LOGGER.warning(f"-> TIDAL: No cover art found. Included types: {[x.get('type') for x in included_items]}")
                return None
        except Exception as e: 
            _LOGGER.warning(f"-> TIDAL search exception: {e}")
            return None

    async def get_tidal_access_token(self) -> Optional[str]: 
        if self.tidal_token_cache['token'] and time.time() < self.tidal_token_cache['expires']:
            return self.tidal_token_cache['token']
            
        url = "https://auth.tidal.com/v1/oauth2/token"
        
        # Use Basic Auth standard for OAuth2
        client_id = str(self.config.tidal_client_id).strip()
        client_secret = str(self.config.tidal_client_secret).strip()
        auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        
        tidal_headers = { 
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/x-www-form-urlencoded" 
        }
        payload = { "grant_type": "client_credentials" }
        
        try:
            async with self.session.post(url, headers=tidal_headers, data=payload, timeout=10) as response: 
                if response.status != 200: 
                    _LOGGER.error(f"TIDAL Token Auth failed: {response.status} - {await response.text()}")
                    return None
                response_json = await response.json()
                access_token = response_json["access_token"]
                expiry_time = time.time() + response_json.get("expires_in", 3600) - 60 
                self.tidal_token_cache = { 'token': access_token, 'expires': expiry_time }
                return access_token
        except Exception as e: 
            _LOGGER.error(f"TIDAL token exception: {e}")
            return None

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
                await asyncio.sleep(0.4)
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

        if n_type == "v":
            draw.line([(cx-8, cy), (cx-2, cy+8), (cx+10, cy-8)], fill=active_color, width=3)
        elif n_type == "x":
            s = 7
            draw.line([(cx-s, cy-s), (cx+s, cy+s)], fill=active_color, width=3)
            draw.line([(cx+s, cy-s), (cx-s, cy+s)], fill=active_color, width=3)
        elif n_type == "info":
            draw.ellipse([cx-9, cy-9, cx+9, cy+9], outline=active_color, width=1)
            draw.rectangle([cx-1, cy-2, cx+1, cy+5], fill=active_color) 
            draw.rectangle([cx-1, cy-5, cx+1, cy-4], fill=active_color)
        elif n_type == "success":
            draw.line([(cx-6, cy), (cx-2, cy+6), (cx+7, cy-5)], fill=active_color, width=2)
        elif n_type in ["warning", "alert"]:
            if n_type == "alert":
                draw.arc([cx-6, cy-5, cx+6, cy+5], 180, 0, fill=active_color, width=1)
                draw.line([(cx-6, cy), (cx-8, cy+6)], fill=active_color, width=1)
                draw.line([(cx+6, cy), (cx+8, cy+6)], fill=active_color, width=1)
                draw.line([(cx-8, cy+6), (cx+8, cy+6)], fill=active_color, width=1)
                clapper_x = cx + (2 if frame_num == 1 else 0)
                draw.line([(clapper_x-1, cy+6), (clapper_x+1, cy+6)], fill=active_color, width=1)
                draw.point((clapper_x, cy+8), fill=active_color)
            else:
                draw.polygon([(cx, cy-9), (cx-10, cy+8), (cx+10, cy+8)], outline=active_color, fill=None)
                draw.line([(cx, cy-3), (cx, cy+3)], fill=active_color, width=1)
                draw.point((cx, cy+5), fill=active_color)
        elif n_type == "error":
            s = 5
            draw.line([(cx-s, cy-s), (cx+s, cy+s)], fill=active_color, width=2)
            draw.line([(cx+s, cy-s), (cx-s, cy+s)], fill=active_color, width=2)
        elif n_type == "weather":
            draw.ellipse([cx+2, cy-8, cx+8, cy-2], outline=(255, 215, 0), width=1)
            draw.arc([cx-8, cy-2, cx+2, cy+6], 90, 270, fill=active_color, width=1)
            draw.arc([cx-2, cy-4, cx+8, cy+6], 180, 0, fill=active_color, width=1)
            draw.line([(cx-8, cy+2), (cx+8, cy+2)], fill=active_color, width=1)
        elif n_type == "attack":
            draw.line([(cx, cy-9), (cx-3, cy-4)], fill=active_color, width=1)
            draw.line([(cx, cy-9), (cx+3, cy-4)], fill=active_color, width=1)
            draw.rectangle([cx-3, cy-4, cx+3, cy+4], outline=active_color, width=1)
            draw.line([(cx-3, cy+4), (cx-6, cy+8)], fill=active_color, width=1)
            draw.line([(cx+3, cy+4), (cx+6, cy+8)], fill=active_color, width=1)
            fire_color = (255, 165, 0) if frame_num == 0 else (255, 255, 0)
            draw.line([(cx-1, cy+4), (cx-1, cy+7)], fill=fire_color, width=1)
            draw.line([(cx+1, cy+4), (cx+1, cy+7)], fill=fire_color, width=1)
        elif n_type == "wifi":
            draw.point((cx, cy+6), fill=active_color)
            if frame_num >= 1: draw.arc([cx-4, cy, cx+4, cy+8], 225, 315, fill=active_color, width=1)
            if frame_num >= 2: draw.arc([cx-8, cy-4, cx+8, cy+4], 225, 315, fill=active_color, width=1)
        elif n_type in ["timer", "time"]:
            draw.ellipse([cx-9, cy-9, cx+9, cy+9], outline=active_color, width=1)
            angle = frame_num * 90
            rad = math.radians(angle - 90)
            draw.line([(cx, cy), (cx + 6 * math.cos(rad), cy + 6 * math.sin(rad))], fill=active_color, width=1)
        elif n_type == "boiler": 
            draw.rectangle([cx-5, cy-8, cx+5, cy+8], outline=active_color, width=1)
            draw.line([(cx+1, cy-4), (cx-2, cy), (cx+2, cy), (cx-1, cy+5)], fill=active_color, width=1)
            draw.point((cx, cy+6), fill=active_color)
        elif n_type == "shutter": 
            draw.rectangle([cx-8, cy-8, cx+8, cy+8], outline=active_color, width=1)
            for y_line in range(cy-5, cy+7, 3):
                draw.line([(cx-6, y_line), (cx+6, y_line)], fill=active_color, width=1)
        elif n_type == "car": 
            draw.rectangle([cx-9, cy, cx+9, cy+6], outline=active_color, width=1)
            draw.line([(cx-9, cy), (cx-5, cy-5), (cx+5, cy-5), (cx+9, cy)], fill=active_color, width=1)
            draw.ellipse([cx-7, cy+5, cx-4, cy+8], fill=active_color)
            draw.ellipse([cx+4, cy+5, cx+7, cy+8], fill=active_color)
        elif n_type == "washer": 
            draw.rectangle([cx-8, cy-8, cx+8, cy+8], outline=active_color, width=1)
            draw.ellipse([cx-5, cy-5, cx+5, cy+5], outline=active_color, width=1)
            draw.point((cx+6, cy-6), fill=active_color) 
        elif n_type == "trash": 
            draw.line([(cx-5, cy+8), (cx+5, cy+8), (cx+7, cy-4), (cx-7, cy-4), (cx-5, cy+8)], fill=active_color, width=1)
            draw.line([(cx-8, cy-4), (cx+8, cy-4)], fill=active_color, width=1)
            draw.rectangle([cx-2, cy-6, cx+2, cy-4], fill=active_color)
        elif n_type == "door": 
            draw.rectangle([cx-6, cy-9, cx+6, cy+9], outline=active_color, width=1)
            draw.line([(cx-6, cy-9), (cx+2, cy-6)], fill=active_color, width=1)
            draw.line([(cx+2, cy-6), (cx+2, cy+9)], fill=active_color, width=1)
            draw.line([(cx+2, cy+9), (cx-6, cy+9)], fill=active_color, width=1)
        elif n_type == "lock": 
            draw.rectangle([cx-6, cy-2, cx+6, cy+7], fill=active_color)
            draw.arc([cx-5, cy-8, cx+5, cy-1], 180, 0, fill=active_color, width=1)
        elif n_type == "mail": 
            draw.rectangle([cx-9, cy-6, cx+9, cy+6], outline=active_color, width=1)
            draw.line([(cx-9, cy-6), (cx, cy+2), (cx+9, cy-6)], fill=active_color, width=1)
        elif n_type == "battery": 
            draw.rectangle([cx-8, cy-4, cx+6, cy+4], outline=active_color, width=1)
            draw.rectangle([cx-7, cy-3, cx-2, cy+3], fill=active_color) 
            draw.rectangle([cx+6, cy-2, cx+8, cy+2], fill=active_color) 
        elif n_type == "fire": 
            draw.polygon([(cx, cy-8), (cx+5, cy+2), (cx+3, cy+8), (cx-3, cy+8), (cx-5, cy+2)], outline=active_color, fill=None)
            draw.point((cx, cy+5), fill=active_color)
        elif n_type == "water": 
            draw.polygon([(cx, cy-8), (cx+5, cy+2), (cx, cy+8), (cx-5, cy+2)], outline=active_color, fill=active_color)
        elif n_type == "sleep": 
            draw.arc([cx-6, cy-6, cx+6, cy+6], 90, 270, fill=active_color, width=2)
            draw.line([(cx, cy-6), (cx, cy+6)], fill=active_color, width=1)
        elif n_type == "phone":
            draw.arc([cx-8, cy-4, cx+8, cy+12], 0, 180, fill=active_color, width=2)
            draw.rectangle([cx-9, cy-4, cx-6, cy], fill=active_color)
            draw.rectangle([cx+6, cy-4, cx+9, cy], fill=active_color)
        elif n_type == "calendar":
            draw.rectangle([cx-8, cy-7, cx+8, cy+8], outline=active_color, width=1)
            draw.line([(cx-8, cy-3), (cx+8, cy-3)], fill=active_color, width=1)
            draw.point((cx-4, cy+1), fill=active_color)
            draw.point((cx, cy+1), fill=active_color)
            draw.point((cx+4, cy+1), fill=active_color)
            draw.point((cx-4, cy+5), fill=active_color)
            draw.point((cx, cy+5), fill=active_color)
        elif n_type == "camera":
            draw.rectangle([cx-8, cy-5, cx+8, cy+6], outline=active_color, width=1)
            draw.rectangle([cx-2, cy-8, cx+2, cy-5], fill=active_color)
            draw.ellipse([cx-3, cy-2, cx+3, cy+4], outline=active_color, width=1)
        elif n_type == "music":
            draw.ellipse([cx-7, cy+3, cx-3, cy+7], fill=active_color)
            draw.ellipse([cx+3, cy+3, cx+7, cy+7], fill=active_color)
            draw.line([(cx-3, cy+5), (cx-3, cy-6)], fill=active_color, width=1)
            draw.line([(cx+7, cy+5), (cx+7, cy-6)], fill=active_color, width=1)
            draw.line([(cx-3, cy-6), (cx+7, cy-6)], fill=active_color, width=2)
        elif n_type == "sun":
            draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=active_color)
            s = 7
            draw.line([(cx, cy-s), (cx, cy-s-2)], fill=active_color, width=1)
            draw.line([(cx, cy+s), (cx, cy+s+2)], fill=active_color, width=1)
            draw.line([(cx-s, cy), (cx-s-2, cy)], fill=active_color, width=1)
            draw.line([(cx+s, cy), (cx+s+2, cy)], fill=active_color, width=1)
            draw.point((cx-5, cy-5), fill=active_color)
            draw.point((cx+5, cy-5), fill=active_color)
            draw.point((cx-5, cy+5), fill=active_color)
            draw.point((cx+5, cy+5), fill=active_color)
        elif n_type == "moon":
            draw.arc([cx-6, cy-6, cx+6, cy+6], 90, 270, fill=active_color, width=2)
            draw.line([(cx, cy-6), (cx, cy+6)], fill=active_color, width=1)

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
