"""SQLite database initialization, WAL configuration, schema, and key normalization."""
import os
import re
import shutil
import sqlite3
from typing import Optional

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA auto_vacuum = INCREMENTAL;
PRAGMA foreign_keys = ON;

-- 1. Master Artwork Metadata & Palette Cache
CREATE TABLE IF NOT EXISTS artwork_masters (
    cache_key TEXT PRIMARY KEY,          -- 'album:{artist}_{album}' or 'track:{artist}_{title}'
    file_path TEXT NOT NULL,             -- Relative or absolute path to 300x300 JPEG
    source TEXT NOT NULL,                -- 'Spotify', 'MusicBrainz', 'AI', etc.
    palette_json TEXT NOT NULL,          -- Serialized dict: color1, color2, color3, font_color, etc.
    created_at INTEGER NOT NULL,         -- Unix epoch timestamp
    last_accessed INTEGER NOT NULL       -- Unix epoch timestamp (updated on hit)
);
CREATE INDEX IF NOT EXISTS idx_art_last_accessed ON artwork_masters(last_accessed);

-- 2. Multi-Asset Slider Cache (Artist Discography / Fanart)
CREATE TABLE IF NOT EXISTS artist_sliders (
    artist_key TEXT PRIMARY KEY,         -- 'artist:{clean_artist}'
    frames_dir TEXT NOT NULL,            -- Path to folder containing 64x64 frame JPEGs
    frame_count INTEGER NOT NULL,        -- Number of stored frames (typically 2-10)
    source_urls_json TEXT NOT NULL,      -- Array of original URLs used
    created_at INTEGER NOT NULL,
    last_accessed INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artist_last_accessed ON artist_sliders(last_accessed);

-- 3. Normalized Song Registry
CREATE TABLE IF NOT EXISTS tracked_songs (
    song_id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    canonical_title TEXT,
    album TEXT,
    fingerprint TEXT UNIQUE NOT NULL,    -- md5(lower(artist) + '|' + lower(title))
    total_plays INTEGER DEFAULT 0,
    first_played INTEGER NOT NULL,
    last_played INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_song_fingerprint ON tracked_songs(fingerprint);

-- 4. Granular Playback Ledger
CREATE TABLE IF NOT EXISTS play_history (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER NOT NULL REFERENCES tracked_songs(song_id) ON DELETE CASCADE,
    played_at INTEGER NOT NULL,          -- UTC Unix epoch timestamp
    source TEXT DEFAULT 'stream'
);
CREATE INDEX IF NOT EXISTS idx_history_played ON play_history(played_at);
CREATE INDEX IF NOT EXISTS idx_history_played_at ON play_history(played_at);

-- 5. Completed Albums Ledger
CREATE TABLE IF NOT EXISTS album_completions (
    completion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_key TEXT NOT NULL,             -- album:{clean_artist}_{clean_album}
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    release_type TEXT DEFAULT 'album',   -- 'album' or 'ep'
    completed_at INTEGER NOT NULL        -- UTC Unix epoch timestamp
);
CREATE INDEX IF NOT EXISTS idx_album_completed ON album_completions(completed_at);

-- 6. Pixel Icons Metadata Cache (AWTRIX & LaMetric)
CREATE TABLE IF NOT EXISTS pixel_icons (
    icon_key TEXT PRIMARY KEY,          -- clean_id / slug
    file_path TEXT NOT NULL,           -- relative path inside storage dir
    source TEXT NOT NULL,              -- 'awtrix', 'lametric', 'custom', 'url'
    frame_count INTEGER NOT NULL,      -- number of frames (1 for static, >1 for animated)
    speed_ms INTEGER NOT NULL,         -- animation speed in ms
    width INTEGER NOT NULL,            -- pixel width
    height INTEGER NOT NULL,           -- pixel height
    created_at INTEGER NOT NULL,       -- Unix epoch timestamp
    last_accessed INTEGER NOT NULL     -- Unix epoch timestamp
);
CREATE INDEX IF NOT EXISTS idx_icon_last_accessed ON pixel_icons(last_accessed);
"""


REMIX_TAGS = re.compile(
    r"\s*[\(\[\{]\s*(?:feat\.?|ft\.?|remix|mix|edit|extended|acoustic|live|instrumental|vip|dub|version|ver\.?|remaster(?:ed)?|radio edit|club mix)[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
REMIX_DASH = re.compile(
    r"\s*-\s*(?:feat\.?|ft\.?|remix|mix|edit|extended|acoustic|live|instrumental|vip|dub|version|ver\.?|remaster(?:ed)?|radio edit|club mix).*",
    re.IGNORECASE,
)


def compute_canonical_title(val: Optional[str]) -> str:
    """Strip remix, edit, VIP, and feature suffixes to resolve canonical parent track title."""
    if not val:
        return ""
    raw = str(val).strip()
    cleaned = REMIX_TAGS.sub("", raw)
    cleaned = REMIX_DASH.sub("", cleaned).strip()
    return cleaned if cleaned else raw


def normalize_string(val: Optional[str]) -> str:
    """Normalize whitespace and strip symbols into a lowercase underscore-delimited token."""
    if not val:
        return ""
    cleaned = re.sub(r"[\W_]+", "_", str(val).strip().lower()).strip("_")
    return cleaned


def clean_storage_slug(val: Optional[str], default: str = "unknown") -> str:
    """Normalize whitespace and strip symbols into a lowercase underscore-delimited slug."""
    return normalize_string(val) or default


def generate_artwork_cache_key(
    artist: str,
    album_or_title: Optional[str] = None,
    title: Optional[str] = None,
    *,
    album: Optional[str] = None,
    is_ai: bool = False,
    is_radio: bool = False,
    force_ai: bool = False,
    playing_radio: bool = False,
    playing_tv: bool = False,
) -> str:
    """Derive deterministic artwork master cache key at album or track granularity."""
    if playing_tv:
        return "tv:icon"
    if title is None:
        resolved_title = album_or_title or ""
        resolved_album = album
    else:
        resolved_album = album if album is not None else album_or_title
        resolved_title = title

    clean_artist = normalize_string(artist) or "unknown_artist"
    clean_title = normalize_string(resolved_title) or "unknown_track"
    clean_album = normalize_string(resolved_album)

    if is_ai or force_ai:
        return f"track:{clean_artist}_{clean_title}"

    has_valid_album = bool(
        clean_album
        and clean_album not in ("unknown_album", "unknown", "none", "single")
        and not (is_radio or playing_radio)
    )
    if has_valid_album:
        return f"album:{clean_artist}_{clean_album}"

    return f"track:{clean_artist}_{clean_title}"


def generate_artist_cache_key(artist: str) -> str:
    """Derive deterministic cache key for artist sliders."""
    clean_artist = normalize_string(artist) or "unknown_artist"
    return f"artist:{clean_artist}"


class PixooDatabase:
    """Thread-safe SQLite connection manager with WAL mode and incremental auto-vacuum."""

    def __init__(self, base_dir: str, db_path: str):
        self.base_dir = base_dir
        self.db_path = db_path
        self.initialized = False

    def get_connection(self) -> sqlite3.Connection:
        """Open a configured SQLite connection with WAL and foreign keys enabled."""
        os.makedirs(self.base_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize_sync(self, masters_dir: str, artists_dir: str, icons_dir: Optional[str] = None) -> None:
        """Create filesystem directories and initialize SQLite schema."""
        os.makedirs(masters_dir, exist_ok=True)
        os.makedirs(artists_dir, exist_ok=True)
        if icons_dir:
            os.makedirs(icons_dir, exist_ok=True)
        marker = os.path.join(self.base_dir, ".uncropped_masters_v2")
        with sqlite3.connect(self.db_path, timeout=15.0) as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                cur_av = conn.execute("PRAGMA auto_vacuum;").fetchone()[0]
                if cur_av != 2:
                    conn.execute("PRAGMA auto_vacuum = INCREMENTAL;")
                    conn.execute("VACUUM;")
            except Exception:
                pass
            conn.executescript(SCHEMA_SQL)
            for migration_sql in (
                "ALTER TABLE tracked_songs ADD COLUMN canonical_title TEXT;",
                "ALTER TABLE play_history ADD COLUMN source TEXT DEFAULT 'stream';",
                "ALTER TABLE album_completions ADD COLUMN release_type TEXT DEFAULT 'album';",
            ):
                try:
                    conn.execute(migration_sql)
                except (sqlite3.OperationalError, Exception):
                    pass
            if not os.path.isfile(marker):
                conn.execute("DELETE FROM artwork_masters;")
            conn.commit()
        if not os.path.isfile(marker):
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write("1")
            except OSError:
                pass
        self.initialized = True
