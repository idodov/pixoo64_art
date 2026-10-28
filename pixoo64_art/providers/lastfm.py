"""Last.fm album and track artwork provider."""

import logging
import re
from typing import TYPE_CHECKING, Any, Optional
import aiohttp

from .base import BaseProvider, _album_match_score, _is_album_match, _normalize_album_name

if TYPE_CHECKING:
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class LastFmProvider(BaseProvider):
    """Queries Last.fm API for album and track artwork."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession) -> None:
        self.config = config
        self.session = session

    def _is_valid_image(self, url: Optional[str]) -> bool:
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        if not url.startswith("http"):
            return False
        if "2a96cbd8b46e442fc41c2b86b821562f" in url or "default_album" in url:
            return False
        return True

    def _optimize_url(self, url: str) -> str:
        if url and "fastly.net" in url:
            return re.sub(r"/i/u/(?:\d+s|\d+x\d+)/", "/i/u/300x300/", url)
        return url

    def _extract_image_url(self, image_list: list) -> Optional[str]:
        if not isinstance(image_list, list):
            return None
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

    async def search_album_art(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        return_tier: bool = False,
    ) -> Any:
        def _ret(url: Optional[str], tier: int = 2) -> Any:
            return (url, tier) if return_tier else url

        clean_artist = str(artist or "").strip()
        clean_title = str(title or "").strip()
        clean_album = str(album or "").strip()
        api_key = str(getattr(self.config, "lastfm", "") or "").strip()
        has_known_album = bool(
            clean_album and clean_album.lower() not in ("unknown album", "unknown")
        )

        if not clean_artist or clean_artist == "Unknown Artist" or not api_key:
            return _ret(None, 2)

        base_url = "https://ws.audioscrobbler.com/2.0/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        if has_known_album:
            params = {
                "method": "album.getInfo",
                "api_key": api_key,
                "artist": clean_artist,
                "album": clean_album,
                "autocorrect": 1,
                "format": "json",
            }
            try:
                async with self.session.get(
                    base_url, headers=headers, params=params, timeout=8
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        album_obj = data.get("album", {})
                        returned_album_name = album_obj.get("name", "")
                        images = album_obj.get("image", [])
                        valid_url = self._extract_image_url(images)

                        if valid_url and _is_album_match(clean_album, returned_album_name):
                            tracks_container = album_obj.get("tracks", {}).get("track", [])
                            if isinstance(tracks_container, dict):
                                tracks_container = [tracks_container]
                            if (
                                tracks_container
                                and clean_title
                                and clean_title != "Unknown Track"
                            ):
                                norm_title = _normalize_album_name(clean_title)
                                track_found = any(
                                    norm_title in _normalize_album_name(t.get("name", ""))
                                    or _normalize_album_name(t.get("name", ""))
                                    in norm_title
                                    for t in tracks_container
                                    if isinstance(t, dict) and t.get("name")
                                )
                                if (
                                    track_found
                                    or _album_match_score(clean_album, returned_album_name)
                                    >= 0.92
                                ):
                                    return _ret(valid_url, 1)
                            else:
                                return _ret(valid_url, 1)
            except Exception as e:
                _LOGGER.debug("Last.fm album.getInfo query error: %s", e)

        if clean_title and clean_title != "Unknown Track":
            params = {
                "method": "track.getInfo",
                "api_key": api_key,
                "artist": clean_artist,
                "track": clean_title,
                "autocorrect": 1,
                "format": "json",
            }
            try:
                async with self.session.get(
                    base_url, headers=headers, params=params, timeout=8
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        track_data = data.get("track", {})
                        album_obj = track_data.get("album", {})
                        discovered_album = album_obj.get("title", "")
                        images = album_obj.get("image", [])
                        valid_url = self._extract_image_url(images)

                        tier = 1
                        if has_known_album:
                            tier = (
                                1
                                if _is_album_match(clean_album, discovered_album)
                                else 2
                            )

                        if valid_url:
                            return _ret(valid_url, tier)

                        if discovered_album and discovered_album != clean_album:
                            alb_params = {
                                "method": "album.getInfo",
                                "api_key": api_key,
                                "artist": clean_artist,
                                "album": discovered_album,
                                "autocorrect": 1,
                                "format": "json",
                            }
                            async with self.session.get(
                                base_url, headers=headers, params=alb_params, timeout=8
                            ) as alb_response:
                                if alb_response.status == 200:
                                    alb_data = await alb_response.json()
                                    alb_images = (
                                        alb_data.get("album", {}).get("image", [])
                                    )
                                    valid_url = self._extract_image_url(alb_images)
                                    if valid_url:
                                        return _ret(valid_url, tier)
            except Exception as e:
                _LOGGER.error("Last.fm search exception: %s", e)

        return _ret(None, 2)
