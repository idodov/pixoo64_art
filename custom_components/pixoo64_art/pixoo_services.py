"""
Core Services for Pixoo64 Media Album Art
Contains all business logic, image processing, API calls, and managers.
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
SYRIAC = r"\u0700-\u074F"
THAANA = r"\u0780-\u07BF"
NKOO = r"\u07C0-\u07FF"
RUMI = r"\U00010E60-\U00010E7F"
ARABIC_MATH = r"\U0001EE00-\U0001EEFF"
SYMBOLS = r"\U0001F110-\U0001F5FF"
OLD_PERSIAN_PHAISTOS = r"\U00010F00-\U00010FFF"
SAMARITAN = r"\u0800-\u08FF"

BIDI_REGEX_PATTERN = f"[{HEBREW}|{ARABIC}|{SYRIAC}|{THAANA}|{NKOO}|{RUMI}|{ARABIC_MATH}|{SYMBOLS}|{OLD_PERSIAN_PHAISTOS}|{SAMARITAN}]"
BIDI_REGEX = re.compile(BIDI_REGEX_PATTERN)

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

class Config:
    def __init__(self, entry):
        data = entry.data
        options = entry.options
        
        self.args = {**data, **options}

        self.media_player = data.get("media_player", "media_player.living_room")
        self.pixoo_ip = data.get("pixoo_ip")
        self.pixoo_url = f"http://{self.pixoo_ip}:80/post"
        self.ha_url = options.get("ha_url", "http://homeassistant.local:8123")
        
        self.pollinations = options.get("pollinations_key", "")
        self.ai_fallback = options.get("ai_model", "flux")
        self.spotify_client_id = options.get("spotify_client_id", "")
        self.spotify_client_secret = options.get("spotify_client_secret", "")
        self.musicbrainz = options.get("musicbrainz_enabled", True)
        self.tidal_client_id = options.get("tidal_client_id", "")
        self.tidal_client_secret = options.get("tidal_client_secret", "")
        self.lastfm = options.get("lastfm", "")
        self.discogs = options.get("discogs", "")

        self.light = options.get("light", None)
        self.wled = options.get("wled_ip", None)
        self.brightness = 255
        self.effect = 38
        self.effect_speed = 60
        self.effect_intensity = 128
        self.only_at_night = True
        self.palette = 0
        self.sound_effect = 0

        self.show_text = options.get("show_text", False)
        self.clean_title = True
        self.text_bg = options.get("text_background", True)
        self.top_text = options.get("top_text", True)
        self.special_mode_spotify_slider = False
        self.force_font_color = None
        self.burned = False
        
        self.crop_borders = options.get("crop_borders", True)
        self.crop_extra = options.get("crop_extra", True)
        
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
        self.lyrics_sync = -1 

        self.progress_bar_enabled = options.get("progress_bar_enabled", True)
        self.progress_bar_entity = "input_boolean.pixoo64_progress_bar"
        self.progress_bar_character = "-"
        self.progress_bar_font = 190
        self.progress_bar_resolution = 21
        self.progress_bar_color = "match"
        self.progress_bar_y_offset = 64
        self.progress_bar_exclude_modes = []
        self.temperature_sensor = options.get("temperature_entity", None)
        self.force_ai = False

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
        if not picture:
            return None

        cache_key = f"{picture}_{media_data.artist}_{media_data.title}" if getattr(self.config, 'burned', False) else picture
        use_cache = not spotify_slide and not getattr(media_data, 'playing_tv', False)
        cached_data = None

        if use_cache and cache_key in self.image_cache:
            self.image_cache.move_to_end(cache_key)
            cached_data = self.image_cache[cache_key]
        else:
            try:
                # התיקון הקריטי: משיכת הכתובת הפנימית האמיתית של השרת
                from homeassistant.helpers.network import get_url
                if picture.startswith('http'):
                    url = picture
                else:
                    try:
                        base_url = get_url(media_data.hass)
                    except Exception:
                        base_url = "http://127.0.0.1:8123"
                    url = f"{base_url}{picture}"

                async with self.session.get(url, timeout=30) as response:
                    response.raise_for_status()
                    image_data = await response.read()
                    cached_data = await self.process_image_data(image_data, media_data)
                    
                    if cached_data and not spotify_slide:
                        if len(self.image_cache) >= self.cache_size:
                            self.image_cache.popitem(last=False)
                        self.image_cache[cache_key] = cached_data
            except Exception as e:
                _LOGGER.error(f"Error fetching/processing image: {e}")
                return self._fallback_response()

        if not cached_data: return self._fallback_response()

        final_img = cached_data['pil_image'].copy()
        final_img = self.text_clock_img(final_img, cached_data, media_data)
        
        return {
            'base64_image': self.gbase64(final_img),
            **cached_data 
        }

    def _fallback_response(self) -> dict:
        # יצירת מסך שחור וגיבוי בפורמט גולמי תקין
        img = Image.new("RGB", (64, 64), color=(0, 0, 0))
        return {
            "base64_image": self.gbase64(img),
            "font_color": "#FFFFFF",
            "clock_color": "#FFFFFF",
            "temp_color": "#FFFFFF",
            "brightness": 0,
            "brightness_lower_part": 0.5,
            "background_color_rgb": (0, 0, 0),
            "color1": "#000000",
            "color2": "#000000",
            "color3": "#000000"
        }

    def gbase64(self, img: Image.Image) -> Optional[str]:
        try:
            # חובה לוודא שהתמונה בפורמט RGB לפני ההמרה כדי למנוע קריסת נתונים
            if img.mode != "RGB":
                img = img.convert("RGB")
            raw_data = img.tobytes()
            b64 = base64.b64encode(raw_data)
            return b64.decode("utf-8")
        except Exception as e:
            _LOGGER.error(f"Error converting image to base64: {e}")
            return None

    async def process_image_data(self, image_data: bytes, media_data: "MediaData") -> Optional[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._process_image, image_data, media_data)

    def _process_image(self, image_data: bytes, media_data: "MediaData") -> Optional[dict]:
        try:
            with Image.open(BytesIO(image_data)) as img:
                img.load() 
                img = ensure_rgb(img)
                max_dimension = 320
                if max(img.size) > max_dimension:
                    scale_factor = max_dimension / max(img.size)
                    img = img.resize((int(img.width * scale_factor), int(img.height * scale_factor)), Image.Resampling.BILINEAR)

                if (self.config.crop_borders or self.config.special_mode) and not media_data.radio_logo:
                    img = self.crop_image_borders(img, media_data.radio_logo)

                img = self.fixed_size(img)
                if img.width > 64 or img.height > 64: img = img.resize((64, 64), Image.Resampling.BILINEAR)
                if self.config.contrast or self.config.sharpness or self.config.colors or self.config.kernel or self.config.limit_color:
                    img = self.filter_image(img)
                if self.config.burned and not media_data.radio_logo:
                    img = self._draw_burned_text(img, media_data.artist, media_data.title_clean)
                if self.config.special_mode: img = self.special_mode(img)
                
                vals = self.img_values(img)
                if self.config.force_font_color: media_data.lyrics_font_color = self.config.force_font_color
                elif vals.get('font_color'): media_data.lyrics_font_color = vals['font_color']
                else: media_data.lyrics_font_color = "#FF00FF"

                return {'pil_image': img, 'font_color': vals['font_color'], 'brightness_lower_part': vals['brightness_lower_part'], 'background_color_rgb': vals['background_color_rgb']}
        except Exception as e:
            return None

    def img_values(self, img: Image.Image) -> dict:
        analysis_img = img.resize((50, 50), Image.Resampling.NEAREST)
        palette = self.get_image_palette(analysis_img) 
        text_box = (0, 0, 64, 16) if self.config.top_text else (0, 48, 64, 64)
        
        if self.config.text_bg:
             prime_color = palette[0] if palette else (255, 255, 0)
             h, s, v = colorsys.rgb_to_hsv(prime_color[0]/255, prime_color[1]/255, prime_color[2]/255)
             r, g, b = colorsys.hsv_to_rgb(h, max(0.5, s), 1.0)
             hex_color = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
             most_common_color_alternative_rgb = prime_color
        else:
             most_common_color_alternative_rgb = palette[0] if palette else (0,0,0)

        brightness = int(sum(most_common_color_alternative_rgb) / 3)
        brightness_lower_part = round(1 - brightness / 255, 2) if 0 <= brightness <= 255 else 0
        font_color = self.get_optimal_font_color(analysis_img)

        return {'font_color': font_color, 'brightness_lower_part': brightness_lower_part, 'background_color_rgb': most_common_color_alternative_rgb}

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

    def crop_image_borders(self, img: Image.Image, radio_logo: bool) -> Image.Image: return img
    def _draw_burned_text(self, img: Image.Image, artist: str, title: str) -> Image.Image: return img
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

    def filter_image(self, img: Image.Image) -> Image.Image:
        if self.config.colors: img = ImageEnhance.Color(img).enhance(1.5)
        if self.config.contrast: img = ImageEnhance.Contrast(img).enhance(1.5)
        if self.config.sharpness: img = ImageEnhance.Sharpness(img).enhance(4.0)
        return img

    def special_mode(self, img: Image.Image) -> Image.Image: return img

    def text_clock_img(self, img: Image.Image, cached_data: dict, media_data: "MediaData") -> Image.Image:
        if getattr(self.config, 'burned', False):
            img = ImageEnhance.Color(img).enhance(1.5)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            img = ImageEnhance.Brightness(img).enhance(0.7)
            
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

        if self.config.text_bg and self.config.show_text and not self.config.show_lyrics and not media_data.playing_tv:
            if self.config.top_text: lpc = (0, 0, 64, 16)
            else: lpc = (0, 48, 64, 64)
            lower_part_img = img.crop(lpc); lower_part_img = ImageEnhance.Brightness(lower_part_img).enhance(brightness_lower_part); img.paste(lower_part_img, lpc)

        if getattr(media_data, 'show_progress_bar', False):
            y_bottom = self.config.progress_bar_y_offset - 1
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

class SpotifyService:
    def __init__(self, config: "Config", session: aiohttp.ClientSession, image_processor: "ImageProcessor"): 
        self.config = config
        self.session = session
        self.image_processor = image_processor
    async def get_spotify_album_id(self, media_data: "MediaData") -> tuple[Optional[str], Optional[str]]: return None, None
    async def get_spotify_album_image_url(self, album_id: str) -> Optional[str]: return None

class LyricsProvider:
    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session 
        self.lyrics_cache: OrderedDict[str, list] = OrderedDict()
        self.visual_timeline: list[dict] = [] 
        self.current_song_key: Optional[str] = None
        self.current_frame_index: int = -1  

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
        if album: params['album_name'] = album
        if duration: params['duration'] = str(int(duration))

        try:
            async with self.session.get(base_url_get, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('syncedLyrics'):
                        fetched_lyrics = self._parse_lrc(data['syncedLyrics'])
        except Exception: pass

        if len(self.lyrics_cache) >= 100: self.lyrics_cache.popitem(last=False)
        self.lyrics_cache[new_key] = fetched_lyrics
        self._build_visual_timeline(fetched_lyrics)
        return fetched_lyrics

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
        parsed.sort(key=lambda x: x['seconds'])
        return parsed

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

            self.visual_timeline.append({
                'start': start_time, 'end': end_time,
                'layout': [{'y': 20, 'h': 12, 'dir': 0, 'text': text[:20]}]
            })

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
        for frame in self.visual_timeline:
            if frame['start'] > current_pos: return [], max(0.1, frame['start'] - current_pos)
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
        self.title_original = ""
        self.album = None
        self.lyrics = []
        self.picture = None
        self.lyrics_font_color = "#FFA000"
        self.show_progress_bar = False
        self.playing_tv = False
        self.playing_radio = False
        self.radio_logo = False
        self.pic_source = None
        self.media_position = 0
        self.media_duration = 0
        self.media_position_updated_at = None

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

            self.title_original = raw_title
            self.title_clean = raw_title
            self.title = self.title_clean
            self.artist = raw_artist if raw_artist else ""
            self.album = attributes.get('album_name') or attributes.get('media_album_name') or ""
            self.picture = attributes.get('entity_picture')
            
            try:
                self.media_position = float(attributes.get('media_position', 0))
                self.media_duration = float(attributes.get('media_duration', 0))
            except (ValueError, TypeError): pass

            if self.config.progress_bar_enabled:
                pb_state = self.hass.states.get(self.config.progress_bar_entity)
                is_toggled_on = True if pb_state is None else str(pb_state.state).lower() in ['on', 'true']
                self.show_progress_bar = is_toggled_on and self.media_duration > 0
            else: self.show_progress_bar = False

            pos_updated_at_str = attributes.get('media_position_updated_at')
            if isinstance(pos_updated_at_str, datetime): self.media_position_updated_at = pos_updated_at_str
            elif pos_updated_at_str: self.media_position_updated_at = datetime.fromisoformat(pos_updated_at_str.replace('Z', '+00:00'))
            else: self.media_position_updated_at = None

            self.playing_tv = "netflix" in str(app_name).lower() or "youtube" in str(app_name).lower()

            if getattr(self.config, 'show_lyrics', False) and not getattr(self.config, 'special_mode', False) and not self.playing_tv:
                self.lyrics = await self.lyrics_provider.get_lyrics(self.artist, self.title_original, self.album, self.media_duration)
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
        encoded_prompt = urllib.parse.quote(f"Square album cover for '{clean_title}' by {clean_artist}, vibrant colors, sharp focus, 8k", safe='')
        url_params = f"?model={self.config.ai_fallback}&width=1024&height=1024&seed={random.randint(1, 2147483647)}"
        if self.config.pollinations and len(self.config.pollinations) > 5: url_params += f"&key={self.config.pollinations.strip()}"
        return f"https://gen.pollinations.ai/image/{encoded_prompt}{url_params}"

class FallbackService:
    def __init__(self, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession, spotify_service: "SpotifyService", pixoo_device: "PixooDevice"): 
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.spotify_service = spotify_service
        self.pixoo_device = pixoo_device 

    async def get_final_url(self, picture: Optional[str], media_data: "MediaData") -> Optional[dict]: 
        if self.config.force_ai and not media_data.radio_logo and not media_data.playing_tv:
            return await self._try_ai_generation(media_data)

        try:
            if not media_data.playing_radio or media_data.radio_logo:
                result = await self.image_processor.get_image(picture, media_data, False)
                if result:
                    media_data.pic_source = "Original"
                    return result
        except Exception: pass 

        if self.config.spotify_client_id and self.config.spotify_client_secret:
            try:
                album_id, _ = await self.spotify_service.get_spotify_album_id(media_data)
                if album_id:
                    image_url = await self.spotify_service.get_spotify_album_image_url(album_id)
                    if image_url:
                        result = await self.image_processor.get_image(image_url, media_data, False)
                        if result:
                            media_data.pic_source = "Spotify"
                            return result
            except Exception: pass 
        
        result = await self._try_ai_generation(media_data)
        if result: 
            media_data.pic_source = "AI"
            return result

        media_data.pic_source = "Internal"
        return self._get_fallback_black_image_data() 

    async def _try_ai_generation(self, media_data):
        ai_url = media_data.format_ai_image_prompt(media_data.artist, media_data.title)
        if not ai_url: return None
        for attempt in range(3):
            try:
                result = await asyncio.wait_for(self.image_processor.get_image(ai_url, media_data, False), timeout=25)
                if result: return result
            except Exception:
                if attempt < 2: await asyncio.sleep(1.5)
        return None

    def _get_fallback_black_image_data(self) -> dict: 
        return self.image_processor._fallback_response()

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
        color = media_data.lyrics_font_color if self.config.progress_bar_color == 'match' else self.config.progress_bar_color
        
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
            text_items = [{"TextId": 25 + i, "type": 22, "x": 0, "y": 20 + (i * 10), "dir": 0, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": line, "color": "#FFFFFF"} for i, line in enumerate(lines)]
            await self.pixoo.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Channel/OnOffScreen", "OnOff": 1}, {"Command": "Draw/ClearHttpText"}]})
            await self.pixoo.send_command({"Command": "Draw/SendHttpItemList", "ItemList": text_items})
            await asyncio.sleep(duration)
        except Exception: pass
        finally: self.is_active = False
