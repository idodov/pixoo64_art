"""Discogs album art provider."""

import logging
from typing import TYPE_CHECKING, Any, Optional
import aiohttp

from .base import BaseProvider, _is_album_match

if TYPE_CHECKING:
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class DiscogsProvider(BaseProvider):
    """Fetches album artwork from Discogs API."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession) -> None:
        self.config = config
        self.session = session

    async def search_album_art(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        return_tier: bool = False,
    ) -> Any:
        def _ret(url: Optional[str], tier: int = 2) -> Any:
            return (url, tier) if return_tier else url

        token = getattr(self.config, "discogs", None)
        if not token:
            return _ret(None, 2)

        clean_artist = str(artist or "").strip()
        clean_title = str(title or "").strip()
        clean_album = str(album or "").strip()
        has_known_album = bool(
            clean_album and clean_album.lower() not in ("unknown album", "unknown")
        )

        base_url = "https://api.discogs.com/database/search"
        headers = {
            "User-Agent": "AlbumArtSearchApp/1.0",
            "Authorization": f"Discogs token={token}",
        }

        try:
            if has_known_album:
                params_album = {
                    "artist": clean_artist,
                    "release_title": clean_album,
                    "track": clean_title,
                    "type": "release",
                    "per_page": 5,
                }
                async with self.session.get(
                    base_url, headers=headers, params=params_album, timeout=8
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("results", []):
                            cover = item.get("cover_image")
                            if cover and not cover.endswith("spacer.gif"):
                                return _ret(cover, 1)

            params = {
                "artist": clean_artist,
                "track": clean_title,
                "type": "release",
                "format": "album",
                "per_page": 10,
            }
            async with self.session.get(
                base_url, headers=headers, params=params, timeout=10
            ) as response:
                if response.status != 200:
                    _LOGGER.warning("Discogs API returned status %s", response.status)
                    return _ret(None, 2)
                data = await response.json()
                results = [
                    r
                    for r in data.get("results", [])
                    if r.get("cover_image")
                    and not r.get("cover_image", "").endswith("spacer.gif")
                ]
                if not results:
                    return _ret(None, 2)

                if has_known_album:
                    for r in results:
                        raw_t = str(r.get("title", ""))
                        rel_part = raw_t.split(" - ", 1)[-1] if " - " in raw_t else raw_t
                        if _is_album_match(clean_album, rel_part):
                            return _ret(r.get("cover_image"), 1)
                    return _ret(results[0].get("cover_image"), 2)

                return _ret(results[0].get("cover_image"), 1)
        except Exception as e:
            _LOGGER.error("Discogs search exception: %s", e)
            return _ret(None, 2)
