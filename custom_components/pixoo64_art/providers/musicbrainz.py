"""MusicBrainz and Cover Art Archive provider."""

import asyncio
import time
from typing import Any, Optional
import aiohttp

from .base import BaseProvider, _album_match_score, _is_album_match


class MusicBrainzProvider(BaseProvider):
    """Queries MusicBrainz and Cover Art Archive for release artwork."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self._last_query_time: float = 0.0

    async def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_query_time
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)
        self._last_query_time = time.monotonic()

    async def get_album_art_url(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        return_tier: bool = False,
    ) -> Any:
        def _ret(url: Optional[str], tier: int = 2) -> Any:
            return (url, tier) if return_tier else url

        clean_artist = str(artist or "").replace('"', "").strip()
        clean_title = str(title or "").replace('"', "").strip()
        clean_album = str(album or "").replace('"', "").strip()
        has_known_album = bool(
            clean_album and clean_album.lower() not in ("unknown album", "unknown")
        )

        if not clean_artist or not clean_title:
            return _ret(None, 2)

        await self._throttle()

        search_url = "https://musicbrainz.org/ws/2/release/"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Pixoo64MediaArt/2.0 (https://github.com/idodov/pixoo64_art)",
        }

        query = f'artist:"{clean_artist}" AND recording:"{clean_title}"'
        query_with_album = (
            f'{query} AND release:"{clean_album}"' if has_known_album else None
        )

        try:
            releases = []
            matched_tier = 2 if has_known_album else 1

            if query_with_album:
                async with self.session.get(
                    search_url,
                    params={"query": query_with_album, "fmt": "json"},
                    headers=headers,
                    timeout=10,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        releases = data.get("releases", [])
                        if releases:
                            matched_tier = 1

            if not releases:
                await self._throttle()
                async with self.session.get(
                    search_url,
                    params={"query": query, "fmt": "json"},
                    headers=headers,
                    timeout=10,
                ) as response:
                    if response.status != 200:
                        return _ret(None, 2)
                    data = await response.json()
                    releases = data.get("releases", [])
                    if not releases:
                        return _ret(None, 2)

                    if has_known_album:
                        scored = sorted(
                            releases,
                            key=lambda r: _album_match_score(
                                clean_album, r.get("title", "")
                            ),
                            reverse=True,
                        )
                        if _is_album_match(clean_album, scored[0].get("title", "")):
                            releases = scored
                            matched_tier = 1
                        else:
                            matched_tier = 2

            for rel in releases[:3]:
                release_id = rel.get("id")
                if not release_id:
                    continue
                cover_art_url = f"https://coverartarchive.org/release/{release_id}"
                try:
                    async with self.session.get(
                        cover_art_url, headers=headers, timeout=12
                    ) as art_response:
                        if art_response.status != 200:
                            continue
                        art_data = await art_response.json()
                        for image in art_data.get("images", []):
                            if image.get("front", False):
                                thumb = image.get("thumbnails", {}).get(
                                    "250"
                                ) or image.get("image")
                                if thumb:
                                    return _ret(thumb, matched_tier)
                except Exception:
                    continue
            return _ret(None, 2)
        except Exception:
            return _ret(None, 2)
