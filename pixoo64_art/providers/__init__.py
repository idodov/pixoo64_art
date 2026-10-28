"""Upstream artwork and metadata providers for Pixoo64 Art."""

from .ai import AiArtProvider
from .audiodb import TheAudioDbProvider
from .base import (
    BaseProvider,
    _album_match_score,
    _is_album_match,
    _normalize_album_name,
    create_fallback_black_image_data,
    create_tv_icon_image,
)
from .discogs import DiscogsProvider
from .fallback import FallbackService
from .internet_archive import InternetArchiveProvider
from .lastfm import LastFmProvider
from .lyrics import LyricsProvider
from .musicbrainz import MusicBrainzProvider
from .spotify import SpotifyService
from .tidal import TidalProvider

__all__ = [
    "BaseProvider",
    "_normalize_album_name",
    "_album_match_score",
    "_is_album_match",
    "create_tv_icon_image",
    "create_fallback_black_image_data",
    "AiArtProvider",
    "TheAudioDbProvider",
    "MusicBrainzProvider",
    "DiscogsProvider",
    "InternetArchiveProvider",
    "LastFmProvider",
    "TidalProvider",
    "LyricsProvider",
    "SpotifyService",
    "FallbackService",
]
