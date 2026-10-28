"""Constants for the Pixoo64 Media Album Art integration."""
import re

DOMAIN = "pixoo64_art"

# Configuration Keys
CONF_PIXOO_IP = "pixoo_ip"
CONF_MEDIA_PLAYER = "media_player"
CONF_TV_MODE = "tv_mode"
CONF_PREFETCH_ENABLED = "prefetch_enabled"
CONF_AUDIODB_ENABLED = "audiodb_enabled"

# Options / Advanced Keys
CONF_POLLINATIONS_KEY = "pollinations_key"
CONF_SPOTIFY_CLIENT_ID = "spotify_client_id"
CONF_SPOTIFY_CLIENT_SECRET = "spotify_client_secret"
CONF_MUSICBRAINZ_ENABLED = "musicbrainz_enabled"
CONF_INTERNET_ARCHIVE = "internet_archive_enabled"
CONF_TIDAL_CLIENT_ID = "tidal_client_id"
CONF_TIDAL_CLIENT_SECRET = "tidal_client_secret"
CONF_LASTFM_KEY = "lastfm_key"
CONF_DISCOGS_TOKEN = "discogs_token"
CONF_WLED_IP = "wled_ip"
CONF_LIGHT_ENTITY = "light_entity"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_PLAYLIST_PREFETCH = "playlist_prefetch_range"

# Persistent Cache & Analytics Keys
CONF_PERSISTENT_CACHE_ENABLED = "enable_persistent_cache"
CONF_MAX_CACHED_ALBUMS = "max_cached_albums"
CONF_CLEAR_CACHE_TRIGGER = "clear_cache_trigger"

# Chart Engine Keys
CONF_FIRST_DAY_OF_WEEK = "first_day_of_week"
CONF_CHART_SLIDE_DURATION = "chart_slide_duration"
CONF_CHART_SIZE_LIMIT = "chart_size_limit"

DEFAULT_PERSISTENT_CACHE_ENABLED = True
DEFAULT_MAX_CACHED_ALBUMS = 1000
DEFAULT_MAX_CACHED_ARTISTS = 100
DEFAULT_HISTORY_DAYS = 365
DEFAULT_FIRST_DAY_OF_WEEK = "Sunday"
FIRST_DAY_OF_WEEK_OPTIONS = ["Sunday", "Monday"]
DEFAULT_CHART_SLIDE_DURATION = 4
DEFAULT_CHART_SIZE_LIMIT = 10

CHART_TYPES = ["Top Tracks", "Top Radio Tracks", "Top Artists", "Completed Albums", "Completed EPs"]
CHART_TIMEFRAMES = ["Daily", "Weekly", "Monthly", "Yearly", "All-Time"]
CHART_DIRECTIONS = ["Countdown (10 -> 1)", "Ascending (1 -> 10)"]

# BIDI & Transliteration Constants
HEBREW = r"\u0590-\u05FF"
ARABIC = r"\u0600-\u06FF|\u0750-\u077F|\u08A0-\u08FF|\uFB50-\uFDFF|\uFE70-\uFEFF|\u0621-\u06FF"
BIDI_REGEX = re.compile(f"[{HEBREW}|{ARABIC}]")

HEBREW_MAP = {
    'א': 'A', 'ב': 'B', 'ג': 'G', 'ד': 'D', 'ה': 'H', 'ו': 'V', 'ז': 'Z',
    'ח': 'Ch', 'ט': 'T', 'י': 'Y', 'כ': 'K', 'ך': 'K', 'ל': 'L', 'מ': 'M',
    'ם': 'M', 'נ': 'N', 'ן': 'N', 'ס': 'S', 'ע': 'A', 'פ': 'P', 'ף': 'F',
    'צ': 'Ts', 'ץ': 'Ts', 'ק': 'K', 'ר': 'R', 'ש': 'Sh', 'ת': 'T'
}

COLOR_PALETTE = [
    (255, 51, 51), (255, 99, 71), (255, 140, 0), (255, 215, 0), (255, 255, 0),
    (173, 255, 47), (127, 255, 0), (50, 205, 50), (0, 255, 255), (0, 191, 255),
    (30, 144, 255), (238, 130, 238), (255, 0, 255), (255, 20, 147), (255, 255, 255)
]
