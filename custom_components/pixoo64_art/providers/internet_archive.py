"""Internet Archive audio cover artwork provider."""

import logging
from typing import Any, Optional
import aiohttp

from .base import BaseProvider, _is_album_match

_LOGGER = logging.getLogger(__name__)


class InternetArchiveProvider(BaseProvider):
    """Searches the Internet Archive (archive.org) for metadata and album/item cover art."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def search_artwork(
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
        has_known_album = bool(
            clean_album and clean_album.lower() not in ("unknown album", "unknown")
        )

        if not clean_artist or not clean_title or clean_artist == "Unknown Artist":
            return _ret(None, 2)

        target_title = clean_album if has_known_album else clean_title
        query = f'artist:( "{clean_artist}" ) AND title:( "{target_title}" )'
        search_url = "https://archive.org/advancedsearch.php"
        params = {
            "q": query,
            "fl[]": ["identifier", "title"],
            "rows": 3,
            "page": 1,
            "output": "json",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        try:
            async with self.session.get(
                search_url, params=params, headers=headers, timeout=8
            ) as response:
                if response.status != 200:
                    return _ret(None, 2)

                data = await response.json(content_type=None)
                docs = data.get("response", {}).get("docs", [])
                if not docs:
                    return _ret(None, 2)

                for doc in docs:
                    identifier = doc.get("identifier")
                    doc_title = doc.get("title", "")
                    if not identifier:
                        continue

                    tier = (
                        1
                        if (not has_known_album or _is_album_match(clean_album, doc_title))
                        else 2
                    )
                    meta_url = f"https://archive.org/metadata/{identifier}"
                    async with self.session.get(
                        meta_url, headers=headers, timeout=8
                    ) as meta_resp:
                        if meta_resp.status != 200:
                            continue
                        meta_data = await meta_resp.json(content_type=None)
                        files = meta_data.get("files", [])

                        for file_info in files:
                            name = file_info.get("name", "").lower()
                            if name.endswith((".jpg", ".jpeg", ".png")) and (
                                "cover" in name or "thumb" in name or "front" in name
                            ):
                                return _ret(
                                    f"https://archive.org/download/{identifier}/{file_info.get('name')}",
                                    tier,
                                )

                        for file_info in files:
                            name = file_info.get("name", "").lower()
                            if name.endswith((".jpg", ".jpeg", ".png")):
                                return _ret(
                                    f"https://archive.org/download/{identifier}/{file_info.get('name')}",
                                    tier,
                                )

        except Exception as e:
            _LOGGER.debug("Internet Archive search exception: %s", e)

        return _ret(None, 2)
