"""Fallback coordinator service (Smart Race Mode, Sequential Mode, and Persistent Master Caching)."""
import asyncio
from collections import OrderedDict
from io import BytesIO
import logging
import time
from typing import TYPE_CHECKING, Any, Optional
import aiohttp
from PIL import Image

from ..models import ensure_rgb
from ..storage import generate_artist_cache_key, generate_artwork_cache_key
from .ai import AiArtProvider
from .audiodb import TheAudioDbProvider
from .base import BaseProvider, create_fallback_black_image_data, create_tv_icon_image
from .discogs import DiscogsProvider
from .internet_archive import InternetArchiveProvider
from .lastfm import LastFmProvider
from .musicbrainz import MusicBrainzProvider
from .tidal import TidalProvider

if TYPE_CHECKING:
    from ..device import PixooDevice
    from ..image.processor import ImageProcessor
    from ..models import Config, MediaData
    from .spotify import SpotifyService

_LOGGER = logging.getLogger(__name__)


class FallbackService(BaseProvider):
    """Coordinates artwork resolution across local storage, media player, and upstream providers."""

    def __init__(
        self, config: "Config", image_processor: "ImageProcessor", session: aiohttp.ClientSession,
        spotify_service: "SpotifyService", pixoo_device: "PixooDevice", hub: Optional[Any] = None,
    ) -> None:
        self.config, self.image_processor, self.session = config, image_processor, session
        self.spotify_service, self.pixoo_device, self.hub = spotify_service, pixoo_device, hub
        self.fail_txt = self.fallback = False
        self._artwork_cache: OrderedDict[str, dict] = OrderedDict()
        self.mb_provider, self.discogs_provider = MusicBrainzProvider(session), DiscogsProvider(config, session)
        self.lastfm_provider, self.tidal_provider = LastFmProvider(config, session), TidalProvider(config, session)
        self.ai_provider, self.ia_provider = AiArtProvider(config), InternetArchiveProvider(session)
        self.audiodb_provider = TheAudioDbProvider(session, config)

    async def get_musicbrainz_album_art_url(self, artist: str, title: str, album: Optional[str] = None):
        return await self.mb_provider.get_album_art_url(artist, title, album)

    async def search_discogs_album_art(self, artist: str, title: str, album: Optional[str] = None):
        return await self.discogs_provider.search_album_art(artist, title, album)

    async def search_lastfm_album_art(self, artist: str, title: str, album: Optional[str] = None):
        return await self.lastfm_provider.search_album_art(artist, title, album)

    async def get_tidal_album_art_url(self, artist: str, title: str, album: Optional[str] = None):
        return await self.tidal_provider.get_album_art_url(artist, title, album)

    async def get_tidal_access_token(self):
        return await self.tidal_provider.get_access_token()

    async def _persist_master_artwork(
        self, cache_key: str, proc_result: Optional[dict], source: str, original_url: Optional[str] = None
    ) -> None:
        storage_mgr = getattr(self.image_processor, "storage_manager", None)
        master_img = proc_result.get("master_300_image") if proc_result else None
        if not storage_mgr or not master_img or source in ("Spotify Artist", "TheAudioDB"):
            return
        palette = {
            "font_color": proc_result.get("font_color", "#FFFFFF"), "brightness": proc_result.get("brightness", 0.5),
            "brightness_lower_part": proc_result.get("brightness_lower_part", 0.5),
            "background_color": proc_result.get("background_color", "#000000"),
            "background_color_rgb": list(proc_result.get("background_color_rgb", (0, 0, 0))),
            "color1": proc_result.get("color1", "#000000"), "color2": proc_result.get("color2", "#000000"),
            "color3": proc_result.get("color3", "#000000"),
        }
        if original_url and str(original_url).startswith("https://") and "/api/media_player_proxy/" not in str(original_url):
            palette["original_image_url"] = str(original_url)
        await storage_mgr.async_save_master(cache_key, master_img, source, palette)

    async def _resolve_remote_url_for_cached(
        self, source: str, media_data: "MediaData", known_album: Optional[str]
    ) -> Optional[str]:
        src_clean = str(source or "").lower()
        try:
            if "last" in src_clean:
                return await self.lastfm_provider.search_album_art(media_data.artist, media_data.title, known_album)
            if "spotify" in src_clean:
                album_id, _ = await self.spotify_service.get_spotify_album_id(media_data)
                if album_id:
                    return await self.spotify_service.get_spotify_album_image_url(album_id)
            if "musicbrainz" in src_clean:
                return await self.mb_provider.get_album_art_url(media_data.artist, media_data.title, known_album)
            if "discogs" in src_clean:
                return await self.discogs_provider.search_album_art(media_data.artist, media_data.title, known_album)
            if "tidal" in src_clean:
                return await self.tidal_provider.get_album_art_url(media_data.artist, media_data.title, known_album)
        except Exception as e:
            _LOGGER.debug("Error resolving remote URL for cached artwork (%s): %s", source, e)
        return None

    async def play_artist_gallery_slide(
        self, pixoo_device: Optional["PixooDevice"], media_data: "MediaData", send_to_device: bool = True
    ) -> None:
        await self.audiodb_provider.play_artist_gallery_slide(self.image_processor, pixoo_device, media_data, send_to_device)

    async def prefetch_next_track(self, url: Optional[str], media_data: "MediaData") -> None:
        await self.get_final_url(url, media_data)
        frames = 0
        if getattr(self.config, "spotify_slide", False) and not getattr(media_data, "radio_logo", False):
            frames = await self.spotify_service.prefetch_slider_data(media_data)
        elif getattr(self.config, "artist_slide", False) and not getattr(media_data, "radio_logo", False):
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
        if picture and isinstance(picture, str) and picture.startswith("https://") and "/api/media_player_proxy/" not in picture:
            media_data.original_image_url = picture
        is_force_ai = bool(
            getattr(self.config, "force_ai", False)
            and getattr(self.config, "pollinations", None)
            and not getattr(media_data, "radio_logo", False)
            and not getattr(media_data, "playing_tv", False)
        )
        storage_cache_key = generate_artwork_cache_key(
            getattr(media_data, "artist", "") or "",
            getattr(media_data, "album", None),
            getattr(media_data, "title", "") or "",
            force_ai=is_force_ai,
            playing_radio=getattr(media_data, "playing_radio", False),
            playing_tv=getattr(media_data, "playing_tv", False),
        )
        known_album = (
            media_data.album.strip()
            if (
                getattr(media_data, "album", None)
                and str(media_data.album).strip().lower() not in ("", "unknown album", "unknown", "none", "single", "singles")
                and not getattr(media_data, "playing_radio", False)
            )
            else None
        )
        song_cache_key = f"{media_data.artist}_{known_album or media_data.title}".strip().lower()
        is_spotify_slider = getattr(self.config, "spotify_slide", False) and not getattr(media_data, "radio_logo", False) and not getattr(media_data, "playing_tv", False)
        is_artist_slider = getattr(self.config, "artist_slide", False) and not getattr(media_data, "radio_logo", False) and not getattr(media_data, "playing_tv", False)
        is_slide_pass = getattr(media_data, "spotify_slide_pass", False) or getattr(media_data, "artist_slide_pass", False)

        if picture == "TV_IS_ON_ICON":
            media_data.pic_source = "Internal"
            media_data.pic_url = "TV Icon"
            tv_icon_img = self.create_tv_icon_image()
            return {
                "pil_image": tv_icon_img, "clean_image": tv_icon_img, "base64_image": self.image_processor.gbase64(tv_icon_img),
                "font_color": "#FF00FF", "brightness": 0.67, "brightness_lower_part": 0.5, "background_color": "#000000",
                "background_color_rgb": (0, 0, 0), "color1": "#000000", "color2": "#000000", "color3": "#000000",
            }

        storage_mgr = getattr(self.image_processor, "storage_manager", None)
        if not is_spotify_slider and not is_artist_slider and storage_mgr:
            f_mode, c_mode = getattr(self.config, "image_filter", "None"), getattr(self.config, "crop_mode", "No Crop")
            mem_tag = f"master_{media_data.artist}_{media_data.title}_{f_mode}_{c_mode}"
            if mem_tag in self.image_processor.image_cache:
                self.image_processor.image_cache.move_to_end(mem_tag)
                cached_res = self.image_processor.image_cache[mem_tag]
                if cached_res.get("original_image_url"):
                    media_data.original_image_url = cached_res["original_image_url"]
                elif song_cache_key in self._artwork_cache and str(self._artwork_cache[song_cache_key].get("url", "")).startswith("https://"):
                    media_data.original_image_url = self._artwork_cache[song_cache_key]["url"]
                media_data.pic_url = media_data.original_image_url or (picture if (picture and str(picture).startswith("https://") and "/api/media_player_proxy/" not in picture) else None) or cached_res.get("live_display_url") or f"cache://{storage_cache_key}"
                media_data.pic_source = "RAM Cache"
                if cached_res.get("live_display_url"):
                    media_data.live_display_url = cached_res["live_display_url"]
                return cached_res
            cached_master = await storage_mgr.async_get_master(storage_cache_key)
            if cached_master:
                if isinstance(cached_master, dict):
                    with Image.open(BytesIO(cached_master["image_bytes"])) as im:
                        master_img = im.convert("RGB")
                    palette, cached_source = cached_master.get("palette", {}), cached_master.get("source", "Cache")
                else:
                    master_img, palette, cached_source = cached_master
                if not media_data.original_image_url:
                    if palette.get("original_image_url") and str(palette["original_image_url"]).startswith("https://"):
                        media_data.original_image_url = palette["original_image_url"]
                    elif song_cache_key in self._artwork_cache and str(self._artwork_cache[song_cache_key].get("url", "")).startswith("https://"):
                        media_data.original_image_url = self._artwork_cache[song_cache_key]["url"]
                        palette["original_image_url"] = media_data.original_image_url
                        await storage_mgr.async_save_master(storage_cache_key, master_img, cached_source, palette)
                    elif cached_source and cached_source not in ("Cache", "Original", "TV", "Internal"):
                        resolved_url = await self._resolve_remote_url_for_cached(cached_source, media_data, known_album)
                        if resolved_url and resolved_url.startswith("https://"):
                            media_data.original_image_url = resolved_url
                            self._save_to_artwork_cache(song_cache_key, resolved_url, cached_source)
                            palette["original_image_url"] = resolved_url
                            await storage_mgr.async_save_master(storage_cache_key, master_img, cached_source, palette)
                proc_res = await self.image_processor.render_from_master(master_img, palette, media_data, is_slide_pass)
                if proc_res:
                    media_data.pic_url = media_data.original_image_url or (picture if (picture and str(picture).startswith("https://") and "/api/media_player_proxy/" not in picture) else None) or proc_res.get("live_display_url") or f"cache://{storage_cache_key}"
                    media_data.pic_source = f"{cached_source} (Cached)"
                    return proc_res

        if not is_spotify_slider and not is_artist_slider and is_force_ai:
            ai_res = await self._try_ai_generation(media_data)
            if ai_res:
                await self._persist_master_artwork(storage_cache_key, ai_res, "AI", getattr(media_data, "original_image_url", None))
                return ai_res

        if not is_force_ai and song_cache_key in self._artwork_cache:
            cached = self._artwork_cache[song_cache_key]
            if not is_spotify_slider and not is_artist_slider or cached.get("source") in ["Spotify", "Spotify Artist", "Spotify (Artist Profile Image)", "Original"]:
                if cached.get("url") and str(cached["url"]).startswith("https://") and "/api/media_player_proxy/" not in cached["url"]:
                    media_data.original_image_url = cached["url"]
                proc_res = await self.image_processor.get_image(cached["url"], media_data, is_slide_pass)
                if proc_res:
                    media_data.pic_url = cached["url"]
                    media_data.pic_source = cached["source"]
                    return proc_res

        if not (is_spotify_slider or is_artist_slider):
            if res := await self._resolve_upstream_providers(picture, media_data, known_album, is_slide_pass, song_cache_key, storage_cache_key):
                return res

        media_data.pic_url, media_data.pic_source = "Fallback Image", "Internal"
        return await self.image_processor.hass.async_add_executor_job(self._get_fallback_black_image_data, media_data)

    async def _resolve_upstream_providers(
        self, picture: Optional[str], media_data: "MediaData", known_album: Optional[str], is_slide_pass: bool, song_cache_key: str, storage_cache_key: str
    ) -> Optional[dict]:
        has_providers = bool(
            (getattr(self.config, "spotify_client_id", None) and getattr(self.config, "spotify_client_secret", None))
            or (getattr(self.config, "tidal_client_id", None) and getattr(self.config, "tidal_client_secret", None))
            or getattr(self.config, "lastfm", None) or getattr(self.config, "discogs", None)
            or getattr(self.config, "musicbrainz", False) or getattr(self.config, "internet_archive", False)
        )
        use_race_mode = getattr(self.config, "artwork_race_mode", False) and has_providers
        is_generic_logo = getattr(media_data, "playing_radio", False) and getattr(media_data, "radio_logo", False)

        if not use_race_mode:
            if picture and not is_generic_logo:
                try:
                    result = await self.image_processor.get_image(picture, media_data, is_slide_pass)
                    if result:
                        if picture and picture.startswith("https://") and "/api/media_player_proxy/" not in picture:
                            media_data.original_image_url = picture
                        self._save_to_artwork_cache(song_cache_key, picture, "Original")
                        await self._persist_master_artwork(storage_cache_key, result, "Original", getattr(media_data, "original_image_url", None))
                        media_data.pic_source = "Original"
                        media_data.pic_url = picture
                        return result
                except Exception as e:
                    _LOGGER.debug("First attempt fetching original artwork failed: %s", e)

                # Retry original art only if entity_picture attribute changed or radio
                if "/api/media_player_proxy/" in picture or getattr(media_data, "playing_radio", False):
                    latest_st = self.image_processor.hass.states.get(getattr(self.config, "media_player", ""))
                    latest_pic = latest_st.attributes.get("entity_picture") if latest_st else None
                    if latest_pic and latest_pic != picture:
                        try:
                            result = await self.image_processor.get_image(latest_pic, media_data, is_slide_pass)
                            if result:
                                if latest_pic.startswith("https://") and "/api/media_player_proxy/" not in latest_pic:
                                    media_data.original_image_url = latest_pic
                                self._save_to_artwork_cache(song_cache_key, latest_pic, "Original")
                                await self._persist_master_artwork(storage_cache_key, result, "Original", getattr(media_data, "original_image_url", None))
                                media_data.pic_source = "Original"
                                media_data.pic_url = latest_pic
                                return result
                        except Exception as e:
                            _LOGGER.debug("Retry attempt fetching original artwork failed: %s", e)

            if getattr(self.config, "spotify_client_id", None) and getattr(self.config, "spotify_client_secret", None):
                sp_res = await self._try_sequential_spotify(media_data, is_slide_pass, song_cache_key, storage_cache_key, tier1_only=True)
                if sp_res:
                    return sp_res

        race_res = await self._run_provider_tasks(
            picture if use_race_mode else None, use_race_mode, media_data, known_album, is_slide_pass, song_cache_key, storage_cache_key
        )
        if race_res:
            return race_res

        if not use_race_mode and getattr(self.config, "spotify_client_id", None) and getattr(self.config, "spotify_client_secret", None):
            sp_fallback = await self._try_sequential_spotify(media_data, is_slide_pass, song_cache_key, storage_cache_key, tier1_only=False)
            if sp_fallback:
                return sp_fallback

        if not getattr(self.config, "force_ai", False) and getattr(self.config, "audiodb_enabled", True):
            for img_url in await self.audiodb_provider.get_artist_images(media_data.artist):
                proc_result = await self.image_processor.get_image(img_url, media_data, is_slide_pass)
                if proc_result:
                    self._save_to_artwork_cache(song_cache_key, img_url, "TheAudioDB")
                    await self._persist_master_artwork(storage_cache_key, proc_result, "TheAudioDB", img_url)
                    media_data.pic_url = img_url
                    if img_url.startswith("https://"):
                        media_data.original_image_url = img_url
                    media_data.pic_source = "TheAudioDB"
                    return proc_result

        if not getattr(self.config, "force_ai", False) and getattr(self.config, "pollinations", None):
            result = await self._try_ai_generation(media_data)
            if result:
                if media_data.pic_url:
                    self._save_to_artwork_cache(song_cache_key, media_data.pic_url, "AI")
                    if media_data.pic_url.startswith("https://"):
                        media_data.original_image_url = media_data.pic_url
                await self._persist_master_artwork(storage_cache_key, result, "AI", getattr(media_data, "original_image_url", None))
                media_data.pic_source = "AI"
                return result

        if picture and is_generic_logo:
            try:
                res = await self.image_processor.get_image(picture, media_data, is_slide_pass)
                if res:
                    self._save_to_artwork_cache(song_cache_key, picture, "Radio Logo")
                    media_data.pic_source = "Radio Logo"
                    media_data.pic_url = picture
                    return res
            except Exception as e:
                _LOGGER.debug("Radio logo fallback processing note: %s", e)
        return None

    async def _try_sequential_spotify(
        self, media_data: "MediaData", is_slide_pass: bool, song_cache_key: str, storage_cache_key: str, tier1_only: bool = False
    ) -> Optional[dict]:
        try:
            album_id, first_album = await self.spotify_service.get_spotify_album_id(media_data)
            if tier1_only:
                if not album_id or getattr(self.spotify_service, "last_match_tier", 1) != 1:
                    return None
                url = await self.spotify_service.get_spotify_album_image_url(album_id)
                candidates = [(url, "Spotify")] if url else []
            else:
                candidates = []
                if album_id:
                    candidates.append((await self.spotify_service.get_spotify_album_image_url(album_id), "Spotify"))
                if first_album and first_album != album_id:
                    candidates.append((await self.spotify_service.get_spotify_album_image_url(first_album), "Spotify"))
                candidates.append((await self.spotify_service.get_spotify_artist_image_url_by_name(media_data.artist), "Spotify Artist"))
            for url, label in candidates:
                if url:
                    res = await self.image_processor.get_image(url, media_data, is_slide_pass)
                    if res:
                        self._save_to_artwork_cache(song_cache_key, url, label)
                        await self._persist_master_artwork(storage_cache_key, res, label, url)
                        if label != "Spotify Artist":
                            media_data.pic_url = url
                        if url.startswith("https://"):
                            media_data.original_image_url = url
                        media_data.pic_source = label
                        return res
        except Exception as e:
            _LOGGER.error("Spotify fallback failed: %s", e)
        return None

    async def _run_provider_tasks(
        self, race_picture: Optional[str], include_spotify: bool, media_data: "MediaData", known_album: Optional[str], is_slide_pass: bool, song_cache_key: str, storage_cache_key: str
    ) -> Optional[dict]:
        tasks = []
        provider_specs = [
            ("Discogs", bool(getattr(self.config, "discogs", None)), self.discogs_provider.search_album_art),
            ("Last.FM", bool(getattr(self.config, "lastfm", None)), self.lastfm_provider.search_album_art),
            ("TIDAL", bool(getattr(self.config, "tidal_client_id", None) and getattr(self.config, "tidal_client_secret", None)), self.tidal_provider.get_album_art_url),
            ("MusicBrainz", bool(getattr(self.config, "musicbrainz", False)), self.mb_provider.get_album_art_url),
            ("Internet Archive", bool(getattr(self.config, "internet_archive", False)), self.ia_provider.search_artwork),
        ]
        has_other_providers = bool(include_spotify or any(p[1] for p in provider_specs))
        is_generic_logo = getattr(media_data, "playing_radio", False) and getattr(media_data, "radio_logo", False)
        if race_picture and not is_generic_logo:
            async def _fetch_orig():
                res = await self.image_processor.get_image(race_picture, media_data, is_slide_pass)
                if not res and ("/api/media_player_proxy/" in race_picture or getattr(media_data, "playing_radio", False)):
                    latest_st = self.image_processor.hass.states.get(getattr(self.config, "media_player", ""))
                    retry_pic = (latest_st.attributes.get("entity_picture") if latest_st else None)
                    if retry_pic and retry_pic != race_picture:
                        res = await self.image_processor.get_image(retry_pic, media_data, is_slide_pass)
                tier = 2 if has_other_providers else 1
                return (res, race_picture, "Original", tier) if res else None
            tasks.append(_fetch_orig())

        if include_spotify and getattr(self.config, "spotify_client_id", None) and getattr(self.config, "spotify_client_secret", None):
            async def _fetch_sp():
                alb_id, first_alb = await self.spotify_service.get_spotify_album_id(media_data)
                target = alb_id or first_alb
                img_url = await self.spotify_service.get_spotify_album_image_url(target) if target else None
                if img_url and (res := await self.image_processor.get_image(img_url, media_data, is_slide_pass)):
                    return res, img_url, "Spotify", getattr(self.spotify_service, "last_match_tier", 1)
                return None
            tasks.append(_fetch_sp())

        async def _fetch_generic(provider_name: str, coro):
            try:
                res_data = await coro
                if not res_data:
                    return None
                url, base_tier = res_data if isinstance(res_data, tuple) else (res_data, 1)
                tier = 2 if provider_name in ("Discogs", "Internet Archive") else base_tier
                if url and (proc_res := await self.image_processor.get_image(url, media_data, is_slide_pass)):
                    return proc_res, url, provider_name, tier
            except Exception:
                pass
            return None

        for p_name, enabled, fn in provider_specs:
            if enabled:
                tasks.append(_fetch_generic(p_name, fn(media_data.artist, media_data.title, known_album, return_tier=True)))

        if not tasks:
            return None

        pending = {asyncio.create_task(t) for t in tasks}
        best_tier2, tier2_deadline = None, None
        while pending:
            timeout_left = max(0.05, tier2_deadline - time.monotonic()) if tier2_deadline is not None else None
            done, pending = await asyncio.wait(pending, timeout=timeout_left, return_when=asyncio.FIRST_COMPLETED)
            if not done and tier2_deadline is not None and time.monotonic() >= tier2_deadline:
                break
            for task in done:
                try:
                    res = task.result()
                    if res:
                        proc_result, url, provider_name, tier = res
                        if tier == 1:
                            for p in pending:
                                p.cancel()
                            self._save_to_artwork_cache(song_cache_key, url, provider_name)
                            await self._persist_master_artwork(storage_cache_key, proc_result, provider_name, url)
                            media_data.pic_url = url
                            if url.startswith("https://"):
                                media_data.original_image_url = url
                            media_data.pic_source = provider_name
                            return proc_result
                        if best_tier2 is None:
                            best_tier2 = (proc_result, url, provider_name)
                        if tier2_deadline is None:
                            tier2_deadline = time.monotonic() + 0.6
                except Exception:
                    pass

        for p in pending:
            p.cancel()
        if best_tier2:
            proc_result, url, provider_name = best_tier2
            self._save_to_artwork_cache(song_cache_key, url, provider_name)
            await self._persist_master_artwork(storage_cache_key, proc_result, provider_name, url)
            media_data.pic_url = url
            if url.startswith("https://"):
                media_data.original_image_url = url
            media_data.pic_source = provider_name
            return proc_result
        return None

    def _save_to_artwork_cache(self, key: str, url: str, source: str) -> None:
        if len(self._artwork_cache) >= 40:
            self._artwork_cache.popitem(last=False)
        self._artwork_cache[key] = {"url": url, "source": source}

    async def _try_ai_generation(self, media_data: "MediaData") -> Optional[dict]:
        ai_url = self.ai_provider.format_prompt_url(media_data.artist, media_data.title)
        if not ai_url:
            return None
        is_live = not getattr(media_data, "is_prefetch", False)
        if is_live and self.hub and hasattr(self.hub, "set_ai_generating"):
            self.hub.set_ai_generating(True, "Generating AI Artwork...")
        try:
            for attempt in range(3):
                try:
                    if is_live and self.hub and hasattr(self.hub, "set_ai_generating") and attempt > 0:
                        self.hub.set_ai_generating(True, f"Retrying AI Art ({attempt + 1}/3)...")
                    is_slide = getattr(media_data, "spotify_slide_pass", False) or getattr(media_data, "artist_slide_pass", False)
                    result = await asyncio.wait_for(self.image_processor.get_image(ai_url, media_data, is_slide), timeout=25)
                    if result:
                        media_data.pic_url = ai_url
                        media_data.pic_source = "AI"
                        return result
                except Exception as e:
                    _LOGGER.warning("AI generation failed: %s (Attempt %s/3)", e, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(1.5)
            return None
        finally:
            if is_live and self.hub and hasattr(self.hub, "set_ai_generating"):
                self.hub.set_ai_generating(False, "Idle")

    def _get_fallback_black_image_data(self, media_data: Optional["MediaData"] = None) -> dict:
        self.fail_txt = True
        self.fallback = True
        return create_fallback_black_image_data(self.image_processor, media_data)

    def create_tv_icon_image(self) -> Image.Image:
        return create_tv_icon_image()
