"""Tidal OAuth and OpenAPI artwork provider."""

import base64
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Optional
import aiohttp

from .base import BaseProvider, _album_match_score, _is_album_match

if TYPE_CHECKING:
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class TidalProvider(BaseProvider):
    """Fetches album and track cover art from Tidal OpenAPI."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession) -> None:
        self.config = config
        self.session = session
        self.token_cache: dict[str, Any] = {"token": None, "expires": 0}

    def _format_uuid(self, val: Any) -> Optional[str]:
        if not val or not isinstance(val, str):
            return None
        cleaned = val.strip().replace("-", "").replace("/", "")
        if len(cleaned) == 32 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
            return f"{cleaned[:8]}/{cleaned[8:12]}/{cleaned[12:16]}/{cleaned[16:20]}/{cleaned[20:]}"
        return None

    def _ensure_320_resolution(self, url: str) -> str:
        if url and "resources.tidal.com" in url:
            return re.sub(r"\d+x\d+", "320x320", url)
        return url

    def _extract_image(self, item: dict) -> Optional[str]:
        if not isinstance(item, dict):
            return None
        attrs = item.get("attributes", {})

        for key in ["files", "imageLinks", "images"]:
            links = attrs.get(key)
            if isinstance(links, list) and links:
                for candidate in links:
                    if isinstance(candidate, dict):
                        href = candidate.get("href") or candidate.get("url")
                        meta = candidate.get("meta", {})
                        if (meta.get("width") == 320) or (href and "320x320" in href):
                            return self._ensure_320_resolution(href)
                for candidate in reversed(links):
                    if isinstance(candidate, dict):
                        href = candidate.get("href") or candidate.get("url")
                        if href and isinstance(href, str) and href.startswith("http"):
                            return self._ensure_320_resolution(href)

        for key in ["href", "url", "image", "picture"]:
            val = attrs.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return self._ensure_320_resolution(val)

        item_type = str(item.get("type", "")).lower()
        if item_type in ["artworks", "artwork", "coverart"]:
            uuid_path = self._format_uuid(item.get("id"))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        for cover_key in ["cover", "coverArt", "imageCover"]:
            uuid_path = self._format_uuid(attrs.get(cover_key))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        cover_data = item.get("relationships", {}).get("coverArt", {}).get("data")
        if isinstance(cover_data, dict):
            uuid_path = self._format_uuid(cover_data.get("id"))
            if uuid_path:
                return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"
        elif isinstance(cover_data, list):
            for entry in cover_data:
                if isinstance(entry, dict):
                    uuid_path = self._format_uuid(entry.get("id"))
                    if uuid_path:
                        return f"https://resources.tidal.com/images/{uuid_path}/320x320.jpg"

        return None

    async def get_access_token(self) -> Optional[str]:
        if self.token_cache["token"] and time.time() < self.token_cache["expires"]:
            return self.token_cache["token"]

        client_id = str(self.config.tidal_client_id).strip()
        client_secret = str(self.config.tidal_client_secret).strip()
        if not client_id or not client_secret:
            return None

        url = "https://auth.tidal.com/v1/oauth2/token"
        auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        tidal_headers = {
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {"grant_type": "client_credentials"}

        try:
            async with self.session.post(
                url, headers=tidal_headers, data=payload, timeout=10
            ) as response:
                if response.status != 200:
                    _LOGGER.error("TIDAL Token Auth failed: %s", response.status)
                    return None
                response_json = await response.json()
                access_token = response_json["access_token"]
                expiry_time = time.time() + response_json.get("expires_in", 3600) - 60
                self.token_cache = {"token": access_token, "expires": expiry_time}
                return access_token
        except Exception as e:
            _LOGGER.error("TIDAL token exception: %s", e)
            return None

    def _resolve_album_artwork_from_included(
        self, album_item: dict, artworks_by_id: dict[str, dict]
    ) -> Optional[str]:
        direct = self._extract_image(album_item)
        if direct:
            return direct
        rel_data = album_item.get("relationships", {}).get("coverArt", {}).get("data")
        if isinstance(rel_data, dict):
            rel_data = [rel_data]
        if isinstance(rel_data, list):
            for entry in rel_data:
                if isinstance(entry, dict):
                    art_id = str(entry.get("id", ""))
                    if art_id in artworks_by_id:
                        url = self._extract_image(artworks_by_id[art_id])
                        if url:
                            return url
        return None

    async def get_album_art_url(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        return_tier: bool = False,
    ) -> Any:
        def _ret(url: Optional[str], tier: int = 2) -> Any:
            return (url, tier) if return_tier else url

        access_token = await self.get_access_token()
        if not access_token:
            return _ret(None, 2)

        clean_artist = str(artist).strip() if artist and artist != "Unknown Artist" else ""
        clean_title = str(title).strip() if title and title != "Unknown Track" else ""
        clean_album = str(album).strip() if album and album != "Unknown Album" else ""
        has_known_album = bool(clean_album)

        query = (
            f"{clean_artist} {clean_title} {clean_album}".strip()
            if has_known_album
            else f"{clean_artist} {clean_title}".strip()
        )
        if len(query) < 2 or query == "-":
            return _ret(None, 2)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.api+json",
        }
        search_url = "https://openapi.tidal.com/v2/searchResults"
        search_params = {
            "countryCode": "US",
            "filter[query]": query,
            "include": "tracks.albums.coverArt,albums.coverArt",
        }

        try:
            async with self.session.get(
                search_url, headers=headers, params=search_params, timeout=10
            ) as response:
                if response.status != 200:
                    return _ret(None, 2)
                search_data = await response.json()
                included_items = search_data.get("included", [])

                albums_by_id: dict[str, dict] = {}
                artworks_by_id: dict[str, dict] = {}
                tracks_list: list[dict] = []

                for inc in included_items:
                    if not isinstance(inc, dict):
                        continue
                    inc_type = str(inc.get("type", "")).lower()
                    inc_id = str(inc.get("id", ""))
                    if inc_type == "albums" and inc_id:
                        albums_by_id[inc_id] = inc
                    elif inc_type in ("artworks", "artwork", "coverart") and inc_id:
                        artworks_by_id[inc_id] = inc
                    elif inc_type == "tracks":
                        tracks_list.append(inc)

                if has_known_album and albums_by_id:
                    scored_albums = sorted(
                        albums_by_id.values(),
                        key=lambda a: _album_match_score(
                            clean_album, a.get("attributes", {}).get("title", "")
                        ),
                        reverse=True,
                    )
                    best_alb = scored_albums[0]
                    if _is_album_match(
                        clean_album, best_alb.get("attributes", {}).get("title", "")
                    ):
                        img_url = self._resolve_album_artwork_from_included(
                            best_alb, artworks_by_id
                        )
                        if img_url:
                            return _ret(img_url, 1)

                for trk in tracks_list:
                    trk_title = trk.get("attributes", {}).get("title", "")
                    if clean_title and _album_match_score(clean_title, trk_title) >= 0.65:
                        rel_albums = (
                            trk.get("relationships", {})
                            .get("albums", {})
                            .get("data", [])
                        )
                        if isinstance(rel_albums, dict):
                            rel_albums = [rel_albums]
                        for rel_a in rel_albums:
                            alb_id = str(rel_a.get("id", ""))
                            if alb_id in albums_by_id:
                                alb_obj = albums_by_id[alb_id]
                                alb_title = alb_obj.get("attributes", {}).get("title", "")
                                img_url = self._resolve_album_artwork_from_included(
                                    alb_obj, artworks_by_id
                                )
                                if img_url:
                                    tier = (
                                        1
                                        if (
                                            not has_known_album
                                            or _is_album_match(clean_album, alb_title)
                                        )
                                        else 2
                                    )
                                    return _ret(img_url, tier)

                fallback_tier = 2 if has_known_album else 1
                for alb_obj in albums_by_id.values():
                    img_url = self._resolve_album_artwork_from_included(
                        alb_obj, artworks_by_id
                    )
                    if img_url:
                        return _ret(img_url, fallback_tier)

                for art_obj in artworks_by_id.values():
                    img_url = self._extract_image(art_obj)
                    if img_url:
                        return _ret(img_url, fallback_tier)

                return _ret(None, 2)
        except Exception as e:
            _LOGGER.warning("TIDAL search exception: %s", e)
            return _ret(None, 2)
