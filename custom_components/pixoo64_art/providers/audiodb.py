"""TheAudioDB artist fanart, thumbnail provider, and Artist Gallery slider."""
import asyncio
from collections import OrderedDict
from io import BytesIO
import logging
import re
from typing import TYPE_CHECKING, List, Optional
import urllib.parse
import aiohttp
from PIL import Image

from ..models import ensure_rgb
from ..storage import generate_artist_cache_key
from .base import BaseProvider

if TYPE_CHECKING:
    from ..device import PixooDevice
    from ..image.processor import ImageProcessor
    from ..models import Config, MediaData

_LOGGER = logging.getLogger(__name__)


class TheAudioDbProvider(BaseProvider):
    """Fetches artist fanart and thumbnails from TheAudioDB public API and renders gallery slides."""

    def __init__(self, session: aiohttp.ClientSession, config: Optional["Config"] = None) -> None:
        self.session = session
        self.config = config

    async def get_artist_images(self, artist: str) -> List[str]:
        """Return deduplicated list of artist image URLs from TheAudioDB."""
        if self.config and not getattr(self.config, "audiodb_enabled", True):
            return []
        clean_artist = str(artist or "").strip()
        if not clean_artist or clean_artist == "Unknown Artist":
            return []
        raw_artists = [
            a.strip()
            for a in re.split(r"[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+", clean_artist, flags=re.IGNORECASE)
            if a.strip()
        ]
        urls: List[str] = []
        for a in raw_artists:
            url = f"https://www.theaudiodb.com/api/v1/json/123/search.php?s={urllib.parse.quote(a)}"
            try:
                async with self.session.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        artists_data = data.get("artists")
                        if artists_data and isinstance(artists_data, list):
                            ad = artists_data[0]
                            for key in (
                                "strArtistThumb",
                                "strArtistFanart",
                                "strArtistFanart2",
                                "strArtistFanart3",
                                "strArtistFanart4",
                                "strArtistClearart",
                                "strArtistWideThumb",
                            ):
                                val = ad.get(key)
                                if val and isinstance(val, str) and val.startswith("http"):
                                    urls.append(val)
            except Exception as e:
                _LOGGER.debug("AudioDB search exception: %s", e)
        return list(OrderedDict.fromkeys(urls))

    async def play_artist_gallery_slide(
        self,
        image_processor: "ImageProcessor",
        pixoo_device: Optional["PixooDevice"],
        media_data: "MediaData",
        send_to_device: bool = True,
    ) -> None:
        media_data.artist_slide_pass = False
        try:
            frames_b64 = getattr(media_data, "slider_frames_b64", None)
            storage_mgr = getattr(image_processor, "storage_manager", None)
            artist_key = generate_artist_cache_key(getattr(media_data, "artist", "") or "")
            filter_mode = getattr(self.config, "image_filter", "None") if self.config else "None"

            if (not frames_b64 or len(frames_b64) < 2) and storage_mgr:
                cached_slider = await storage_mgr.async_get_artist_slider(artist_key)
                if cached_slider:
                    clean_frames, source_urls = (
                        cached_slider if isinstance(cached_slider, tuple) else (cached_slider, [f"cache://{artist_key}"])
                    )
                    if len(clean_frames) >= 2:
                        def _render_cached():
                            b64_list, pil_list = [], []
                            for frm in clean_frames:
                                if isinstance(frm, bytes):
                                    with Image.open(BytesIO(frm)) as opened:
                                        base_img = opened.convert("RGB")
                                else:
                                    base_img = frm.copy()
                                img = image_processor.text_clock_img(
                                    image_processor.filter_service.apply_post_scale(base_img, filter_mode), {}, media_data
                                )
                                b64 = image_processor.gbase64(img)
                                if b64:
                                    b64_list.append(b64)
                                    pil_list.append(img)
                            return b64_list, pil_list

                        frames_b64, gallery_pil = await image_processor.hass.async_add_executor_job(_render_cached)
                        if len(frames_b64) >= 2:
                            media_data.slider_frames_b64 = frames_b64
                            media_data.slider_album_urls = source_urls
                            media_data.live_display_url = await image_processor.async_save_live_display_gif(
                                gallery_pil, 5000, f"artist_gallery_{media_data.artist}"
                            )

            if not frames_b64 or len(frames_b64) < 2:
                urls = getattr(media_data, "slider_album_urls", None) or await self.get_artist_images(media_data.artist)
                if not urls or len(urls) < 2:
                    media_data.slider_error = "Not enough artist images found"
                    return
                media_data.slider_album_urls = urls
                sem = asyncio.Semaphore(5)

                def _decode_gallery_frame(raw_data: bytes):
                    with Image.open(BytesIO(raw_data)) as raw_img:
                        img = image_processor.fixed_size(ensure_rgb(raw_img))
                        clean_64 = img.resize((64, 64), Image.Resampling.BILINEAR)
                        styled = image_processor.filter_service.apply_pre_scale(img, filter_mode).resize((64, 64), Image.Resampling.BILINEAR)
                        styled = image_processor.text_clock_img(
                            image_processor.filter_service.apply_post_scale(styled, filter_mode), {}, media_data
                        )
                        return image_processor.gbase64(styled), styled.copy(), clean_64.copy()

                async def process_pipeline(url):
                    async with sem:
                        try:
                            raw_data = await image_processor.get_raw_image_data(url)
                            if raw_data:
                                return await image_processor.hass.async_add_executor_job(_decode_gallery_frame, raw_data)
                        except Exception as err:
                            _LOGGER.error("Artist Slide pipeline error: %s", err)
                        return None, None, None

                results = await asyncio.gather(*[process_pipeline(u) for u in urls[:10]])
                frames_b64 = [f[0] for f in results if f[0]]
                gallery_pil_frames = [f[1] for f in results if f[1]]
                clean_64_frames = [f[2] for f in results if f[2]]
                if len(frames_b64) < 2:
                    media_data.slider_error = "Failed to process enough frames"
                    return
                media_data.slider_frames_b64 = frames_b64
                if storage_mgr and len(clean_64_frames) >= 2:
                    await storage_mgr.async_save_artist_slider(artist_key, clean_64_frames, urls[:10])
                if gallery_pil_frames:
                    media_data.live_display_url = await image_processor.async_save_live_display_gif(
                        gallery_pil_frames, 5000, f"artist_gallery_{media_data.artist}"
                    )

            media_data.artist_slide_pass = True
            media_data.slider_frames = len(frames_b64)
            if send_to_device and pixoo_device:
                await pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ResetHttpGifId"}]})
                for pic_offset, b64_frame in enumerate(frames_b64):
                    await pixoo_device.send_command({
                        "Command": "Draw/SendHttpGif", "PicNum": len(frames_b64), "PicWidth": 64,
                        "PicOffset": pic_offset, "PicID": 0, "PicSpeed": 5000, "PicData": b64_frame,
                    })
        except Exception as e:
            media_data.slider_error = str(e)
            _LOGGER.error("Artist Gallery Slide Error: %s", e)
