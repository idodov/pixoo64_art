"""Core data models, configuration parsing, and BIDI/text utilities for Pixoo64."""
import logging
import re
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Optional

import aiohttp
from PIL import Image, ImageFont, UnidentifiedImageError
from homeassistant.core import HomeAssistant

from .const import (
    BIDI_REGEX,
    CONF_CHART_SIZE_LIMIT,
    CONF_CHART_SLIDE_DURATION,
    CONF_FIRST_DAY_OF_WEEK,
    CONF_MAX_CACHED_ALBUMS,
    CONF_PERSISTENT_CACHE_ENABLED,
    DEFAULT_CHART_SIZE_LIMIT,
    DEFAULT_CHART_SLIDE_DURATION,
    DEFAULT_FIRST_DAY_OF_WEEK,
    DEFAULT_MAX_CACHED_ALBUMS,
    DEFAULT_PERSISTENT_CACHE_ENABLED,
    HEBREW_MAP,
)

if TYPE_CHECKING:
    from .image.processor import ImageProcessor

_LOGGER = logging.getLogger(__name__)

try:
    from bidi.algorithm import get_display
    bidi_support = True
except ImportError:
    bidi_support = False

try:
    from unidecode import unidecode
except ImportError:
    def unidecode(text: str) -> str:
        return "".join(HEBREW_MAP.get(ch, ch) for ch in text)


def get_bidi(text: str) -> str:
    """Format right-to-left text (Hebrew/Arabic) into proper visual order."""
    if not text:
        return ""
    if bidi_support:
        try:
            return get_display(text)
        except Exception:
            pass
    # Pure-Python BiDi fallback when python-bidi is not installed:
    words = text.split()
    res = []
    for w in words:
        res.append(w[::-1] if has_bidi(w) else w)
    if has_bidi(text):
        res.reverse()
    return " ".join(res)


ARABIC_REGEX = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def is_arabic(text: str) -> bool:
    if not text:
        return False
    return bool(ARABIC_REGEX.search(text))


try:
    import arabic_reshaper  # type: ignore

    def reshape_arabic(text: str) -> str:
        try:
            return arabic_reshaper.reshape(text)
        except Exception:
            return text
except ImportError:
    def reshape_arabic(text: str) -> str:
        return text


def prepare_bidi_text(text: str) -> str:
    """Prepare text for display with BiDi and Arabic cursive shaping."""
    if not text:
        return ""
    if is_arabic(text):
        text = reshape_arabic(text)
    return get_bidi(text)


def has_bidi(text: str) -> bool:
    if not text:
        return False
    return bool(BIDI_REGEX.search(text))


is_hebrew = has_bidi


def ensure_rgb(img: Optional[Image.Image]) -> Optional[Image.Image]:
    try:
        if img and img.mode != "RGB":
            img = img.convert("RGB")
        return img
    except (UnidentifiedImageError, OSError):
        return None


def _resize_image_sync(image_data: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(BytesIO(image_data))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img.resize((34, 34), Image.Resampling.BILINEAR)
    except Exception:
        return None


class Config:
    """Runtime configuration state synchronized with Home Assistant ConfigEntry and UI entities."""

    def __init__(self, entry):
        data = entry.data
        options = entry.options

        def get_val(key, default=None):
            return options.get(key, data.get(key, default))

        self.temperature_sensor = get_val("temperature_entity")
        self.media_player = get_val("media_player", "media_player.living_room")
        self.pixoo_ip = get_val("pixoo_ip")
        self.pixoo_url = f"http://{self.pixoo_ip}:80/post" if self.pixoo_ip else None
        self.pollinations = get_val("pollinations_key", "")
        self.ai_fallback = get_val("ai_model", "black-forest-labs/flux.1-schnell")
        self.spotify_client_id = get_val("spotify_client_id", "")
        self.spotify_client_secret = get_val("spotify_client_secret", "")
        self.musicbrainz = get_val("musicbrainz_enabled", True)
        self.internet_archive = get_val("internet_archive_enabled", True)
        self.audiodb_enabled = get_val("audiodb_enabled", True)
        self.prefetch_enabled = get_val("prefetch_enabled", False)
        self.tidal_client_id = get_val("tidal_client_id", "")
        self.tidal_client_secret = get_val("tidal_client_secret", "")
        self.lastfm = get_val("lastfm_key", "")
        self.discogs = get_val("discogs_token", "")
        self.wled_ip = get_val("wled_ip", "")
        self.light_entity = get_val("light_entity", [])
        self.only_at_night = get_val("only_at_night", True)
        self.tv_mode = get_val("tv_mode", False)
        self.artwork_race_mode = get_val("artwork_race_mode", False)

        # Persistent Cache & Analytics settings
        raw_cache_flag = get_val(
            CONF_PERSISTENT_CACHE_ENABLED,
            get_val("persistent_cache_enabled", DEFAULT_PERSISTENT_CACHE_ENABLED),
        )
        self.enable_persistent_cache = bool(raw_cache_flag)
        self.persistent_cache_enabled = self.enable_persistent_cache
        try:
            self.max_cached_albums = max(50, min(2000, int(get_val(CONF_MAX_CACHED_ALBUMS, DEFAULT_MAX_CACHED_ALBUMS))))
        except (ValueError, TypeError):
            self.max_cached_albums = DEFAULT_MAX_CACHED_ALBUMS

        self.artist_slide, self.vinyl_mode, self.cassette_mode, self.analog_clock = False, False, False, False
        self.show_text, self.clean_title, self.text_bg, self.top_text = False, True, True, False
        self.overlay_top, self.overlay_align = True, "Clock Right, Temp Left"
        self.special_mode_spotify_slider, self.force_font_color, self.burned, self.burned_text = False, None, False, False
        self.crop_mode, self.crop_borders, self.crop_extra, self.crop_Sensitivity = "No Crop", False, False, False
        self.images_cache, self.full_control = 40, False
        self.contrast, self.sharpness, self.colors, self.kernel = False, False, False, False
        self.special_mode, self.info, self.show_clock, self.clock_bg, self.clock_align = False, False, False, False, "Right"
        self.clock_Analog, self.limit_colors = False, 0
        self.osd_overlay, self.pause_timeout, self.volume_osd_duration = get_val("osd_overlay", "Enabled"), get_val("pause_timeout", "15s"), get_val("volume_osd_duration", "2s")
        self.temperature, self.tv_icon_pic, self.spotify_slide, self.limit_color = False, False, False, None
        self.show_lyrics, self.lyrics_font, self.lyrics_sync = False, 2, 0.0
        self.progress_bar_enabled, self.progress_bar_character = True, "-"
        self.progress_bar_font, self.progress_bar_resolution = 190, 21
        self.progress_bar_color, self.progress_bar_y_offset = "match", 64
        self.force_ai, self.image_filter = False, "None"
        self.playlist_prefetch_range = get_val("playlist_prefetch_range", "Disabled")
        self.first_day_of_week = str(get_val(CONF_FIRST_DAY_OF_WEEK, DEFAULT_FIRST_DAY_OF_WEEK) or DEFAULT_FIRST_DAY_OF_WEEK)
        try:
            self.chart_slide_duration = max(2, min(10, int(get_val(CONF_CHART_SLIDE_DURATION, DEFAULT_CHART_SLIDE_DURATION))))
        except (ValueError, TypeError):
            self.chart_slide_duration = DEFAULT_CHART_SLIDE_DURATION
        try:
            self.chart_size_limit = max(3, min(20, int(get_val(CONF_CHART_SIZE_LIMIT, DEFAULT_CHART_SIZE_LIMIT))))
        except (ValueError, TypeError):
            self.chart_size_limit = DEFAULT_CHART_SIZE_LIMIT
        self.chart_type, self.chart_timeframe, self.chart_period, self.chart_direction = "Top Tracks", "Weekly", "Current", "Countdown (10 -> 1)"
        self.default_font = ImageFont.load_default()


class TitleCleaner:
    """Strips remaster tags, file extensions, and featuring suffixes from media titles."""

    def __init__(self):
        self._patterns = [
            re.compile(r'^\d+\s*[\.-]\s*', re.IGNORECASE),
            re.compile(r'\.(mp3|m4a|wav|flac|ogg|wma)$', re.IGNORECASE),
            re.compile(
                r'[\(\[][^)\]]*(?:remaster|remix|version|feat|ft\.|featuring|live|radio|edit|mix|acoustic|instrumental|cover|bonus|official|video|audio|mono|stereo)[^)\]]*[\)\]]',
                re.IGNORECASE,
            ),
            re.compile(
                r'\s+-\s+(?:Remaster(?:ed)?|Remix|Radio Edit|Live|Single|EP|Acoustic|Instrumental|Mono|Stereo)(?:\s+.*)?$',
                re.IGNORECASE,
            ),
            re.compile(r'\s+(?:feat\.?|ft\.?|featuring)\s+.*$', re.IGNORECASE),
            re.compile(r'\(\s*\)|\[\s*\]', re.IGNORECASE),
            re.compile(r'\s*[\-:]\s*$', re.IGNORECASE),
        ]

    def clean(self, title: str) -> str:
        if not title:
            return title
        for pattern in self._patterns:
            title = pattern.sub('', title)
        return ' '.join(title.split())


class MediaData:
    """Tracks current media player metadata, lyrics state, and animation frame buffers."""

    def __init__(self, hass: HomeAssistant, config: Config, image_processor: "ImageProcessor", session: aiohttp.ClientSession):
        from .providers.ai import AiArtProvider
        from .providers.lyrics import LyricsProvider

        self.hass = hass
        self.config = config
        self.image_processor = image_processor
        self.session = session
        self.lyrics_provider = LyricsProvider(self.config, self.session)
        self.lyrics_available: bool = False
        self.title_cleaner = TitleCleaner()
        self.ai_provider = AiArtProvider(self.config)
        self.vinyl_frames_b64: list = []
        self.cassette_frames_b64: list = []
        self.slider_frames_b64: list = []
        self.cached_slider_frames_bytes: list = []
        self.live_display_url: Optional[str] = None
        self.original_image_url: Optional[str] = None

        self.prev_title: str = ""
        self.prev_artist: str = ""
        self.prev_album: Optional[str] = None
        self.prev_playlist: Optional[str] = None
        self.prev_track_number: Optional[int] = None
        self.prev_picture: Optional[str] = None
        self.track_changed: bool = False
        self.play_recorded: bool = False
        self.is_prefetch: bool = False

        self.artist: str = ""
        self.title: str = ""
        self.title_original: str = ""
        self.album: Optional[str] = None
        self.playlist: str = ""
        self.lyrics: list = []
        self.picture: Optional[str] = None
        self.lyrics_font_color: str = "#FFA000"
        self.background_color: str = "#000000"
        self.show_progress_bar: bool = False
        self.playing_tv: bool = False
        self.playing_radio: bool = False
        self.radio_logo: bool = False
        self.pic_source: Optional[str] = None
        self.pic_url: Optional[str] = None
        self.media_position: float = 0.0
        self.media_duration: float = 0.0
        self.media_position_updated_at: Optional[datetime] = None
        self.temperature: Optional[str] = None

        self.spotify_slide_pass: bool = False
        self.artist_slide_pass: bool = False
        self.slider_frames: int = 0
        self.slider_album_urls: list[str] = []
        self.slider_artist_pic_url: Optional[str] = None
        self.slider_error: Optional[str] = None
        self.track_number: int = 1
        self.queue_total: int = 0

    def clean_title(self, title: str) -> str:
        return self.title_cleaner.clean(title)

    def format_ai_image_prompt(self, artist: Optional[str], title: str) -> Optional[str]:
        return self.ai_provider.format_prompt_url(artist, title)

    async def update(self, state_obj=None) -> Optional["MediaData"]:
        try:
            media_state_obj = state_obj or self.hass.states.get(self.config.media_player)
            if not media_state_obj or media_state_obj.state not in ["playing", "on", "paused"]:
                return None

            attributes = media_state_obj.attributes
            raw_title = attributes.get('media_title')
            raw_artist = attributes.get('media_artist')
            app_name = attributes.get('app_name')

            if self._is_tv_playing(raw_title, raw_artist, app_name, attributes):
                self._set_tv_state()
                return self

            if not raw_title or str(raw_title).strip() == "":
                raw_title = app_name if (app_name and str(app_name).strip() != "") else "Unknown Track"

            if not raw_artist or str(raw_artist).strip() == "":
                raw_artist = app_name if (app_name and str(app_name).strip() != "" and raw_title != app_name) else "Unknown Artist"

            self._set_media_state(raw_title, raw_artist, attributes)
            self._evaluate_radio_mode(raw_title, raw_artist, attributes)
            self._check_cached_lyrics()

            pic_changed = bool(self.picture and self.picture != self.prev_picture)
            album_changed = bool(self.album and self.album != getattr(self, "prev_album", None))
            playlist_changed = bool(self.playlist and self.playlist != getattr(self, "prev_playlist", None))
            track_num_changed = bool(self.track_number and self.track_number != getattr(self, "prev_track_number", None))
            self.track_changed = (
                self.title != self.prev_title
                or self.artist != self.prev_artist
                or album_changed
                or playlist_changed
                or track_num_changed
                or pic_changed
            )
            if self.track_changed:
                self.play_recorded = False
                self.vinyl_frames_b64 = []
                self.cassette_frames_b64 = []
                self.slider_frames_b64 = []
                self.cached_slider_frames_bytes = []
                self.slider_album_urls = []
                self.slider_artist_pic_url = None
                self.slider_frames = 0
                self.spotify_slide_pass = False
                self.artist_slide_pass = False
                self.slider_error = None

            self.prev_title, self.prev_artist = self.title, self.artist
            self.prev_album, self.prev_picture = self.album, self.picture
            self.prev_playlist, self.prev_track_number = self.playlist, self.track_number
            return self
        except Exception as e:
            _LOGGER.error("Error updating Media Data: %s", e)
            return None

    def _is_tv_playing(self, title: str, artist: str, app_name: str, attributes: dict) -> bool:
        if not getattr(self.config, "tv_mode", False):
            return False
        app_lower = str(app_name or "").lower()
        title_lower = str(title or "").lower()
        source_lower = str(attributes.get('source') or "").lower()
        channel_lower = str(attributes.get('media_channel') or "").lower()

        if "music" in app_lower or (artist and title and str(artist).strip() not in ("", "TV") and attributes.get("entity_picture")):
            return False

        is_tv_detected = (
            title == "TV" or title_lower == "tv" or app_lower == "tv"
            or source_lower == "tv" or channel_lower == "tv"
            or "netflix" in app_lower or "disney" in app_lower or "live tv" in app_lower
            or "audio return channel" in source_lower
        )
        return is_tv_detected and (
            not artist or artist == "TV" or title == "TV"
            or "netflix" in app_lower or source_lower == "tv"
        )

    def _set_tv_state(self):
        self.artist = self.title = self.title_original = "TV"
        self.playing_tv, self.lyrics, self.show_progress_bar = True, [], False
        self.picture = "TV_IS_ON_ICON" if getattr(self.config, 'tv_mode', False) else "TV_IS_ON"
        self.original_image_url = None
        self.track_changed = (self.title != self.prev_title or self.artist != self.prev_artist or self.picture != self.prev_picture)
        self.prev_title, self.prev_artist, self.prev_picture = self.title, self.artist, self.picture

    def _set_media_state(self, raw_title: str, raw_artist: str, attributes: dict):
        self.playing_tv = False
        self.title_original = raw_title
        self.title = self.clean_title(raw_title) if self.config.clean_title else raw_title
        self.artist = raw_artist if raw_artist else ""
        self.album = attributes.get('album_name') or attributes.get('media_album_name') or ""
        self.playlist = attributes.get('media_playlist') or attributes.get('playlist') or ""
        self.track_number = int(attributes.get('media_track', 1)) if str(attributes.get('media_track', '')).isdigit() else 1
        self.live_display_url = None

        original_picture = attributes.get('entity_picture')
        if original_picture and (re.match(r'^[a-zA-Z]:\\', original_picture) or original_picture.startswith("file://")):
            original_picture = None
        self.picture = original_picture
        self.original_image_url = original_picture if (original_picture and isinstance(original_picture, str) and original_picture.startswith("https://") and "/api/media_player_proxy/" not in original_picture) else None

        try:
            self.media_position = float(attributes.get('media_position', 0))
            self.media_duration = float(attributes.get('media_duration', 0))
        except (ValueError, TypeError):
            pass

        self.show_progress_bar = self.config.progress_bar_enabled and self.media_duration > 0
        pos_updated_at_str = attributes.get('media_position_updated_at')
        if isinstance(pos_updated_at_str, datetime):
            self.media_position_updated_at = pos_updated_at_str
        elif pos_updated_at_str:
            self.media_position_updated_at = datetime.fromisoformat(pos_updated_at_str.replace('Z', '+00:00'))
        else:
            self.media_position_updated_at = None

        raw_track = attributes.get('media_track')
        try:
            self.track_number = int(raw_track) if raw_track is not None else 1
        except (ValueError, TypeError):
            self.track_number = 1

    def _evaluate_radio_mode(self, raw_title: str, raw_artist: str, attributes: dict):
        media_content_id = str(attributes.get('media_content_id') or "").lower()
        media_channel = attributes.get('media_channel')
        app_name = str(attributes.get('app_name') or "").lower()
        source = str(attributes.get('source') or "").lower()
        content_type = str(attributes.get('media_content_type') or "").lower()

        # Traditional music streaming services always provide track-specific artwork even in station/radio mode
        is_music_service = any(
            srv in media_content_id or srv in app_name or srv in source
            for srv in ("apple", "spotify", "tidal", "deezer", "amazon", "youtube", "qobuz", "soundcloud")
        )

        is_radio_stream = bool(
            "tunein" in media_content_id or "tunein" in app_name or "tunein" in source
            or "iheart" in media_content_id or "iheart" in source
            or "radio" in media_content_id or "radio" in app_name
            or content_type in ("channel", "radio")
            or media_content_id.startswith(("aac://", "rtsp://", "icy://"))
            or (media_channel and not is_music_service and (
                media_content_id.startswith(("http://", "https://", "x-rincon-stream", "x-sonosapi-stream"))
            ))
        )

        if is_music_service:
            self.playing_radio = False
            self.radio_logo = False
        elif is_radio_stream:
            self.playing_radio = True
            # Real broadcast radio stations provide static station logos, not track art
            self.radio_logo = True
        else:
            self.playing_radio = False
            self.radio_logo = False

    def _check_cached_lyrics(self) -> bool:
        has_timing = (
            not self.playing_tv and not self.playing_radio and getattr(self, 'media_duration', 0) > 0
        )
        new_key = f"{self.artist}|{self.title_original}".lower()
        if has_timing and self.artist and self.title and new_key in self.lyrics_provider.lyrics_cache:
            raw = self.lyrics_provider.lyrics_cache[new_key]
            self.lyrics_available = bool(raw and len(raw) > 0)
            self.lyrics = raw if self.lyrics_available else []
            if self.lyrics_available:
                self.lyrics_provider.ensure_timeline_built(self.artist, self.title_original)
        else:
            self.lyrics_available = False
            self.lyrics = []
        return bool(self.lyrics_available)

    async def async_fetch_lyrics(self) -> bool:
        has_timing = (
            not self.playing_tv and not self.playing_radio and getattr(self, 'media_duration', 0) > 0
        )
        if not has_timing or not self.artist or not self.title:
            self.lyrics_available = False
            self.lyrics = []
            return False
        try:
            self.lyrics_available = await self.lyrics_provider.check_lyrics_availability(
                self.artist, self.title_original, int(self.media_duration)
            )
        except Exception as e:
            _LOGGER.debug("Error checking lyrics availability: %s", e)
            self.lyrics_available = False

        new_key = f"{self.artist}|{self.title_original}".lower()
        if self.lyrics_available and new_key in self.lyrics_provider.lyrics_cache:
            raw = self.lyrics_provider.lyrics_cache[new_key]
            self.lyrics = raw if (raw and len(raw) > 0) else []
            if self.lyrics:
                self.lyrics_provider.ensure_timeline_built(self.artist, self.title_original)
        else:
            self.lyrics = []
        return bool(self.lyrics_available)
