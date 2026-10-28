"""Core image processor, caching, base64 encoder, and Lovelace GIF saver."""
import base64
from collections import OrderedDict
from io import BytesIO
import logging
import os
import re
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
import aiohttp
from homeassistant.core import HomeAssistant
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from ..models import ensure_rgb
from .color import ColorAnalyzer
from .cropper import ImageCropper
from .filters import ImageFilterService

if TYPE_CHECKING:
    from ..models import Config, MediaData
    from ..storage.manager import PixooStorageManager

_LOGGER = logging.getLogger(__name__)


class ImageProcessor:
    """Processes, crops, filters, and encodes artwork for Pixoo64."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: "Config",
        session: aiohttp.ClientSession,
        storage_manager: Optional["PixooStorageManager"] = None,
    ):
        self.hass = hass
        self.config = config
        self.session = session
        self.storage_manager = storage_manager
        self.cache_size = 40
        self.image_cache: OrderedDict = OrderedDict()
        self.raw_image_cache: OrderedDict = OrderedDict()
        self.color_analyzer = ColorAnalyzer(config)
        self.cropper = ImageCropper()
        self.filter_service = ImageFilterService()
        self._font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._gif_lock = threading.Lock()

    async def get_raw_image_data(self, url: str) -> Optional[bytes]:
        if not url or not isinstance(url, str):
            return None
        is_tokenless = "/api/media_player_proxy/" in url and "token=" not in url
        if not is_tokenless and url in self.raw_image_cache:
            self.raw_image_cache.move_to_end(url)
            return self.raw_image_cache[url]

        # 1. Direct in-memory extraction for media_player_proxy
        if "/api/media_player_proxy/" in url:
            try:
                raw_part = url.split("/api/media_player_proxy/")[1].split("?")[0].strip("/")
                target_ids = [raw_part] if raw_part else []
                cfg_player = getattr(self.config, "media_player", None)
                if cfg_player and cfg_player not in target_ids:
                    target_ids.append(cfg_player)

                comp = self.hass.data.get("media_player") or self.hass.data.get("entity_components", {}).get("media_player")
                entity = None
                if comp and hasattr(comp, "get_entity"):
                    for eid in target_ids:
                        entity = comp.get_entity(eid)
                        if entity:
                            break
                if not entity:
                    for val in list(self.hass.data.values()):
                        if hasattr(val, "get_entity"):
                            for eid in target_ids:
                                entity = val.get_entity(eid)
                                if entity:
                                    break
                        if entity:
                            break

                if entity and hasattr(entity, "async_get_media_image"):
                    img_tuple = await entity.async_get_media_image()
                    if img_tuple and img_tuple[0]:
                        data = img_tuple[0]
                        if not is_tokenless:
                            self.raw_image_cache[url] = data
                            if len(self.raw_image_cache) > self.cache_size:
                                self.raw_image_cache.popitem(last=False)
                        return data
            except Exception as ex:
                _LOGGER.debug("Direct in-memory proxy fetch note: %s", ex)

        # 2. Candidate URLs for internal/proxy routes
        urls_to_try = []
        is_relative = url.startswith("/")
        if is_relative:
            base_url = None
            try:
                from homeassistant.helpers.network import get_url
                base_url = get_url(self.hass, allow_internal=True)
            except Exception:
                pass
            if not base_url:
                base_url = getattr(self.hass.config, "internal_url", None) or getattr(self.hass.config, "external_url", None)
            if base_url:
                cand = f"{base_url.rstrip('/')}{url}"
                if cand not in urls_to_try:
                    urls_to_try.append(cand)
            port = getattr(getattr(self.hass.config, "api", None), "port", 8123) or 8123
            urls_to_try.append(f"http://127.0.0.1:{port}{url}")
            urls_to_try.append(f"https://127.0.0.1:{port}{url}")
        else:
            urls_to_try.append(url)

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        is_internal = is_relative or "/api/media_player_proxy/" in url or "127.0.0.1" in url
        timeout_sec = 20 if "pollinations.ai" in url else (2 if is_internal else 8)

        for target_url in urls_to_try:
            try:
                async with self.session.get(target_url, headers=headers, timeout=timeout_sec, ssl=False) as response:
                    if response.status == 200:
                        data = await response.read()
                        if data:
                            if not is_tokenless:
                                self.raw_image_cache[url] = data
                                if len(self.raw_image_cache) > self.cache_size:
                                    self.raw_image_cache.popitem(last=False)
                            return data
                    elif not is_relative:
                        _LOGGER.warning("HTTP %s when fetching image: %s", response.status, target_url)
            except Exception as e:
                if not is_relative:
                    _LOGGER.warning("Exception fetching image from %s: %s", target_url, e)
                else:
                    _LOGGER.debug("Candidate %s failed: %s", target_url, e)
        return None

    async def async_prefetch_url(self, url: str, media_data: "MediaData") -> None:
        if not url:
            return
        await self.get_image(url, media_data)

    async def get_image(self, url: str, media_data: "MediaData", spotify_slide: bool = False) -> Optional[dict]:
        crop_mode = "No Crop" if getattr(media_data, "radio_logo", False) else getattr(self.config, "crop_mode", "Crop" if getattr(self.config, "crop_borders", False) else "No Crop")
        filter_mode = getattr(self.config, "image_filter", "None")
        has_lyrics = bool(getattr(self.config, "show_lyrics", False) and getattr(media_data, "lyrics", None))
        cache_key = (
            f"{url}_{getattr(self.config, 'special_mode', False)}_{getattr(self.config, 'contrast', False)}_{getattr(self.config, 'sharpness', False)}_"
            f"{getattr(self.config, 'colors', False)}_{getattr(self.config, 'kernel', False)}_{getattr(self.config, 'show_text', False)}_{getattr(self.config, 'text_bg', False)}_"
            f"{getattr(self.config, 'top_text', False)}_{getattr(self.config, 'show_clock', False)}_{getattr(self.config, 'temperature', False)}_"
            f"{getattr(self.config, 'overlay_top', True)}_{getattr(self.config, 'overlay_align', 'Clock Right, Temp Left')}_{spotify_slide}_"
            f"{crop_mode}_{filter_mode}_{getattr(self.config, 'crop_Sensitivity', False)}_{has_lyrics}_"
            f"{getattr(self.config, 'limit_colors', 0)}_{getattr(self.config, 'vinyl_mode', False)}_"
            f"{getattr(self.config, 'cassette_mode', False)}_{getattr(self.config, 'clock_Analog', False)}_"
            f"{getattr(self.config, 'burned_text', False)}"
        )
        if getattr(self.config, "burned_text", False) or ("/api/media_player_proxy/" in url and "token=" not in url):
            cache_key += f"_{getattr(media_data, 'artist', '')}_{getattr(media_data, 'title', '')}"

        if cache_key in self.image_cache:
            self.image_cache.move_to_end(cache_key)
            cached_res = self.image_cache[cache_key]
            for attr in ("color1", "color2", "color3", "font_color", "brightness", "brightness_lower_part", "background_color", "background_color_rgb"):
                if attr in cached_res:
                    setattr(media_data, attr, cached_res[attr])
            if "live_display_url" in cached_res and cached_res["live_display_url"]:
                media_data.live_display_url = cached_res["live_display_url"]
            if cached_res.get("original_image_url"):
                media_data.original_image_url = cached_res["original_image_url"]
            return cached_res

        raw_data = await self.get_raw_image_data(url)
        if not raw_data:
            return None

        result = await self.hass.async_add_executor_job(self._process_image, raw_data, media_data, spotify_slide)
        if result:
            is_static = not (
                getattr(self.config, "vinyl_mode", False)
                or getattr(self.config, "cassette_mode", False)
                or getattr(self.config, "clock_Analog", False)
                or getattr(self.config, "spotify_slide", False)
                or getattr(self.config, "artist_slide", False)
            )
            if is_static and "pil_image" in result and not spotify_slide:
                album_tag = media_data.album if getattr(media_data, "album", None) else media_data.title
                s_key = f"std_{media_data.artist}_{album_tag}_{filter_mode}_{crop_mode}"
                live_url = await self.async_save_live_display_gif([result["pil_image"]], 1000, s_key)
                result["live_display_url"] = live_url
                media_data.live_display_url = live_url

            if getattr(media_data, "original_image_url", None):
                result["original_image_url"] = media_data.original_image_url
            self.image_cache[cache_key] = result
            if len(self.image_cache) > self.cache_size:
                self.image_cache.popitem(last=False)
        return result

    def _apply_scaling_and_filters(
        self, img_300: Image.Image, palette: dict, media_data: "MediaData", spotify_slide: bool = False
    ) -> Optional[dict]:
        filter_mode = getattr(self.config, "image_filter", "None")
        radio_logo = getattr(media_data, "radio_logo", False)
        cropped_img = self.cropper.crop_image_borders(img_300, self.config, radio_logo)
        palette = dict(palette)
        palette["font_color"] = self.color_analyzer.get_optimal_font_color(
            cropped_img.resize((50, 50), Image.Resampling.NEAREST), self.config
        )
        img = self.filter_service.apply_pre_scale(cropped_img, filter_mode)
        resample_method = Image.Resampling.LANCZOS if getattr(self.config, "kernel", True) else Image.Resampling.BILINEAR
        img = img.resize((64, 64), resample_method)

        if getattr(self.config, "contrast", False):
            img = ImageEnhance.Contrast(img).enhance(1.25)
        if getattr(self.config, "sharpness", False):
            img = ImageEnhance.Sharpness(img).enhance(1.5)
        if getattr(self.config, "colors", False):
            img = ImageEnhance.Color(img).enhance(1.3)
        if getattr(self.config, "kernel", False):
            img = img.filter(ImageFilter.SHARPEN)
        if getattr(self.config, "limit_colors", 0) > 0:
            img = img.quantize(colors=int(self.config.limit_colors), method=Image.Quantize.MAXCOVERAGE).convert("RGB")

        clean_64 = img.copy()
        if getattr(self.config, "special_mode", False):
            img = self.special_mode(img)
        img = self.filter_service.apply_post_scale(img, filter_mode)
        clean_filtered_64 = img.copy()

        for k, v in palette.items():
            setattr(media_data, k, tuple(v) if k == "background_color_rgb" and isinstance(v, list) else v)

        if not spotify_slide:
            img = self.text_clock_img(img, palette, media_data)

        b64_data = self.gbase64(img)
        if not b64_data:
            return None

        is_raw_64_mode = getattr(self.config, "analog_clock", False) or getattr(self.config, "clock_Analog", False) or getattr(self.config, "vinyl_mode", False)
        return {
            "pil_image": clean_64 if is_raw_64_mode else img,
            "clean_image": clean_filtered_64 if filter_mode != "None" else clean_64,
            "master_300_image": img_300,
            "base64_image": b64_data,
            **palette,
        }

    def _process_image(self, image_data: bytes, media_data: "MediaData", spotify_slide: bool = False) -> Optional[dict]:
        try:
            with Image.open(BytesIO(image_data)) as raw_img:
                raw_img.load()
                img = ensure_rgb(raw_img)
                if img is None:
                    return None
                img = self.fixed_size(img)
                clean_300 = img.resize((300, 300), Image.Resampling.BILINEAR)
                palette = self.color_analyzer.extract_info(clean_300.resize((64, 64), Image.Resampling.BILINEAR), media_data)
                return self._apply_scaling_and_filters(clean_300, palette, media_data, spotify_slide)
        except Exception as e:
            _LOGGER.error("Image processing failed: %s", e)
            return None

    def get_image_palette(self, img: Image.Image) -> list:
        return ColorAnalyzer.get_image_palette(img)

    async def render_from_master(
        self, master_img: Image.Image, palette: dict, media_data: "MediaData", spotify_slide: bool = False
    ) -> Optional[dict]:
        """Render 64x64 frame from a cached 300x300 master PIL Image and precomputed palette."""
        def _sync_render():
            try:
                return self._apply_scaling_and_filters(ensure_rgb(master_img), palette, media_data, spotify_slide)
            except Exception as e:
                _LOGGER.error("Master image render failed: %s", e)
                return None

        result = await self.hass.async_add_executor_job(_sync_render)
        if result:
            is_static = not (
                getattr(self.config, "vinyl_mode", False)
                or getattr(self.config, "cassette_mode", False)
                or getattr(self.config, "clock_Analog", False)
                or getattr(self.config, "spotify_slide", False)
                or getattr(self.config, "artist_slide", False)
            )
            filter_mode = getattr(self.config, "image_filter", "None")
            crop_mode = getattr(self.config, "crop_mode", "No Crop")
            if is_static and "pil_image" in result and not spotify_slide:
                album_tag = media_data.album if getattr(media_data, "album", None) else media_data.title
                s_key = f"std_{media_data.artist}_{album_tag}_{filter_mode}_{crop_mode}"
                live_url = await self.async_save_live_display_gif([result["pil_image"]], 1000, s_key)
                result["live_display_url"] = live_url
                media_data.live_display_url = live_url
            mem_tag = f"master_{media_data.artist}_{media_data.title}_{filter_mode}_{crop_mode}"
            if getattr(media_data, "original_image_url", None):
                result["original_image_url"] = media_data.original_image_url
            self.image_cache[mem_tag] = result
            if len(self.image_cache) > self.cache_size:
                self.image_cache.popitem(last=False)
        return result

    def fixed_size(self, image: Image.Image) -> Image.Image:
        return self.filter_service.fixed_size(image)

    def special_mode(self, image: Image.Image) -> Image.Image:
        return self.filter_service.special_mode(image, self.config)

    def text_clock_img(self, image: Image.Image, img_info: dict, media_data: "MediaData") -> Image.Image:
        return self.filter_service.text_clock_img(image, img_info, media_data, self.config, self._font_cache)

    def _draw_burned_text(self, image: Image.Image, media_data: "MediaData", font_color_hex: str = "#FFFFFF") -> Image.Image:
        return self.filter_service.draw_burned_text(image, media_data, font_color_hex, self._font_cache)

    def gbase64(self, image: Image.Image) -> Optional[str]:
        try:
            rgb_img = image.convert("RGB")
            if rgb_img.size != (64, 64):
                rgb_img = rgb_img.resize((64, 64), Image.Resampling.BILINEAR)
            return base64.b64encode(rgb_img.tobytes()).decode("utf-8")
        except Exception as e:
            _LOGGER.error("Base64 conversion error: %s", e)
            return None

    async def process_slide_image(self, image_data: bytes, media_data: "MediaData") -> Optional[str]:
        return await self.hass.async_add_executor_job(self._process_slide_sync, image_data, media_data)

    def _process_slide_sync(self, image_data: bytes, media_data: "MediaData") -> Optional[str]:
        try:
            with Image.open(BytesIO(image_data)) as img:
                img = self.fixed_size(ensure_rgb(img))
                img = self.cropper.crop_image_borders(img, self.config, getattr(media_data, "radio_logo", False))
                filter_mode = getattr(self.config, "image_filter", "None")
                img = self.filter_service.apply_pre_scale(img, filter_mode).resize((64, 64), Image.Resampling.BILINEAR)
                if getattr(self.config, "special_mode", False):
                    img = self.special_mode(img)
                img = self.text_clock_img(self.filter_service.apply_post_scale(img, filter_mode), {}, media_data)
                return self.gbase64(img)
        except Exception:
            return None

    def generate_vinyl_frames(self, pil_image: Image.Image, media_data: "MediaData") -> List[str]:
        from ..renderers.vinyl import VinylRenderer
        return VinylRenderer.render_frames(pil_image, self, media_data)

    def generate_cassette_frames(self, pil_image: Image.Image, media_data: "MediaData") -> List[str]:
        from ..renderers.cassette import CassetteRenderer
        return CassetteRenderer.render_frames(pil_image, self, media_data)

    def generate_analog_clock_frame(self, pil_image: Image.Image, media_data: "MediaData") -> Optional[str]:
        from ..renderers.clock import AnalogClockRenderer
        try:
            clock_img = AnalogClockRenderer.render(pil_image.copy())
            filter_mode = getattr(self.config, "image_filter", "None")
            clock_img = self.text_clock_img(self.filter_service.apply_post_scale(clock_img, filter_mode), {}, media_data)
            c_key = f"clock_{media_data.artist}_{media_data.title}_{filter_mode}"
            media_data.live_display_url = self.save_live_display_gif([clock_img], 1000, c_key)
            return self.gbase64(clock_img)
        except Exception as e:
            _LOGGER.error("Error generating analog clock frame: %s", e)
            return None

    def generate_pause_frame(self, pil_image: Optional[Image.Image], media_data: Optional["MediaData"] = None) -> Optional[str]:
        """Generate a dimmed 64x64 frame with an elegant pixel-art pause indicator."""
        try:
            if pil_image:
                base = pil_image.copy().convert("RGBA")
                if base.size != (64, 64):
                    base = base.resize((64, 64), Image.Resampling.BILINEAR)
            else:
                base = Image.new("RGBA", (64, 64), (16, 16, 22, 255))

            dark_overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 165))
            dimmed = Image.alpha_composite(base, dark_overlay)

            draw = ImageDraw.Draw(dimmed)

            # Elegant pixel-art pause bars:
            # Bar 1: x 24..28, y 22..41
            # Bar 2: x 34..38, y 22..41
            shadow_color = (0, 0, 0, 190)
            draw.rounded_rectangle([25, 23, 29, 42], radius=1, fill=shadow_color)
            draw.rounded_rectangle([35, 23, 39, 42], radius=1, fill=shadow_color)

            bar_color = (255, 255, 255, 245)
            highlight_color = (205, 230, 255, 255)

            draw.rounded_rectangle([24, 22, 28, 41], radius=1, fill=bar_color)
            draw.rounded_rectangle([34, 22, 38, 41], radius=1, fill=bar_color)

            draw.line([(24, 23), (24, 40)], fill=highlight_color)
            draw.line([(34, 23), (34, 40)], fill=highlight_color)

            final_rgb = dimmed.convert("RGB")
            if media_data:
                try:
                    p_key = f"pause_{getattr(media_data, 'artist', '')}_{getattr(media_data, 'title', '')}"
                    live_url = self.save_live_display_gif([final_rgb], 1000, p_key)
                    if live_url:
                        media_data.live_display_url = live_url
                except Exception:
                    pass

            return self.gbase64(final_rgb)
        except Exception as e:
            _LOGGER.error("Failed to generate pause frame: %s", e)
            return None

    def save_live_display_gif(self, pil_frames: List[Image.Image], duration_ms: int, cache_key: str) -> Optional[str]:
        if not pil_frames:
            return None
        try:
            with self._gif_lock:
                cache_dir = self.hass.config.path("www", "pixoo_cache")
                os.makedirs(cache_dir, exist_ok=True)
                safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in cache_key).strip("_")[:100]
                filename = f"pixoo_{safe_key or 'art'}.gif"
                file_path = os.path.join(cache_dir, filename)
                pil_frames[0].convert("RGBA").save(
                    file_path,
                    save_all=True,
                    append_images=[f.convert("RGBA") for f in pil_frames[1:]],
                    duration=duration_ms,
                    loop=0,
                    disposal=2,
                    optimize=False,
                )
                try:
                    entries = []
                    for f in os.listdir(cache_dir):
                        if f.startswith("pixoo_"):
                            p = os.path.join(cache_dir, f)
                            try:
                                entries.append((os.path.getmtime(p), p))
                            except OSError:
                                pass
                    entries.sort(key=lambda item: item[0])
                    while len(entries) > self.cache_size:
                        _, oldest = entries.pop(0)
                        try:
                            os.remove(oldest)
                        except OSError:
                            pass
                except OSError:
                    pass
                return f"/local/pixoo_cache/{filename}?t={int(time.time() * 1000)}"
        except Exception as e:
            _LOGGER.error("Failed to save live display GIF: %s", e)
            return None

    async def async_save_live_display_gif(self, pil_frames: List[Image.Image], duration_ms: int, cache_key: str) -> Optional[str]:
        return await self.hass.async_add_executor_job(self.save_live_display_gif, pil_frames, duration_ms, cache_key)

    def shutdown(self) -> None:
        self.image_cache.clear()
        self.raw_image_cache.clear()
