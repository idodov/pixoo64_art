"""Spotify OAuth, search, album resolution, and discography slider service."""
import asyncio
import base64
from io import BytesIO
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Optional
import aiohttp
from PIL import Image

from ..models import ensure_rgb
from ..storage import generate_artist_cache_key
from .base import BaseProvider, _album_match_score

if TYPE_CHECKING:
    from ..device import PixooDevice
    from ..image.processor import ImageProcessor
    from ..models import Config, MediaData

_LOGGER = logging.getLogger(__name__)


class SpotifyService(BaseProvider):
    """Handles Spotify API authentication, track/album search, and slider animations."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession, image_processor: "ImageProcessor") -> None:
        self.config = config
        self.session = session
        self.image_processor = image_processor
        self.spotify_token_cache: dict[str, Any] = {"token": None, "expires": 0}
        self.spotify_data: Optional[dict] = None
        self.last_match_tier: int = 1
        self.album_image_map: dict[str, str] = {}
        self._semaphore = asyncio.Semaphore(5)

    async def get_spotify_access_token(self) -> Optional[str]:
        if self.spotify_token_cache["token"] and time.time() < self.spotify_token_cache["expires"]:
            return self.spotify_token_cache["token"]
        if not self.config.spotify_client_id or not self.config.spotify_client_secret:
            return None
        url = "https://accounts.spotify.com/api/token"
        auth_str = base64.b64encode(f"{self.config.spotify_client_id}:{self.config.spotify_client_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {auth_str}", "Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with self.session.post(url, headers=headers, data={"grant_type": "client_credentials"}, timeout=10) as resp:
                resp.raise_for_status()
                data = await resp.json()
                token = data["access_token"]
                self.spotify_token_cache = {"token": token, "expires": time.time() + data.get("expires_in", 3600) - 60}
                return token
        except Exception as e:
            _LOGGER.error("Error fetching Spotify token: %s", e)
        return None

    async def _async_spotify_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        token = await self.get_spotify_access_token()
        if not token:
            return None
        url = f"https://api.spotify.com/v1/{endpoint}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with self.session.get(url, headers=headers, params=params, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 401:
                    self.spotify_token_cache = {"token": None, "expires": 0}
        except Exception as e:
            _LOGGER.error("Spotify API request failed for '%s': %s", endpoint, e)
        return None

    async def get_spotify_json(self, artist: str, title: str) -> Optional[dict]:
        clean_title = re.sub(r"[\'\"()]", "", str(title or "")).strip()
        clean_artist = re.sub(r"[\'\"()]", "", str(artist or "")).strip()
        params = {"q": f'track:"{clean_title}" artist:"{clean_artist}"', "type": "track", "limit": 50}
        data = await self._async_spotify_request("search", params=params)
        if data and data.get("tracks", {}).get("items"):
            return data
        return await self._async_spotify_request("search", {"q": f"{clean_artist} {clean_title}", "type": "track", "limit": 50})

    async def get_spotify_artist_image_url_by_name(self, artist_name: str) -> Optional[str]:
        if not artist_name:
            return None
        primary = re.split(r"[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+", artist_name, flags=re.IGNORECASE)[0].strip()
        data = await self._async_spotify_request("search", params={"q": f"artist:{primary}", "type": "artist", "limit": 1})
        if data and "artists" in data and data["artists"]["items"]:
            artist_id = data["artists"]["items"][0]["id"]
            art_data = await self._async_spotify_request(f"artists/{artist_id}")
            if art_data and art_data.get("images"):
                return art_data["images"][0]["url"]
        return None

    async def prepare_slider_for_media(self, media_data: "MediaData") -> list[str]:
        if getattr(media_data, "slider_album_urls", None):
            return media_data.slider_album_urls
        media_data.slider_error = None
        spotify_json = await self.get_spotify_json(media_data.artist, media_data.title)
        if not spotify_json:
            media_data.slider_error = "Track not found on Spotify"
            return []
        self.spotify_data = spotify_json
        media_data.slider_artist_pic_url = await self.get_spotify_artist_image_url_by_name(media_data.artist)

        tracks = spotify_json.get("tracks", {}).get("items", [])
        albums = {}
        raw_artists = [
            a.strip().lower()
            for a in re.split(r"[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+", media_data.artist, flags=re.IGNORECASE)
            if a.strip()
        ]
        for track in tracks:
            album = track.get("album", {})
            album_id = album.get("id")
            album_artists = [a.get("name", "").strip().lower() for a in album.get("artists", [])]
            if any("various artists" in a for a in album_artists):
                continue
            if raw_artists and not any(ra in aa or aa in ra for ra in raw_artists for aa in album_artists):
                continue
            if album_id and album_id not in albums:
                albums[album_id] = album

        sorted_albums = sorted(
            albums.values(),
            key=lambda x: (x.get("album_type") == "single", x.get("album_type") == "album"),
            reverse=True,
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
        return [] if getattr(media_data, "playing_tv", False) else await self.prepare_slider_for_media(media_data)

    async def get_slide_img(self, picture: str, media_data: "MediaData") -> Optional[str]:
        try:
            raw = await self.image_processor.get_raw_image_data(picture)
            if raw:
                return await self.image_processor.process_slide_image(raw, media_data)
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
        self, pixoo_device: "PixooDevice", command: str, pic_num: int, pic_width: int, pic_offset: int, pic_id: int, pic_speed: int, pic_data: str
    ) -> None:
        await pixoo_device.send_command({
            "Command": command, "PicNum": pic_num, "PicWidth": pic_width,
            "PicOffset": pic_offset, "PicID": pic_id, "PicSpeed": pic_speed, "PicData": pic_data,
        })

    async def spotify_albums_slide(
        self, pixoo_device: Optional["PixooDevice"], media_data: "MediaData", prev_channel: int = 0, send_to_device: bool = True
    ) -> None:
        media_data.spotify_slide_pass = False
        try:
            album_urls_b64 = getattr(media_data, "slider_frames_b64", None)
            storage_mgr = getattr(self.image_processor, "storage_manager", None)
            artist_key = generate_artist_cache_key(getattr(media_data, "artist", "") or "")
            filter_mode = getattr(self.config, "image_filter", "None")

            if (not album_urls_b64 or len(album_urls_b64) < 2) and storage_mgr:
                cached_slider = await storage_mgr.async_get_artist_slider(artist_key)
                if cached_slider:
                    clean_frames, source_urls = (
                        cached_slider if isinstance(cached_slider, tuple) else (cached_slider, [f"cache://{artist_key}"])
                    )
                    if len(clean_frames) >= 2:
                        def _render_cached_frames():
                            b64_list, pil_list = [], []
                            for frm in clean_frames:
                                if isinstance(frm, bytes):
                                    with Image.open(BytesIO(frm)) as opened:
                                        img = opened.convert("RGB")
                                else:
                                    img = frm.copy()
                                if getattr(self.config, "special_mode", False):
                                    img = self.image_processor.special_mode(img)
                                img = self.image_processor.filter_service.apply_post_scale(img, filter_mode)
                                img = self.image_processor.text_clock_img(img, {}, media_data)
                                b64 = self.image_processor.gbase64(img)
                                if b64:
                                    b64_list.append(b64)
                                    pil_list.append(img)
                            return b64_list, pil_list

                        album_urls_b64, slide_pil = await self.image_processor.hass.async_add_executor_job(_render_cached_frames)
                        if len(album_urls_b64) >= 2:
                            media_data.slider_frames_b64 = album_urls_b64
                            media_data.slider_album_urls = source_urls
                            media_data.pic_url = source_urls
                            media_data.pic_source = "Spotify (Slide)"
                            s_key = f"slider_{media_data.artist}_{media_data.title}"
                            media_data.live_display_url = await self.image_processor.async_save_live_display_gif(slide_pil, 5000, s_key)

            if not album_urls_b64 or len(album_urls_b64) < 2:
                album_urls = getattr(media_data, "slider_album_urls", None) or await self.prepare_slider_for_media(media_data)
                if not album_urls or len(album_urls) < 2:
                    return
                if send_to_device and pixoo_device:
                    artist_pic_url = getattr(media_data, "slider_artist_pic_url", None) or await self.get_spotify_artist_image_url_by_name(media_data.artist)
                    if artist_pic_url:
                        preview_b64 = await self.get_slide_img(artist_pic_url, media_data)
                        if preview_b64:
                            await pixoo_device.send_command({
                                "Command": "Draw/CommandList",
                                "CommandList": [
                                    {"Command": "Draw/ResetHttpGifId"},
                                    {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 1000, "PicData": preview_b64},
                                ],
                            })

                def _decode_and_render_slide(raw_data: bytes):
                    with Image.open(BytesIO(raw_data)) as raw_img:
                        img = self.image_processor.fixed_size(ensure_rgb(raw_img))
                        clean_64 = img.resize((64, 64), Image.Resampling.BILINEAR)
                        styled = self.image_processor.filter_service.apply_pre_scale(img, filter_mode).resize((64, 64), Image.Resampling.BILINEAR)
                        if getattr(self.config, "special_mode", False):
                            styled = self.image_processor.special_mode(styled)
                        styled = self.image_processor.text_clock_img(self.image_processor.filter_service.apply_post_scale(styled, filter_mode), {}, media_data)
                        return self.image_processor.gbase64(styled), styled.copy(), clean_64.copy()

                async def process_pipeline(url):
                    async with self._semaphore:
                        try:
                            raw_data = await self.image_processor.get_raw_image_data(url)
                            if raw_data:
                                return await self.image_processor.hass.async_add_executor_job(_decode_and_render_slide, raw_data)
                        except Exception as err:
                            _LOGGER.error("Slide image pipeline error: %s", err)
                        return None, None, None

                results = await asyncio.gather(*[process_pipeline(url) for url in album_urls[:10]])
                album_urls_b64 = [res[0] for res in results if res[0]]
                slide_pil_frames = [res[1] for res in results if res[1]]
                clean_64_frames = [res[2] for res in results if res[2]]
                if len(album_urls_b64) < 2:
                    media_data.slider_error = "Insufficient valid frames processed"
                    return
                media_data.slider_frames_b64 = album_urls_b64
                if storage_mgr and len(clean_64_frames) >= 2:
                    await storage_mgr.async_save_artist_slider(artist_key, clean_64_frames, album_urls[:10])
                if slide_pil_frames:
                    s_key = f"slider_{media_data.artist}_{media_data.title}"
                    media_data.live_display_url = await self.image_processor.async_save_live_display_gif(slide_pil_frames, 5000, s_key)

            frames = len(album_urls_b64)
            media_data.spotify_slide_pass = True
            media_data.slider_frames = frames
            if send_to_device and pixoo_device:
                await pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ResetHttpGifId"}]})
                for pic_offset, b64_frame in enumerate(album_urls_b64):
                    await self.send_pixoo_animation_frame(pixoo_device, "Draw/SendHttpGif", frames, 64, pic_offset, 0, 5000, b64_frame)
        except Exception as e:
            media_data.slider_error = str(e)
            _LOGGER.error("Spotify Albums Slide Animation Error: %s", e)

    async def spotify_album_art_animation(self, pixoo_device: "PixooDevice", media_data: "MediaData", prev_channel: int) -> None:
        await self.spotify_albums_slide(pixoo_device, media_data, prev_channel, send_to_device=True)

    async def spotify_best_album(self, tracks: list[dict], artist: str, album: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        self.last_match_tier = 1
        for trk in tracks:
            alb = trk.get("album") or {}
            if alb.get("id") and alb.get("images"):
                self.album_image_map[alb["id"]] = alb["images"][0]["url"]
        first_album_id = tracks[0]["album"]["id"] if tracks else None
        raw_artists = [
            a.strip().lower()
            for a in re.split(r"[,&/]|(?:\s+feat\.?\s+)|\s+ft\.?\s+|\s+and\s+", str(artist or ""), flags=re.IGNORECASE)
            if a.strip()
        ]

        def _artist_matches(alb_obj: dict) -> bool:
            alb_artists = [a.get("name", "").strip().lower() for a in alb_obj.get("artists", [])]
            return True if (not raw_artists or not alb_artists) else any(ra in aa or aa in ra for ra in raw_artists for aa in alb_artists)

        def _type_rank(alb_obj: dict) -> int:
            t = str(alb_obj.get("album_type") or "").lower()
            return 0 if t == "album" else (1 if t == "single" else 2)

        has_known_album = bool(album and str(album).strip().lower() not in ("", "unknown album", "unknown", "none"))
        if has_known_album:
            best_score, matched_album = 0.0, None
            for track in tracks:
                alb = track.get("album") or {}
                if not _artist_matches(alb):
                    continue
                score = _album_match_score(album, alb.get("name", ""))
                if score > best_score or (score == best_score and matched_album and _type_rank(alb) < _type_rank(matched_album)):
                    best_score, matched_album = score, alb
            if matched_album and best_score >= 0.76:
                self.last_match_tier = 1
                return matched_album.get("id"), first_album_id

        best_album, best_key = None, (99, float("inf"))
        for track in tracks:
            alb = track.get("album") or {}
            if not _artist_matches(alb):
                continue
            release_date = alb.get("release_date")
            year = int(release_date[:4]) if release_date and release_date[:4].isdigit() else float("inf")
            cand_key = (_type_rank(alb), year)
            if cand_key < best_key:
                best_key, best_album = cand_key, alb

        self.last_match_tier = 2 if has_known_album else 1
        return (best_album.get("id") if best_album else None), first_album_id

    async def get_spotify_album_id(self, media_data: "MediaData") -> tuple[Optional[str], Optional[str]]:
        try:
            self.spotify_data = None
            self.last_match_tier = 1
            known_album = (
                media_data.album.strip()
                if (
                    getattr(media_data, "album", None)
                    and str(media_data.album).strip().lower() not in ("", "unknown album", "unknown", "none")
                    and not getattr(media_data, "playing_radio", False)
                )
                else None
            )
            response_json = await self.get_spotify_json(media_data.artist, media_data.title)
            tracks = response_json.get("tracks", {}).get("items", []) if response_json else []
            best_album_id, first_album_id = None, None
            if tracks:
                self.spotify_data = response_json
                best_album_id, first_album_id = await self.spotify_best_album(tracks, media_data.artist, known_album)
                if best_album_id and self.last_match_tier == 1:
                    return best_album_id, first_album_id

            if known_album:
                c_artist = re.sub(r"[\'\"()]", "", str(media_data.artist or "")).strip()
                c_album = re.sub(r"[\'\"()]", "", str(known_album)).strip()
                a_data = await self._async_spotify_request("search", params={"q": f'album:"{c_album}" artist:"{c_artist}"', "type": "album", "limit": 5})
                for alb in (a_data.get("albums", {}).get("items", []) if a_data else []):
                    if alb.get("id") and alb.get("images"):
                        self.album_image_map[alb["id"]] = alb["images"][0]["url"]
                    if _album_match_score(known_album, alb.get("name", "")) >= 0.76:
                        self.last_match_tier = 1
                        return alb.get("id"), first_album_id or alb.get("id")

            return (best_album_id, first_album_id) if tracks else (None, None)
        except Exception as e:
            _LOGGER.error("Error retrieving Spotify Album ID: %s", e)
            return None, None

    async def get_spotify_album_image_url(self, album_id: str) -> Optional[str]:
        if not album_id:
            return None
        if album_id in self.album_image_map:
            return self.album_image_map[album_id]
        res = await self._async_spotify_request(f"albums/{album_id}")
        if res and res.get("images"):
            self.album_image_map[album_id] = res["images"][0]["url"]
            return self.album_image_map[album_id]
        return None
