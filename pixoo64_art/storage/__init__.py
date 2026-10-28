"""Persistence and playback analytics package for Pixoo64."""
from .analytics import (
    PixooAnalytics,
    PlaybackAnalyticsEngine,
    compute_track_fingerprint,
    format_week_label,
    get_week_bounds,
)
from .database import (
    SCHEMA_SQL,
    PixooDatabase,
    generate_artist_cache_key,
    generate_artwork_cache_key,
    normalize_string,
)
from .manager import PixooStorageManager

__all__ = [
    "SCHEMA_SQL",
    "PixooAnalytics",
    "PlaybackAnalyticsEngine",
    "PixooDatabase",
    "PixooStorageManager",
    "compute_track_fingerprint",
    "format_week_label",
    "generate_artist_cache_key",
    "generate_artwork_cache_key",
    "get_week_bounds",
    "normalize_string",
]
