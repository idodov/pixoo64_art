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
from concurrent.futures import ThreadPoolExecutor
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
    if not bidi_support: return text
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
        self.temperature_sensor = options.get("temperature_entity", None)
        self.media_player = data.get("media_player", "media_player.living_room")
        self.pixoo_ip = data.get("pixoo_ip")
        self.pixoo_url = f"http://{self.pixoo_ip}:80/post"
        self.pollinations = options.get("pollinations_key", "")
        self.ai_fallback = options.get("ai_model", "flux")
        self.spotify_client_id = options.get("spotify_client_id", "")
        self.spotify_client_secret = options.get("spotify_client_secret", "")
        self.musicbrainz = options.get("musicbrainz_enabled", True)
        self.tidal_client_id = options.get("tidal_client_id", "")
        self.tidal_client_secret = options.get("tidal_client_secret", "")
        self.lastfm = options.get("lastfm", "")
        self.discogs = options.get("discogs", "")
        
        # State driven variables (Updated dynamically by Hub)
        self.show_text = False
        self.clean_title = True
        self.text_bg = True
        self.top_text = False
        self.special_mode_spotify_slider = False
        self.force_font_color = None
        self.burned = False
        self.crop_borders = True
        self.crop_extra = False
        self.images_cache = 25
        self.full_control = True
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
        self.lyrics_font = 190
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
        if self.session.closed: return False
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
            except Exception as e:
                if attempt < retries: await asyncio.sleep(0.2 * attempt)
        return False

    async def get_current_channel_index(self) -> int: 
        if self.session.closed: return 0
        try:
            async with self.session.post(self.config.pixoo_url, headers=self.headers, json={"Command": "Channel/GetIndex"}, timeout=5) as response:
                response_data = await response.json()
                return response_data.get('SelectIndex', 0)
        except Exception: return 0

class ImageProcessor:
    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.image_cache: OrderedDict[str, dict] = OrderedDict()
        self.cache_size: int = config.images_cache
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="PixooImageProc")

    def shutdown(self):
        self._executor.shutdown(wait=False)

    async def get_image(self, picture: Optional[str], media_data: "MediaData", spotify_slide: bool = False) -> Optional[dict]:
        if not picture: return None
        cache_key = f"{picture}_{media_data.artist}_{media_data.title}" if getattr(self.config, 'burned', False) else picture
        use_cache = not spotify_slide and not getattr(media_data, 'playing_tv', False)
        cached_data = None

        if use_cache and cache_key in self.image_cache:
            self.image_cache.move_to_end(cache_key)
            cached_data = self.image_cache[cache_key]
        else:
            try:
                if picture.startswith('http'): url = picture
                else:
                    try: base_url = get_url(media_data.hass)
                    except Exception: base_url = "http://127.0.0.1:8123"
                    url = f"{base_url}{picture}"

                async with self.session.get(url, timeout=30) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        cached_data = await self.process_image_data(image_data, media_data)
                        if cached_data and not spotify_slide:
                            if len(self.image_cache) >= self.cache_size: self.image_cache.popitem(last=False)
                            self.image_cache[cache_key] = cached_data
            except Exception as e:
                _LOGGER.error(f"Error fetching/processing image: {e}")
                return self._fallback_response()

        if not cached_data: return self._fallback_response()
        final_img = cached_data['pil_image'].copy()
        final_img = self.text_clock_img(final_img, cached_data, media_data)
        
        return {'base64_image': self.gbase64(final_img), **cached_data}

    async def process_image_data(self, image_data: bytes, media_data: "MediaData") -> Optional[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._process_image, image_data, media_data)

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

                if (self.config.crop_borders or self.config.special_mode) and not media_data.radio_logo:
                    img = self.crop_image_borders(img, media_data.radio_logo)

                img = self.fixed_size(img)
                if img.width > 64 or img.height > 64: img = img.resize((64, 64), Image.Resampling.BILINEAR)
                
                if self.config.burned and not media_data.radio_logo:
                    img = self._draw_burned_text(img, media_data.artist, media_data.title)
                
                if self.config.special_mode:
                    img = self.special_mode(img)

                vals = self.img_values(img)
                return {
                    'pil_image': img, 
                    'font_color': vals['font_color'], 
                    'brightness_lower_part': vals['brightness_lower_part'], 
                    'background_color_rgb': vals['background_color_rgb'],
                    'background_color': vals['background_color']
                }
        except Exception as e:
            return None

    def img_values(self, img: Image.Image) -> dict:
        analysis_img = img.resize((50, 50), Image.Resampling.NEAREST)
        palette = self.get_image_palette(analysis_img) 
        
        if self.config.text_bg:
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
        if self.config.force_font_color: return self.config.force_font_color
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

        if self.config.text_bg:
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
        album_size = (34, 34) if self.config.show_text else (56, 56)
        
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

    def _perform_border_crop(self, img_to_crop: Image.Image) -> Optional[Image.Image]:
        try:
            orig_w, orig_h = img_to_crop.size
            scale = 128 / max(orig_w, orig_h)
            proxy_w = int(orig_w * scale)
            proxy_h = int(orig_h * scale)
            proxy = img_to_crop.resize((proxy_w, proxy_h), Image.Resampling.BILINEAR)

            # Get dominant border color
            img_rgb = proxy if proxy.mode == "RGB" else proxy.convert("RGB")
            thumb = img_rgb.resize((64, 64), Image.Resampling.NEAREST)
            h_border = list(thumb.crop((0, 0, 64, 1)).getdata()) + list(thumb.crop((0, 63, 64, 64)).getdata())
            v_border = list(thumb.crop((0, 0, 1, 64)).getdata()) + list(thumb.crop((63, 0, 64, 64)).getdata())
            border_color = Counter(h_border + v_border).most_common(1)[0][0]

            # Find bounding box
            bg = Image.new("RGB", proxy.size, border_color)
            diff = ImageChops.difference(proxy, bg)
            diff = ImageOps.grayscale(diff).point(lambda p: 255 if p > 30 else 0)
            bbox = diff.getbbox()
            
            if not bbox: return img_to_crop 

            min_x, min_y, max_x, max_y = bbox
            crop_size = min(max_x - min_x, max_y - min_y)
            
            center_x = min_x + (max_x - min_x) // 2
            center_y = min_y + (max_y - min_y) // 2
            
            real_size = int(crop_size / scale)
            real_cx = int(center_x / scale)
            real_cy = int(center_y / scale)
            
            real_left = max(0, real_cx - (real_size // 2))
            real_top = max(0, real_cy - (real_size // 2))
            
            return img_to_crop.crop((real_left, real_top, real_left + real_size, real_top + real_size))
        except Exception:
            return img_to_crop

    def crop_image_borders(self, img: Image.Image, radio_logo: bool) -> Image.Image:
        if radio_logo or not self.config.crop_borders: return img
        return self._perform_border_crop(img) or img

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
        
        # Pick contrasting colors
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
        brightness_lower_part = cached_data.get('brightness_lower_part', 0.5)

        if media_data.lyrics and getattr(self.config, 'show_lyrics', False) and getattr(self.config, 'text_bg', False) and not getattr(media_data, 'playing_radio', False):
            img = ImageEnhance.Brightness(img).enhance(0.55)
            img = ImageEnhance.Contrast(img).enhance(0.5)

        if bool(self.config.show_clock and self.config.text_bg) and not self.config.show_lyrics:
            if self.config.top_text: lpc = (43, 55, 62, 62) if self.config.clock_align == "Right" else (2, 55, 21, 62)
            else: lpc = (43, 2, 62, 9) if self.config.clock_align == "Right" else (2, 2, 21, 9)
            lower_part_img = img.crop(lpc); lower_part_img = ImageEnhance.Brightness(lower_part_img).enhance(0.3); img.paste(lower_part_img, lpc)

        if bool(self.config.temperature and self.config.text_bg) and not self.config.show_lyrics:
            if self.config.top_text: lpc = (2, 55, 18, 62) if self.config.clock_align == "Right" else (47, 55, 63, 62)
            else: lpc = (2, 2, 18, 9) if self.config.clock_align == "Right" else (47, 2, 63, 9)
            lower_part_img = img.crop(lpc); lower_part_img = ImageEnhance.Brightness(lower_part_img).enhance(0.3); img.paste(lower_part_img, lpc)

        if self.config.text_bg and self.config.show_text and not self.config.show_lyrics and not getattr(media_data, 'playing_tv', False):
            if self.config.top_text: lpc = (0, 0, 64, 16)
            else: lpc = (0, 48, 64, 64)
            lower_part_img = img.crop(lpc); lower_part_img = ImageEnhance.Brightness(lower_part_img).enhance(brightness_lower_part); img.paste(lower_part_img, lpc)

        if getattr(media_data, 'show_progress_bar', False):
            y_bottom = getattr(self.config, 'progress_bar_y_offset', 64) - 1
            if y_bottom >= 63: y_bottom = 63
            y_top = y_bottom - 1 
            try:
                top_box = (0, y_top, 64, y_top + 1)
                top_area = ImageEnhance.Brightness(img.crop(top_box)).enhance(0.8)
                img.paste(top_area, top_box)
                bottom_box = (0, y_bottom, 64, y_bottom + 1)
                bottom_area = ImageEnhance.Brightness(img.crop(bottom_box)).enhance(0.5)
                img.paste(bottom_area, bottom_box)
            except Exception: pass
        return img

    def gbase64(self, img: Image.Image) -> Optional[str]:
        try:
            if img.mode != "RGB":
                img = img.convert("RGB")
            raw_data = img.tobytes()
            b64 = base64.b64encode(raw_data)
            return b64.decode("utf-8")
        except Exception as e:
            _LOGGER.error(f"Error converting image to base64: {e}")
            return None

    def _fallback_response(self) -> dict:
        img = Image.new("RGB", (64, 64), color=(0, 0, 0))
        return {
            "base64_image": self.gbase64(img),
            "font_color": "#FFFFFF", "brightness_lower_part": 0.5, "background_color_rgb": (0, 0, 0), "background_color": "#000000"
        }

    async def process_slide_image(self, image_data: bytes, show_lyrics_is_on: bool, playing_radio_is_on: bool) -> Optional[str]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                self._executor, 
                self._process_slide_image_sync, 
                image_data, show_lyrics_is_on, playing_radio_is_on
            )
        except Exception as e:
            return None

    def _process_slide_image_sync(self, image_data: bytes, show_lyrics_is_on: bool, playing_radio_is_on: bool) -> Optional[str]:
        try:
            with Image.open(BytesIO(image_data)) as img:
                img = ensure_rgb(img)
                img = self.fixed_size(img)
                img = img.resize((64, 64), Image.Resampling.BILINEAR)

                if self.config.special_mode:
                    img = self.special_mode(img)

                if show_lyrics_is_on and not playing_radio_is_on and not self.config.special_mode:
                    img = ImageEnhance.Brightness(img).enhance(0.55)
                    img = ImageEnhance.Contrast(img).enhance(0.5)

                return self.gbase64(img)
        except Exception as e:
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
        if not self.config.spotify_client_id or not self.config.spotify_client_secret: return None

        url = "https://accounts.spotify.com/api/token"
        auth_string = base64.b64encode(f"{self.config.spotify_client_id}:{self.config.spotify_client_secret}".encode()).decode()
        spotify_headers = {"Authorization": f"Basic {auth_string}", "Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with self.session.post(url, headers=spotify_headers, data={"grant_type": "client_credentials"}, timeout=10) as response: 
                response.raise_for_status() 
                response_json = await response.json()
                access_token = response_json["access_token"]
                self.spotify_token_cache = {'token': access_token, 'expires': time.time() + response_json.get("expires_in", 3600) - 60}
                return access_token
        except Exception: return None

    async def get_spotify_json(self, artist: str, title: str) -> Optional[dict]: 
        token = await self.get_spotify_access_token()
        if not token: return None
        url = "https://api.spotify.com/v1/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with self.session.get(url, headers=headers, params={"q": f"track: {title} artist: {artist}", "type": "track", "limit": 50}, timeout=10) as response: 
                return await response.json()
        except Exception: return None

    async def get_spotify_artist_image_url_by_name(self, artist_name: str) -> Optional[str]: 
        token = await self.get_spotify_access_token()
        if not token or not artist_name: return None
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with self.session.get("https://api.spotify.com/v1/search", headers=headers, params={"q": f"artist:{artist_name}", "type": "artist", "limit": 1}, timeout=10) as response: 
                data = await response.json()
                artists = data.get('artists', {}).get('items', [])
                if not artists: return None
                url = f"https://api.spotify.com/v1/artists/{artists[0]['id']}"
                async with self.session.get(url, headers=headers, timeout=10) as art_response:
                    art_data = await art_response.json()
                    images = art_data.get('images', [])
                    return images[0]['url'] if images else None
        except Exception: return None

    async def get_album_list(self, media_data: "MediaData", returntype: str) -> list[str]: 
        if not self.spotify_data or getattr(media_data, 'playing_tv', False): return []
        try:
            tracks = self.spotify_data.get('tracks', {}).get('items', [])
            albums = {} 
            for track in tracks:
                album = track.get('album', {})
                album_id = album.get('id')
                artists = album.get('artists', [])
                if any(artist.get('name', '').lower() == 'various artists' for artist in artists): continue
                if media_data.artist.lower() not in [artist.get('name', '').lower() for artist in artists]: continue
                if album_id not in albums: albums[album_id] = album

            sorted_albums = sorted(albums.values(), key=lambda x: (x.get("album_type") == "single", x.get("album_type") == "album"), reverse=True)[:10]
            album_urls = [album.get("images", [])[0]["url"] for album in sorted_albums if album.get("images")]
            media_data.pic_url = album_urls
            media_data.pic_source = "Spotify (Slide)"
            return album_urls
        except Exception: return []

    async def get_slide_img(self, picture: str, show_lyrics_is_on: bool, playing_radio_is_on: bool) -> Optional[str]: 
        try:
            async with self.session.get(picture, timeout=10) as response: 
                image_raw_data = await response.read()
            return await self.image_processor.process_slide_image(image_raw_data, show_lyrics_is_on, playing_radio_is_on)
        except Exception: return None

    async def send_pixoo_animation_frame(self, pixoo_device: "PixooDevice", command: str, pic_num: int, pic_width: int, pic_offset: int, pic_id: int, pic_speed: int, pic_data: str) -> None: 
        await pixoo_device.send_command({"Command": command, "PicNum": pic_num, "PicWidth": pic_width, "PicOffset": pic_offset, "PicID": pic_id, "PicSpeed": pic_speed, "PicData": pic_data})

    async def spotify_albums_slide(self, pixoo_device: "PixooDevice", media_data: "MediaData", prev_channel: int) -> None: 
        media_data.spotify_slide_pass = True
        try:
            artist_pic_url = await self.get_spotify_artist_image_url_by_name(media_data.artist)
            if artist_pic_url:
                preview_b64 = await self.get_slide_img(artist_pic_url, bool(media_data.lyrics), getattr(media_data, 'playing_radio', False))
                if preview_b64:
                    await pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [
                        {"Command": "Draw/ResetHttpGifId"},
                        {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 1000, "PicData": preview_b64}
                    ]})

            album_urls = await self.get_album_list(media_data, returntype="url")
            if not album_urls: return

            async def process_pipeline(url):
                async with self._semaphore:
                    try:
                        async with self.session.get(url, timeout=10) as response:
                            raw_data = await response.read()
                            return await self.image_processor.process_slide_image(raw_data, bool(media_data.lyrics), getattr(media_data, 'playing_radio', False))
                    except: return None

            tasks = [process_pipeline(url) for url in album_urls[:10]]
            album_urls_b64 = await asyncio.gather(*tasks)
            album_urls_b64 = [res for res in album_urls_b64 if res]

            frames = len(album_urls_b64)
            if frames < 2: return

            await pixoo_device.send_command({"Command": "Draw/CommandList", "Command": "Draw/ResetHttpGifId"})
            for pic_offset, b64_frame in enumerate(album_urls_b64):
                await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", frames, 64, pic_offset, 0, 5000, b64_frame)
        except Exception: pass

    async def spotify_album_art_animation(self, pixoo_device: "PixooDevice", media_data: "MediaData", prev_channel: int) -> None: 
        if getattr(media_data, 'playing_tv', False): return 
        try:
            artist_img = None
            artist_pic_url = await self.get_spotify_artist_image_url_by_name(media_data.artist)
            if artist_pic_url:
                async with self.session.get(artist_pic_url, timeout=5) as response:
                    raw_data = await response.read()
                    loop = asyncio.get_event_loop()
                    artist_img = await loop.run_in_executor(self.image_processor._executor, _resize_image_sync, raw_data)
                    if artist_img:
                        preview_canvas = Image.new("RGB", (64, 64), (0, 0, 0))
                        preview_canvas.paste(artist_img, (16, 8)) 
                        preview_b64 = self.image_processor.gbase64(preview_canvas)
                        await pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [
                            {"Command": "Draw/ResetHttpGifId"},
                            {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 1000, "PicData": preview_b64}
                        ]})

            album_urls = await self.get_album_list(media_data, returntype="url")
            if not album_urls: return

            def prepare_album_variants(raw_data):
                try:
                    img = Image.open(BytesIO(raw_data)).convert("RGB").resize((34, 34), Image.Resampling.BILINEAR)
                    active = img.copy()
                    ImageDraw.Draw(active).rectangle([0, 0, 33, 33], outline="black", width=1)
                    inactive = ImageEnhance.Brightness(img.filter(ImageFilter.GaussianBlur(2))).enhance(0.5)
                    return {"active": active, "inactive": inactive}
                except: return None

            async def download(url):
                try:
                    async with self.session.get(url, timeout=10) as resp: return await resp.read()
                except: return None

            raw_datas = await asyncio.gather(*[download(u) for u in album_urls[:10]])
            raw_datas = [d for d in raw_datas if d]

            loop = asyncio.get_event_loop()
            tasks = [loop.run_in_executor(self.image_processor._executor, prepare_album_variants, d) for d in raw_datas]
            prepared_albums = await asyncio.gather(*tasks)
            prepared_albums = [a for a in prepared_albums if a]

            if artist_img:
                a_img = artist_img.copy()
                ImageDraw.Draw(a_img).rectangle([0,0,33,33], outline="black", width=1)
                i_img = ImageEnhance.Brightness(artist_img.filter(ImageFilter.GaussianBlur(2))).enhance(0.5)
                prepared_albums.insert(0, {"active": a_img, "inactive": i_img})

            if len(prepared_albums) < 3: return

            total_frames = min(len(prepared_albums), 10)
            pixoo_frames = []
            x_pos = [1, 16, 51]

            for i in range(total_frames):
                canvas = Image.new("RGB", (64, 64), (0, 0, 0))
                l, c, r = (i-1)%len(prepared_albums), i%len(prepared_albums), (i+1)%len(prepared_albums)
                canvas.paste(prepared_albums[l]["inactive"], (x_pos[0], 8))
                canvas.paste(prepared_albums[c]["active"], (x_pos[1], 8))
                canvas.paste(prepared_albums[r]["inactive"], (x_pos[2], 8))
                pixoo_frames.append(self.image_processor.gbase64(canvas))

            for offset, frame in enumerate(pixoo_frames):
                await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", total_frames, 64, offset, 0, 5000, frame)
            
            media_data.spotify_slide_pass = True 
        except Exception: pass

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
        try:
            async with self.session.get(base_url_get, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('syncedLyrics'):
                        fetched_lyrics = self._parse_lrc(data['syncedLyrics'])
        except Exception: pass

        if not fetched_lyrics:
            try:
                base_url_search = "https://lrclib.net/api/search"
                search_params = {'q': f"{artist} {title}"}
                async with self.session.get(base_url_search, params=search_params, timeout=10) as response:
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

class MediaData:
    def __init__(self, hass: HomeAssistant, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession):
        self.hass = hass
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.lyrics_provider = LyricsProvider(self.config, self.session)
        self.prev_title = ""
        self.prev_artist = ""
        self.track_changed = False 
        self.artist = ""
        self.title = ""
        self.album = None
        self.lyrics = []
        self.picture = None
        self.lyrics_font_color = "#FFA000"
        self.show_progress_bar = False
        self.playing_tv = False
        self.playing_radio = False
        self.radio_logo = False
        self.pic_source = None
        self.pic_url = None
        self.media_position = 0
        self.media_duration = 0
        self.media_position_updated_at = None
        
        self._clean_title_patterns = [
            re.compile(r'[\(\[][^)\]]*remaster(?:ed)?[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*remix(?:ed)?[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*version[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*feat.[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'[\(\[][^)\]]*live[^)\]]*[\)\]]', re.IGNORECASE),
            re.compile(r'^\d+\s*[\.-]\s*', re.IGNORECASE),
            re.compile(r'\.(mp3|m4a|wav|flac)$', re.IGNORECASE)
        ]

    def clean_title(self, title: str) -> str: 
        if not title: return title
        for pattern in self._clean_title_patterns: title = pattern.sub('', title)
        return ' '.join(title.split())

    async def update(self) -> Optional["MediaData"]:
        try:
            media_state_obj = self.hass.states.get(self.config.media_player)
            if not media_state_obj or media_state_obj.state not in ["playing", "on"]: return None

            attributes = media_state_obj.attributes
            raw_title = attributes.get('media_title')
            raw_artist = attributes.get('media_artist')
            app_name = attributes.get('app_name')

            if raw_title is None or str(raw_title).strip() == "":
                if app_name and str(app_name).strip() != "": raw_title = app_name
                else: return None

            if (raw_artist is None or str(raw_artist).strip() == "") and app_name: raw_artist = app_name

            self.title = self.clean_title(raw_title) if self.config.clean_title else raw_title
            self.artist = raw_artist if raw_artist else ""
            self.album = attributes.get('album_name') or attributes.get('media_album_name') or ""
            
            original_picture = attributes.get('entity_picture')
            if original_picture and (re.match(r'^[a-zA-Z]:\\', original_picture) or original_picture.startswith("file://")): original_picture = None
            self.picture = original_picture
            
            try:
                self.media_position = float(attributes.get('media_position', 0))
                self.media_duration = float(attributes.get('media_duration', 0))
            except (ValueError, TypeError): pass

            if self.config.progress_bar_enabled: self.show_progress_bar = True if self.media_duration > 0 else False
            else: self.show_progress_bar = False

            pos_updated_at_str = attributes.get('media_position_updated_at')
            if isinstance(pos_updated_at_str, datetime): self.media_position_updated_at = pos_updated_at_str
            elif pos_updated_at_str: self.media_position_updated_at = datetime.fromisoformat(pos_updated_at_str.replace('Z', '+00:00'))
            else: self.media_position_updated_at = None

            self.playing_tv = "netflix" in str(app_name).lower() or "youtube" in str(app_name).lower() or raw_title == "TV"
            
            media_content_id = attributes.get('media_content_id')
            media_channel = attributes.get('media_channel')
            if media_channel and (media_content_id and (media_content_id.startswith("x-rincon") or media_content_id.startswith("aac://http") or media_content_id.startswith("rtsp://"))): 
                self.playing_radio = True
                self.radio_logo = ('https://tunein' in str(media_content_id) or raw_title == media_channel or raw_title == raw_artist or raw_artist == media_channel or raw_artist == 'Live' or raw_artist is None)
            else:
                self.playing_radio, self.radio_logo = False, False

            if getattr(self.config, 'show_lyrics', False) and not getattr(self.config, 'special_mode', False) and not self.playing_tv and not self.playing_radio:
                self.lyrics = await self.lyrics_provider.get_lyrics(self.artist, raw_title, self.album, self.media_duration)
            else:
                self.lyrics = []

            self.track_changed = (self.title != self.prev_title or self.artist != self.prev_artist)
            self.prev_title, self.prev_artist = self.title, self.artist
            return self
        except Exception as e: return None

    def format_ai_image_prompt(self, artist: Optional[str], title: str) -> Optional[str]: 
        if not self.config.pollinations: return None
        artist_name = artist if artist else 'Pixoo64' 
        clean_artist = artist_name.replace("/", "-").replace("\\", "-")
        clean_title = title.replace("/", "-").replace("\\", "-")
        prompts = [
            f"Double exposure album cover blending the face of {clean_artist} with a silhouette scene representing '{clean_title}', high contrast, surreal art",
            f"Surreal portrait of {clean_artist} where their mind is opening up to reveal '{clean_title}', vibrant colors, dali-esque dreamscape, digital art",
            f"Pop art portrait of {clean_artist} surrounded by floating icons and symbols of '{clean_title}', Andy Warhol style, bold colors, thick lines",
            f"A moody portrait of {clean_artist}, surrounded by a weather and atmosphere that matches the song '{clean_title}', cinematic lighting, emotional"
        ]
        encoded_prompt = urllib.parse.quote(random.choice(prompts), safe='')
        url_params = f"?model={self.config.ai_fallback}&width=1024&height=1024&seed={random.randint(1, 2147483647)}"
        if len(self.config.pollinations) > 5: url_params += f"&key={self.config.pollinations.strip()}"
        return f"https://gen.pollinations.ai/image/{encoded_prompt}{url_params}"

class FallbackService:
    def __init__(self, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession, spotify_service: "SpotifyService", pixoo_device: "PixooDevice"): 
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.spotify_service = spotify_service
        self.pixoo_device = pixoo_device 

    async def get_final_url(self, picture: Optional[str], media_data: "MediaData") -> Optional[dict]: 
        if self.config.force_ai and not getattr(media_data, 'radio_logo', False) and not getattr(media_data, 'playing_tv', False):
            return await self._try_ai_generation(media_data)

        if picture == "TV_IS_ON_ICON":
            media_data.pic_source = "Internal"
            tv_img = Image.new("RGB", (64, 64), (0, 0, 0)) # Placeholder for TV Icon
            return {'base64_image': self.image_processor.gbase64(tv_img), 'font_color': '#ff00ff', 'background_color': '#000000'}

        try:
            if picture and not (getattr(media_data, 'playing_radio', False) and not media_data.radio_logo):
                result = await self.image_processor.get_image(picture, media_data, False)
                if result:
                    media_data.pic_source = "Original"
                    media_data.pic_url = picture
                    return result
        except Exception: pass 
        
        # Fallback chain
        tasks = []
        providers = []
        if self.config.discogs: tasks.append(self._search_discogs(media_data.artist, media_data.title)); providers.append("Discogs")
        if self.config.lastfm: tasks.append(self._search_lastfm(media_data.artist, media_data.title)); providers.append("Last.FM")
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) or not result: continue
                proc_result = await self.image_processor.get_image(result, media_data, False)
                if proc_result:
                    media_data.pic_url = result
                    media_data.pic_source = providers[i]
                    return proc_result

        result = await self._try_ai_generation(media_data)
        if result: 
            media_data.pic_source = "AI"
            return result

        media_data.pic_source = "Internal"
        return self._get_fallback_black_image_data()

    async def _search_discogs(self, artist, title):
        try:
            headers = {"Authorization": f"Discogs token={self.config.discogs}"}
            async with self.session.get("https://api.discogs.com/database/search", headers=headers, params={"artist": artist, "track": title, "type": "release", "per_page": 1}, timeout=10) as response:
                return (await response.json()).get("results", [])[0].get("cover_image")
        except: return None

    async def _search_lastfm(self, artist, title):
        try:
            async with self.session.get("http://ws.audioscrobbler.com/2.0/", params={"method": "track.getInfo", "api_key": self.config.lastfm, "artist": artist, "track": title, "format": "json"}, timeout=10) as response:
                images = (await response.json()).get("track", {}).get("album", {}).get("image", [])
                return images[-1]["#text"] if images else None
        except: return None

    async def _try_ai_generation(self, media_data):
        ai_url = media_data.format_ai_image_prompt(media_data.artist, media_data.title)
        if not ai_url: return None
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(self.image_processor.get_image(ai_url, media_data, False), timeout=15)
                if result: 
                    media_data.pic_url = ai_url
                    return result
            except Exception:
                if attempt < 1: await asyncio.sleep(1.5)
        return None

    def _get_fallback_black_image_data(self) -> dict: 
        img = Image.new("RGB", (64, 64), color=(0, 0, 0))
        return {"base64_image": self.image_processor.gbase64(img), "font_color": "#FFFFFF", "background_color": "#000000"}

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
    def __init__(self, config: "Config", pixoo: "PixooDevice", image_processor: "ImageProcessor", hass: HomeAssistant):
        self.config = config
        self.pixoo = pixoo
        self.is_active = False

    async def display(self, event_data: dict):
        self.is_active = True
        try:
            message, duration = event_data.get("message", ""), int(event_data.get("duration", 5))
            if not message: return
            lines = textwrap.wrap(message, width=12)[:4]
            text_items = [{"TextId": 25 + i, "type": 22, "x": 0, "y": 20 + (i * 10), "dir": 1 if has_bidi(line) else 0, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(line) if has_bidi(line) else line, "color": "#FFFFFF"} for i, line in enumerate(lines)]
            
            await self.pixoo.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Channel/OnOffScreen", "OnOff": 1}, {"Command": "Draw/ClearHttpText"}, {"Command": "Draw/ResetHttpGifId"}]})
            await asyncio.sleep(0.1)
            await self.pixoo.send_command({"Command": "Draw/SendHttpItemList", "ItemList": text_items})
            await asyncio.sleep(duration)
        except Exception: pass
        finally: self.is_active = False
