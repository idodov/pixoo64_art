"""Persistent hybrid storage manager (SQLite WAL + Local Filesystem) for Pixoo64."""
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
from io import BytesIO
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from PIL import Image, UnidentifiedImageError
from homeassistant.core import HomeAssistant

from .analytics import PixooAnalytics
from .database import PixooDatabase, generate_artist_cache_key, generate_artwork_cache_key, normalize_string

if TYPE_CHECKING:
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class PixooStorageManager:
    """Manages persistent 300x300 album masters, 64x64 artist sliders, LRU pruning, and analytics."""

    def __init__(self, hass: HomeAssistant, config: Optional["Config"] = None):
        self.hass, self.config = hass, config
        self.base_dir = hass.config.path(".storage", "pixoo64")
        self.masters_dir = os.path.join(self.base_dir, "masters")
        self.artists_dir = os.path.join(self.base_dir, "artists")
        self.icons_dir = os.path.join(self.base_dir, "icons")
        self.db_path = os.path.join(self.base_dir, "pixoo_data.db")
        self._lock = asyncio.Lock()
        self.db = PixooDatabase(self.base_dir, self.db_path)
        self.analytics = PixooAnalytics(self.db)

    @property
    def is_cache_enabled(self) -> bool:
        return True if self.config is None else bool(getattr(self.config, "enable_persistent_cache", True))

    async def _run_locked(self, fn: Callable, *args: Any, default: Any = None) -> Any:
        async with self._lock:
            try:
                if not self.db.initialized:
                    await self.hass.async_add_executor_job(
                        self.db.initialize_sync, self.masters_dir, self.artists_dir, self.icons_dir
                    )
                return await self.hass.async_add_executor_job(fn, *args)
            except (UnidentifiedImageError, OSError) as err:
                _LOGGER.debug("Storage I/O error in %s: %s", getattr(fn, "__name__", "fn"), err)
                return default
            except Exception as err:
                _LOGGER.error("Storage error in %s: %s", getattr(fn, "__name__", "fn"), err)
                return default

    async def async_initialize(self) -> None:
        if self.is_cache_enabled:
            await self._run_locked(self.db.initialize_sync, self.masters_dir, self.artists_dir, self.icons_dir)

    @staticmethod
    def _deserialize_palette(palette_json: str) -> dict:
        try:
            palette_data = json.loads(palette_json)
            if not isinstance(palette_data, dict):
                return {}
            if isinstance(palette_data.get("background_color_rgb"), list):
                palette_data["background_color_rgb"] = tuple(palette_data["background_color_rgb"])
            if isinstance(palette_data.get("palette"), list):
                palette_data["palette"] = [
                    tuple(c) if isinstance(c, list) else c for c in palette_data["palette"]
                ]
            return palette_data
        except Exception:
            return {}

    def _resolve_path(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(self.base_dir, p)

    def _get_master_sync(self, cache_key: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_path, source, palette_json FROM artwork_masters WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            file_path, source, palette_json = row
            resolved_path = self._resolve_path(file_path)
            if not os.path.isfile(resolved_path):
                conn.execute("DELETE FROM artwork_masters WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None
            try:
                with open(resolved_path, "rb") as f:
                    image_bytes = f.read()
            except OSError:
                return None
            if not image_bytes:
                return None
            conn.execute(
                "UPDATE artwork_masters SET last_accessed = ? WHERE cache_key = ?", (now, cache_key)
            )
            conn.commit()
            return {
                "image_bytes": image_bytes,
                "source": source,
                "palette": self._deserialize_palette(palette_json),
            }

    async def async_get_master(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve master artwork record and update last_accessed timestamp."""
        if not cache_key or not self.is_cache_enabled:
            return None
        return await self._run_locked(self._get_master_sync, cache_key, default=None)

    def _save_master_sync(
        self, cache_key: str, raw_image: Union[bytes, Image.Image], source: str, palette: dict
    ) -> None:
        os.makedirs(self.masters_dir, exist_ok=True)
        if isinstance(raw_image, Image.Image):
            img = raw_image.convert("RGB") if raw_image.mode != "RGB" else raw_image.copy()
        else:
            with Image.open(BytesIO(raw_image)) as opened:
                opened.load()
                img = opened.convert("RGB") if opened.mode != "RGB" else opened.copy()
        img.thumbnail((300, 300), Image.Resampling.BILINEAR)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)

        file_hash = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
        abs_path = os.path.join(self.masters_dir, f"{file_hash}.jpg")
        with open(abs_path, "wb") as f:
            f.write(buf.getvalue())

        now = int(time.time())
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO artwork_masters (cache_key, file_path, source, palette_json, created_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    file_path = excluded.file_path,
                    source = excluded.source,
                    palette_json = excluded.palette_json,
                    last_accessed = excluded.last_accessed
                """,
                (cache_key, abs_path, str(source or "Unknown"), json.dumps(palette or {}), now, now),
            )
            conn.commit()
            max_masters = int(getattr(self.config, "max_cached_albums", 1000) if self.config else 1000)
            self._enforce_masters_lru(conn, max_masters)

    async def async_save_master(
        self, cache_key: str, raw_image_bytes: Union[bytes, Image.Image], source: str, palette: dict
    ) -> None:
        """Compress image to 300x300 JPEG, save to /masters/{hash}.jpg, and upsert artwork_masters."""
        if cache_key and raw_image_bytes and self.is_cache_enabled:
            await self._run_locked(self._save_master_sync, cache_key, raw_image_bytes, source, palette)

    def _get_artist_slider_sync(self, artist_key: str) -> Optional[List[bytes]]:
        now = int(time.time())
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT frames_dir, frame_count FROM artist_sliders WHERE artist_key = ?", (artist_key,)
            ).fetchone()
            if not row:
                return None
            resolved_dir = self._resolve_path(row[0])
            if not os.path.isdir(resolved_dir):
                conn.execute("DELETE FROM artist_sliders WHERE artist_key = ?", (artist_key,))
                conn.commit()
                return None
            frame_files = sorted(
                f for f in os.listdir(resolved_dir) if f.startswith("frame_") and f.lower().endswith(".jpg")
            )
            frames: List[bytes] = []
            for fname in frame_files:
                try:
                    with open(os.path.join(resolved_dir, fname), "rb") as f:
                        data = f.read()
                        if data:
                            frames.append(data)
                except OSError:
                    continue
            if len(frames) < 2:
                conn.execute("DELETE FROM artist_sliders WHERE artist_key = ?", (artist_key,))
                conn.commit()
                return None
            conn.execute(
                "UPDATE artist_sliders SET last_accessed = ? WHERE artist_key = ?", (now, artist_key)
            )
            conn.commit()
            return frames

    async def async_get_artist_slider(self, artist_key: str) -> Optional[List[bytes]]:
        """Retrieve ordered list of 64x64 frame bytes from disk for the given artist."""
        if not artist_key or not self.is_cache_enabled:
            return None
        return await self._run_locked(self._get_artist_slider_sync, artist_key, default=None)

    def _save_artist_slider_sync(
        self, artist_key: str, frames_list: List[Union[bytes, Image.Image]], source_urls: List[str]
    ) -> None:
        clean_part = artist_key.split(":", 1)[-1] if ":" in artist_key else artist_key
        folder_hash = hashlib.md5(clean_part.encode("utf-8")).hexdigest()
        artist_folder = os.path.join(self.artists_dir, folder_hash)
        if os.path.isdir(artist_folder):
            shutil.rmtree(artist_folder, ignore_errors=True)
        os.makedirs(artist_folder, exist_ok=True)

        saved_count = 0
        for idx, raw_frame in enumerate(frames_list[:10]):
            if not raw_frame:
                continue
            try:
                if isinstance(raw_frame, Image.Image):
                    img = raw_frame.convert("RGB") if raw_frame.mode != "RGB" else raw_frame.copy()
                else:
                    with Image.open(BytesIO(raw_frame)) as opened:
                        opened.load()
                        img = opened.convert("RGB") if opened.mode != "RGB" else opened.copy()
                if img.size != (64, 64):
                    w, h = img.size
                    if w != h:
                        side = min(w, h)
                        img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
                    img = img.resize((64, 64), Image.Resampling.BILINEAR)
                img.save(os.path.join(artist_folder, f"frame_{saved_count:02d}.jpg"), format="JPEG", quality=85)
                saved_count += 1
            except Exception as err:
                _LOGGER.debug("Skipping invalid slider frame %d for %s: %s", idx, artist_key, err)

        if saved_count < 2:
            shutil.rmtree(artist_folder, ignore_errors=True)
            return

        now = int(time.time())
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO artist_sliders (artist_key, frames_dir, frame_count, source_urls_json, created_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(artist_key) DO UPDATE SET
                    frames_dir = excluded.frames_dir,
                    frame_count = excluded.frame_count,
                    source_urls_json = excluded.source_urls_json,
                    last_accessed = excluded.last_accessed
                """,
                (artist_key, artist_folder, saved_count, json.dumps(list(source_urls or [])[:10]), now, now),
            )
            conn.commit()

    async def async_save_artist_slider(
        self, artist_key: str, frames_bytes_list: List[Union[bytes, Image.Image]], source_urls: List[str]
    ) -> None:
        """Save each frame as 64x64 JPEG in /artists/{hash}/frame_XX.jpg and upsert artist_sliders."""
        if artist_key and frames_bytes_list and len(frames_bytes_list) >= 2 and self.is_cache_enabled:
            await self._run_locked(self._save_artist_slider_sync, artist_key, frames_bytes_list, source_urls)

    def _load_64_img(self, path: str) -> Optional[Image.Image]:
        r_path = self._resolve_path(path)
        if os.path.isfile(r_path):
            try:
                with Image.open(r_path) as im:
                    return im.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
            except Exception:
                pass
        return None

    def _get_chart_artwork_sync(self, item: Dict[str, Any], chart_type: str) -> Optional[Image.Image]:
        """Resolve local-only 64x64 artwork for a chart entry without any network calls."""
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        album = str(item.get("album") or "").strip()
        clean_artist = normalize_string(artist) or "unknown"

        with self.db.get_connection() as conn:
            if chart_type == "Top Artists":
                row = conn.execute(
                    "SELECT frames_dir FROM artist_sliders WHERE artist_key = ?",
                    (generate_artist_cache_key(artist),),
                ).fetchone()
                if row:
                    img = self._load_64_img(os.path.join(self._resolve_path(row[0]), "frame_00.jpg"))
                    if img:
                        return img

            for c_key in [
                generate_artwork_cache_key(artist, album, title) if album else None,
                generate_artwork_cache_key(artist, None, title) if title else None,
            ]:
                if not c_key:
                    continue
                row = conn.execute("SELECT file_path FROM artwork_masters WHERE cache_key = ?", (c_key,)).fetchone()
                if row:
                    img = self._load_64_img(row[0])
                    if img:
                        return img

            if clean_artist != "unknown":
                rows = conn.execute(
                    "SELECT file_path FROM artwork_masters WHERE cache_key LIKE ? OR cache_key LIKE ? ORDER BY last_accessed DESC LIMIT 1",
                    (f"album:{clean_artist}_%", f"track:{clean_artist}_%"),
                ).fetchall()
                for (f_path,) in rows:
                    img = self._load_64_img(f_path)
                    if img:
                        return img
        return None

    async def async_get_chart_artwork(self, item: Dict[str, Any], chart_type: str) -> Optional[Image.Image]:
        return await self._run_locked(self._get_chart_artwork_sync, item, chart_type, default=None)

    async def async_record_playback(self, artist: str, title: str, album: Optional[str] = None, source: str = "stream") -> None:
        if artist and title and artist not in ("Unknown Artist", "TV") and title not in ("Unknown Track", "TV"):
            await self._run_locked(self.analytics.record_playback_sync, artist, title, album, None, source)

    async def async_record_album_completion(self, album_key: str, artist: str, album: str, release_type: str = "album") -> None:
        if artist and album:
            await self._run_locked(self.analytics.record_album_completion_sync, artist, album, album_key, None, release_type)

    async def async_get_top_tracks(self, period: str = "week", limit: int = 10) -> List[Dict[str, Any]]:
        return await self._run_locked(self.analytics.get_top_tracks_sync, period, limit, default=[])

    async def async_get_available_periods(self, timeframe: str = "Weekly", first_day_of_week: str = "Sunday", chart_type: Optional[str] = None) -> List[str]:
        return await self._run_locked(self.analytics.get_available_periods_sync, timeframe, first_day_of_week, chart_type, default=[])

    async def async_get_chart_metadata(self, first_day_of_week: str = "Sunday") -> Dict[str, Any]:
        return await self._run_locked(self.analytics.get_chart_metadata_sync, first_day_of_week, default={
            "available_types": [],
            "available_timeframes": [],
            "periods_by_timeframe": {},
            "periods_by_type_tf": {},
            "days_since_first_play": 0.0,
            "total_plays": 0,
        })

    async def async_get_leaderboard(
        self, chart_type: str = "Top Tracks", timeframe: str = "Weekly", period_label: str = "Current", limit: int = 10, first_day_of_week: str = "Sunday"
    ) -> List[Dict[str, Any]]:
        return await self._run_locked(self.analytics.get_leaderboard_sync, chart_type, timeframe, period_label, limit, first_day_of_week, default=[])

    async def async_get_analytics_summary(self) -> Dict[str, Any]:
        return await self._run_locked(self.analytics.get_analytics_summary_sync, default={})

    async def async_get_track_stats(self, artist: str, title: str) -> Dict[str, Any]:
        return await self._run_locked(self.analytics.get_track_stats_sync, artist, title, default={"plays": 0, "first_played": None, "last_played": None})

    def _get_icon_sync(self, icon_key: str) -> Optional[Tuple[bytes, int]]:
        now = int(time.time())
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_path, speed_ms FROM pixel_icons WHERE icon_key = ?",
                (icon_key,),
            ).fetchone()
            if not row:
                return None
            file_path, speed_ms = row
            resolved_path = self._resolve_path(file_path)
            if not os.path.isfile(resolved_path):
                conn.execute("DELETE FROM pixel_icons WHERE icon_key = ?", (icon_key,))
                conn.commit()
                return None
            try:
                with open(resolved_path, "rb") as f:
                    icon_bytes = f.read()
            except OSError:
                return None
            if not icon_bytes:
                return None
            conn.execute(
                "UPDATE pixel_icons SET last_accessed = ? WHERE icon_key = ?",
                (now, icon_key),
            )
            conn.commit()
            return icon_bytes, speed_ms

    async def async_get_icon(self, icon_key: str) -> Optional[Tuple[bytes, int]]:
        if not self.is_cache_enabled:
            return None
        return await self._run_locked(self._get_icon_sync, icon_key)

    def _save_icon_sync(
        self,
        icon_key: str,
        data: bytes,
        source: str,
        frame_count: int,
        speed_ms: int,
        width: int,
        height: int,
    ) -> None:
        now = int(time.time())
        safe_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", icon_key)
        rel_path = os.path.join("icons", f"{safe_key}.cache")
        abs_path = os.path.join(self.icons_dir, f"{safe_key}.cache")
        try:
            with open(abs_path, "wb") as f:
                f.write(data)
        except OSError as err:
            _LOGGER.debug("Failed to write icon file '%s': %s", abs_path, err)
            return

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO pixel_icons (icon_key, file_path, source, frame_count, speed_ms, width, height, created_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(icon_key) DO UPDATE SET
                    file_path = excluded.file_path,
                    source = excluded.source,
                    frame_count = excluded.frame_count,
                    speed_ms = excluded.speed_ms,
                    width = excluded.width,
                    height = excluded.height,
                    last_accessed = excluded.last_accessed
                """,
                (icon_key, rel_path, source, frame_count, speed_ms, width, height, now, now),
            )
            self._enforce_icons_lru(conn, max_icons=500)
            conn.commit()

    def _enforce_icons_lru(self, conn, max_icons: int = 500) -> None:
        if max_icons <= 0:
            return
        icon_count = conn.execute("SELECT COUNT(*) FROM pixel_icons").fetchone()[0] or 0
        if icon_count > max_icons:
            evicted = conn.execute(
                "SELECT icon_key, file_path FROM pixel_icons ORDER BY last_accessed ASC LIMIT ?",
                (icon_count - max_icons,),
            ).fetchall()
            for key, path in evicted:
                resolved = self._resolve_path(path)
                try:
                    if os.path.isfile(resolved):
                        os.remove(resolved)
                except OSError:
                    pass
                conn.execute("DELETE FROM pixel_icons WHERE icon_key = ?", (key,))

    async def async_save_icon(
        self,
        icon_key: str,
        data: bytes,
        source: str = "custom",
        frame_count: int = 1,
        speed_ms: int = 120,
        width: int = 16,
        height: int = 16,
    ) -> None:
        if not self.is_cache_enabled:
            return
        await self._run_locked(
            self._save_icon_sync,
            icon_key,
            data,
            source,
            frame_count,
            speed_ms,
            width,
            height,
        )

    def _clear_cache_sync(self, scope: str = "all") -> None:
        norm_scope = str(scope or "all").strip().lower()
        if norm_scope in ("all", "masters") and os.path.isdir(self.masters_dir):
            shutil.rmtree(self.masters_dir, ignore_errors=True)
            os.makedirs(self.masters_dir, exist_ok=True)
        if norm_scope in ("all", "artists") and os.path.isdir(self.artists_dir):
            shutil.rmtree(self.artists_dir, ignore_errors=True)
            os.makedirs(self.artists_dir, exist_ok=True)
        if norm_scope in ("all", "icons") and os.path.isdir(self.icons_dir):
            shutil.rmtree(self.icons_dir, ignore_errors=True)
            os.makedirs(self.icons_dir, exist_ok=True)
        with self.db.get_connection() as conn:
            if norm_scope in ("all", "masters"):
                conn.execute("DELETE FROM artwork_masters")
            if norm_scope in ("all", "artists"):
                conn.execute("DELETE FROM artist_sliders")
            if norm_scope in ("all", "icons"):
                conn.execute("DELETE FROM pixel_icons")
            if norm_scope in ("all", "analytics"):
                self.analytics.clear_analytics_on_conn(conn)
            conn.commit()
            if norm_scope == "all":
                conn.execute("VACUUM;")
            else:
                conn.execute("PRAGMA incremental_vacuum;")

        if norm_scope in ("all", "icons"):
            try:
                from ..renderers.notifications import LaMetricIconResolver
                LaMetricIconResolver.clear_memory_cache()
            except Exception:
                pass

    async def async_clear_cache(self, scope: str = "all") -> None:
        await self._run_locked(self._clear_cache_sync, scope)

    def _enforce_masters_lru(self, conn, max_masters: int) -> None:
        if max_masters <= 0:
            return
        master_count = conn.execute("SELECT COUNT(*) FROM artwork_masters").fetchone()[0] or 0
        if master_count > max_masters:
            evicted = conn.execute(
                "SELECT cache_key, file_path FROM artwork_masters ORDER BY last_accessed ASC LIMIT ?",
                (master_count - max_masters,),
            ).fetchall()
            for cache_key, file_path in evicted:
                resolved = self._resolve_path(file_path)
                try:
                    if os.path.isfile(resolved):
                        os.remove(resolved)
                except OSError:
                    pass
                conn.execute("DELETE FROM artwork_masters WHERE cache_key = ?", (cache_key,))
            conn.commit()

    def _prune_sync(self, max_masters: int = 1000, max_artists: int = 100, history_days: int = 365) -> None:
        now = int(time.time())
        with self.db.get_connection() as conn:
            self._enforce_masters_lru(conn, max_masters)
            self._enforce_icons_lru(conn, max_icons=500)
            artist_count = conn.execute("SELECT COUNT(*) FROM artist_sliders").fetchone()[0] or 0
            if artist_count > max_artists:
                evicted_artists = conn.execute(
                    "SELECT artist_key, frames_dir FROM artist_sliders ORDER BY last_accessed ASC LIMIT ?",
                    (artist_count - max_artists,),
                ).fetchall()
                for artist_key, frames_dir in evicted_artists:
                    resolved_dir = self._resolve_path(frames_dir)
                    if os.path.isdir(resolved_dir):
                        shutil.rmtree(resolved_dir, ignore_errors=True)
                    conn.execute("DELETE FROM artist_sliders WHERE artist_key = ?", (artist_key,))
            if history_days > 0:
                conn.execute("DELETE FROM play_history WHERE played_at < ?", (now - int(history_days * 86400),))
            if os.path.isdir(self.masters_dir):
                known_files = {
                    os.path.basename(row[0])
                    for row in conn.execute("SELECT file_path FROM artwork_masters").fetchall()
                    if row[0]
                }
                try:
                    for fname in os.listdir(self.masters_dir):
                        if fname.endswith(".jpg") and fname not in known_files:
                            try:
                                os.remove(os.path.join(self.masters_dir, fname))
                            except OSError:
                                pass
                except OSError:
                    pass
            conn.commit()
            conn.execute("PRAGMA incremental_vacuum;")

    async def async_prune(self, max_masters: Optional[int] = None, max_artists: int = 100, history_days: int = 365) -> None:
        effective = max_masters if max_masters is not None else int(getattr(self.config, "max_cached_albums", 1000) if self.config else 1000)
        await self._run_locked(self._prune_sync, effective, max_artists, history_days)
