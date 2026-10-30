"""Playback analytics engine, album completion tracker, and Hit Parade leaderboard queries."""
import calendar
from datetime import datetime, timedelta
import hashlib
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .database import PixooDatabase, compute_canonical_title, normalize_string

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def compute_track_fingerprint(artist: str, title: str) -> str:
    """Compute MD5 fingerprint for a normalized artist and title."""
    fp_raw = f"{str(artist or '').strip().lower()}|{str(title or '').strip().lower()}"
    return hashlib.md5(fp_raw.encode("utf-8")).hexdigest()


def get_week_bounds(dt: datetime, first_day_of_week: str = "Sunday") -> Tuple[datetime, datetime]:
    """Return (start_of_week 00:00:00, end_of_week 23:59:59) aligned to Sunday or Monday."""
    day_floor = datetime(dt.year, dt.month, dt.day, 0, 0, 0)
    if str(first_day_of_week).strip().lower() == "monday":
        days_since = dt.weekday()
    else:
        days_since = (dt.weekday() + 1) % 7
    start_dt = day_floor - timedelta(days=days_since)
    end_dt = start_dt + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return start_dt, end_dt


def format_week_label(start_dt: datetime, end_dt: datetime, now_start_dt: datetime, first_day_of_week: str = "Sunday") -> str:
    """Format a weekly range label such as 'Current Week (18/10 - 24/10)' or 'Week 41 (11/10 - 17/10)'."""
    span = f"{start_dt.strftime('%d/%m')} - {end_dt.strftime('%d/%m')}"
    if start_dt.date() == now_start_dt.date():
        return f"Current Week ({span})"
    week_num = int(start_dt.strftime("%V" if str(first_day_of_week).lower() == "monday" else "%U")) or 1
    return f"Week {week_num} ({span})"


class PixooAnalytics:
    """Manages SQLite playback ledger, full album completions, and leaderboard queries."""

    def __init__(self, db: PixooDatabase):
        self.db = db

    @staticmethod
    def is_scrobble_eligible(
        position: float,
        duration: float,
        play_recorded: bool = False,
        playing_tv: bool = False,
        playing_radio: bool = False,
        artist: str = "Track",
        title: str = "Title",
        pic_source: Optional[str] = None,
        is_radio_logo: bool = False,
    ) -> bool:
        """Verify if current track playback meets the scrobble rule (30s or 50% duration)."""
        if (
            play_recorded
            or playing_tv
            or not artist
            or not title
            or artist in ("Unknown Artist", "TV")
            or title in ("Unknown Track", "TV")
        ):
            return False

        if playing_radio:
            if is_radio_logo or not pic_source or pic_source in ("Radio Logo", "Internal", "Unknown"):
                return False

        threshold = min(30.0, duration * 0.5) if duration > 0 else 30.0
        return position >= threshold

    def record_playback_sync(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        played_at: Optional[int] = None,
        source: str = "stream",
    ) -> None:
        """Insert or update tracked_songs and append chronological play_history event."""
        clean_artist = str(artist).strip()
        clean_title = str(title).strip()
        canonical_title = compute_canonical_title(clean_title)
        clean_album = str(album).strip() if album else None
        if clean_album and clean_album.lower() in ("unknown album", "unknown", "none"):
            clean_album = None

        fingerprint = compute_track_fingerprint(clean_artist, clean_title)
        now = int(played_at if played_at is not None else time.time())

        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT song_id, album, canonical_title FROM tracked_songs WHERE fingerprint = ?",
                (fingerprint,),
            )
            row = cursor.fetchone()
            if row:
                song_id, existing_album, existing_canonical = row
                updated_album = clean_album if clean_album else existing_album
                updated_canonical = canonical_title if canonical_title else existing_canonical
                conn.execute(
                    """
                    UPDATE tracked_songs
                    SET total_plays = total_plays + 1,
                        last_played = ?,
                        album = ?,
                        canonical_title = ?
                    WHERE song_id = ?
                    """,
                    (now, updated_album, updated_canonical, song_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO tracked_songs (artist, title, canonical_title, album, fingerprint, total_plays, first_played, last_played)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (clean_artist, clean_title, canonical_title, clean_album, fingerprint, now, now),
                )
                song_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO play_history (song_id, played_at, source) VALUES (?, ?, ?)",
                (song_id, now, source),
            )
            conn.commit()

    def record_album_completion_sync(
        self,
        artist: str,
        album: str,
        album_key: Optional[str] = None,
        completed_at: Optional[int] = None,
        release_type: str = "album",
    ) -> None:
        """Insert a verified album or EP completion into album_completions."""
        clean_artist = str(artist or "").strip()
        clean_album = str(album or "").strip()
        if not clean_artist or not clean_album:
            return
        resolved_key = album_key or f"album:{normalize_string(clean_artist)}_{normalize_string(clean_album)}"
        now = int(completed_at if completed_at is not None else time.time())
        norm_type = "ep" if "ep" in str(release_type).lower() else "album"
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO album_completions (album_key, artist, album, release_type, completed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (resolved_key, clean_artist, clean_album, norm_type, now),
            )
            conn.commit()

    def _get_all_event_timestamps_sync(self, chart_type: Optional[str] = None) -> List[int]:
        ct = str(chart_type or "").strip().lower()
        with self.db.get_connection() as conn:
            if "radio" in ct:
                rows = conn.execute("SELECT played_at FROM play_history WHERE source = 'radio' ORDER BY played_at DESC").fetchall()
            elif "ep" in ct:
                rows = conn.execute("SELECT completed_at FROM album_completions WHERE release_type = 'ep' ORDER BY completed_at DESC").fetchall()
            elif "album" in ct:
                rows = conn.execute("SELECT completed_at FROM album_completions WHERE (release_type IS NULL OR release_type = 'album') ORDER BY completed_at DESC").fetchall()
            elif ct:
                rows = conn.execute("SELECT played_at FROM play_history ORDER BY played_at DESC").fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT played_at AS ts FROM play_history
                    UNION
                    SELECT completed_at AS ts FROM album_completions
                    ORDER BY ts DESC
                    """
                ).fetchall()
        return [int(r[0]) for r in rows if r and r[0]]

    def get_available_periods_sync(
        self, timeframe: str = "Weekly", first_day_of_week: str = "Sunday", chart_type: Optional[str] = None
    ) -> List[str]:
        """Return ordered human-readable period labels for the given timeframe based on actual DB records."""
        tf = str(timeframe or "Weekly").strip().lower()
        timestamps = self._get_all_event_timestamps_sync(chart_type=chart_type)
        if tf in ("all-time", "all_time", "all"):
            return ["All History"] if timestamps else []

        if not timestamps:
            return []

        now_dt = datetime.now()
        labels: List[str] = []
        seen = set()

        def _add(lbl: str):
            if lbl not in seen:
                seen.add(lbl)
                labels.append(lbl)

        if tf in ("daily", "day"):
            yesterday_date = (now_dt - timedelta(days=1)).date()
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts)
                if dt.date() == now_dt.date():
                    _add("Today")
                elif dt.date() == yesterday_date:
                    _add("Yesterday")
                else:
                    _add(dt.strftime("%d/%m/%Y"))
            return labels

        if tf in ("weekly", "week"):
            now_w_start, now_w_end = get_week_bounds(now_dt, first_day_of_week)
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts)
                w_start, w_end = get_week_bounds(dt, first_day_of_week)
                _add(format_week_label(w_start, w_end, now_w_start, first_day_of_week))
            return labels

        if tf in ("monthly", "month"):
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts)
                _add(f"{MONTH_NAMES[dt.month]} {dt.year}")
            return labels

        if tf in ("yearly", "year"):
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts)
                _add(str(dt.year))
            return labels

        return ["All History"] if timestamps else []

    def get_chart_metadata_sync(self, first_day_of_week: str = "Sunday") -> Dict[str, Any]:
        """Compute available chart types, eligible timeframes based on DB span, and available periods."""
        now = int(time.time())
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT MIN(played_at), COUNT(*) FROM play_history").fetchone()
            min_ts = row[0] if (row and row[0]) else None
            total_plays = row[1] if row else 0

            alb_min_row = conn.execute("SELECT MIN(completed_at) FROM album_completions").fetchone()
            if alb_min_row and alb_min_row[0]:
                if min_ts is None or alb_min_row[0] < min_ts:
                    min_ts = alb_min_row[0]

            r_plays = conn.execute("SELECT COUNT(*) FROM play_history WHERE source = 'radio'").fetchone()[0] or 0
            artists_cnt = conn.execute("SELECT COUNT(DISTINCT LOWER(artist)) FROM tracked_songs WHERE total_plays > 0").fetchone()[0] or 0
            albs_cnt = conn.execute("SELECT COUNT(*) FROM album_completions WHERE (release_type IS NULL OR release_type = 'album')").fetchone()[0] or 0
            eps_cnt = conn.execute("SELECT COUNT(*) FROM album_completions WHERE release_type = 'ep'").fetchone()[0] or 0

        days_since_first = ((now - min_ts) / 86400.0) if min_ts else 0.0

        available_types: List[str] = []
        if total_plays > 0:
            available_types.append("Top Tracks")
        if r_plays > 0:
            available_types.append("Top Radio Tracks")
        if artists_cnt > 0:
            available_types.append("Top Artists")
        if albs_cnt > 0:
            available_types.append("Completed Albums")
        if eps_cnt > 0:
            available_types.append("Completed EPs")

        available_timeframes: List[str] = []
        if total_plays > 0 or albs_cnt > 0 or eps_cnt > 0:
            available_timeframes.append("Daily")
            if days_since_first >= 7.0:
                available_timeframes.append("Weekly")
            if days_since_first >= 30.0:
                available_timeframes.append("Monthly")
            if days_since_first >= 365.0:
                available_timeframes.append("Yearly")
            available_timeframes.append("All-Time")

        periods_by_tf: Dict[str, List[str]] = {}
        for tf in available_timeframes:
            periods_by_tf[tf] = self.get_available_periods_sync(timeframe=tf, first_day_of_week=first_day_of_week)

        periods_by_type_tf: Dict[str, Dict[str, List[str]]] = {}
        for ctype in available_types:
            periods_by_type_tf[ctype] = {}
            for tf in available_timeframes:
                periods_by_type_tf[ctype][tf] = self.get_available_periods_sync(
                    timeframe=tf, first_day_of_week=first_day_of_week, chart_type=ctype
                )

        return {
            "available_types": available_types,
            "available_timeframes": available_timeframes,
            "periods_by_timeframe": periods_by_tf,
            "periods_by_type_tf": periods_by_type_tf,
            "days_since_first_play": round(days_since_first, 1),
            "total_plays": total_plays,
            "completed_albums": albs_cnt,
            "completed_eps": eps_cnt,
            "radio_plays": r_plays,
            "artists_count": artists_cnt,
        }

    def resolve_period_bounds_sync(
        self,
        timeframe: str = "Weekly",
        period_label: Optional[str] = None,
        first_day_of_week: str = "Sunday",
    ) -> Tuple[int, int]:
        """Resolve (start_ts, end_ts) Unix epoch bounds for a timeframe and period label."""
        tf = str(timeframe or "Weekly").strip().lower()
        now_dt = datetime.now()
        lbl = str(period_label or "").strip()

        if tf in ("all-time", "all_time", "all") or lbl == "All History":
            return 0, int(time.time()) + 86400

        if tf in ("daily", "day"):
            if not lbl or lbl.lower() in ("today", "current", "current / latest", "current / today"):
                s = datetime(now_dt.year, now_dt.month, now_dt.day, 0, 0, 0)
            elif lbl.lower() == "yesterday":
                y = now_dt - timedelta(days=1)
                s = datetime(y.year, y.month, y.day, 0, 0, 0)
            else:
                try:
                    s = datetime.strptime(lbl, "%d/%m/%Y")
                except ValueError:
                    s = datetime(now_dt.year, now_dt.month, now_dt.day, 0, 0, 0)
            e = s + timedelta(hours=23, minutes=59, seconds=59)
            return int(s.timestamp()), int(e.timestamp())

        if tf in ("weekly", "week"):
            now_w_start, now_w_end = get_week_bounds(now_dt, first_day_of_week)
            if not lbl or lbl.startswith("Current Week") or lbl.lower() in ("current", "current / latest", "current week"):
                return int(now_w_start.timestamp()), int(now_w_end.timestamp())
            for ts in self._get_all_event_timestamps_sync():
                dt = datetime.fromtimestamp(ts)
                w_start, w_end = get_week_bounds(dt, first_day_of_week)
                if format_week_label(w_start, w_end, now_w_start, first_day_of_week) == lbl:
                    return int(w_start.timestamp()), int(w_end.timestamp())
            return int(now_w_start.timestamp()), int(now_w_end.timestamp())

        if tf in ("monthly", "month"):
            if not lbl or lbl.lower() in ("current", "current / latest", "current month"):
                m_idx, yr = now_dt.month, now_dt.year
            else:
                parts = lbl.split()
                if len(parts) == 2 and parts[0] in MONTH_NAMES and parts[1].isdigit():
                    m_idx = MONTH_NAMES.index(parts[0])
                    yr = int(parts[1])
                else:
                    m_idx, yr = now_dt.month, now_dt.year
            last_day = calendar.monthrange(yr, m_idx)[1]
            s = datetime(yr, m_idx, 1, 0, 0, 0)
            e = datetime(yr, m_idx, last_day, 23, 59, 59)
            return int(s.timestamp()), int(e.timestamp())

        if tf in ("yearly", "year"):
            if not lbl or lbl.lower() in ("current", "current / latest", "current year"):
                yr = now_dt.year
            else:
                yr = int(lbl) if lbl.isdigit() else now_dt.year
            return int(datetime(yr, 1, 1, 0, 0, 0).timestamp()), int(datetime(yr, 12, 31, 23, 59, 59).timestamp())

        return 0, int(time.time()) + 86400

    def get_leaderboard_sync(
        self,
        chart_type: str = "Top Tracks",
        timeframe: str = "Weekly",
        period: Optional[str] = None,
        limit: int = 10,
        first_day_of_week: str = "Sunday",
    ) -> List[Dict[str, Any]]:
        """Execute analytical SQL leaderboard query for Top Tracks, Top Artists, or Completed Albums."""
        safe_limit = max(1, min(50, int(limit or 10)))
        start_ts, end_ts = self.resolve_period_bounds_sync(timeframe, period, first_day_of_week)
        ct = str(chart_type or "Top Tracks").strip().lower()

        with self.db.get_connection() as conn:
            if "artist" in ct:
                rows = conn.execute(
                    "SELECT s.artist, COUNT(h.event_id) AS plays, MAX(h.played_at) AS last_played "
                    "FROM play_history h JOIN tracked_songs s ON h.song_id = s.song_id "
                    "WHERE h.played_at BETWEEN ? AND ? GROUP BY LOWER(s.artist) "
                    "ORDER BY plays DESC, last_played DESC LIMIT ?",
                    (start_ts, end_ts, safe_limit),
                ).fetchall()
                return [
                    {"rank": idx, "artist": artist, "title": artist, "plays": int(plays), "last_played": int(last_played or 0)}
                    for idx, (artist, plays, last_played) in enumerate(rows, start=1)
                ]

            if "ep" in ct:
                rows = conn.execute(
                    "SELECT artist, album, album_key, COUNT(*) AS full_plays, MAX(completed_at) AS last_played "
                    "FROM album_completions WHERE release_type = 'ep' AND completed_at BETWEEN ? AND ? GROUP BY album_key "
                    "ORDER BY full_plays DESC, last_played DESC LIMIT ?",
                    (start_ts, end_ts, safe_limit),
                ).fetchall()
                return [
                    {
                        "rank": idx, "artist": artist, "album": album, "title": album,
                        "album_key": album_key, "full_plays": int(full_plays), "plays": int(full_plays),
                        "last_played": int(last_played or 0),
                    }
                    for idx, (artist, album, album_key, full_plays, last_played) in enumerate(rows, start=1)
                ]

            if "album" in ct:
                rows = conn.execute(
                    "SELECT artist, album, album_key, COUNT(*) AS full_plays, MAX(completed_at) AS last_played "
                    "FROM album_completions WHERE (release_type IS NULL OR release_type = 'album') AND completed_at BETWEEN ? AND ? GROUP BY album_key "
                    "ORDER BY full_plays DESC, last_played DESC LIMIT ?",
                    (start_ts, end_ts, safe_limit),
                ).fetchall()
                return [
                    {
                        "rank": idx, "artist": artist, "album": album, "title": album,
                        "album_key": album_key, "full_plays": int(full_plays), "plays": int(full_plays),
                        "last_played": int(last_played or 0),
                    }
                    for idx, (artist, album, album_key, full_plays, last_played) in enumerate(rows, start=1)
                ]

            if "radio" in ct:
                rows = conn.execute(
                    "SELECT s.artist, COALESCE(s.canonical_title, s.title) AS can_title, s.album, COUNT(h.event_id) AS plays, MAX(h.played_at) AS last_played "
                    "FROM play_history h JOIN tracked_songs s ON h.song_id = s.song_id "
                    "WHERE h.source = 'radio' AND h.played_at BETWEEN ? AND ? "
                    "GROUP BY LOWER(s.artist), LOWER(COALESCE(s.canonical_title, s.title)) "
                    "ORDER BY plays DESC, last_played DESC LIMIT ?",
                    (start_ts, end_ts, safe_limit),
                ).fetchall()
                return [
                    {"rank": idx, "artist": artist, "title": can_title, "album": album or "", "plays": int(plays), "last_played": int(last_played or 0)}
                    for idx, (artist, can_title, album, plays, last_played) in enumerate(rows, start=1)
                ]

            rows = conn.execute(
                "SELECT s.artist, COALESCE(s.canonical_title, s.title) AS can_title, s.album, COUNT(h.event_id) AS plays, MAX(h.played_at) AS last_played "
                "FROM play_history h JOIN tracked_songs s ON h.song_id = s.song_id "
                "WHERE h.played_at BETWEEN ? AND ? "
                "GROUP BY LOWER(s.artist), LOWER(COALESCE(s.canonical_title, s.title)) "
                "ORDER BY plays DESC, last_played DESC LIMIT ?",
                (start_ts, end_ts, safe_limit),
            ).fetchall()
            return [
                {"rank": idx, "artist": artist, "title": can_title, "album": album or "", "plays": int(plays), "last_played": int(last_played or 0)}
                for idx, (artist, can_title, album, plays, last_played) in enumerate(rows, start=1)
            ]

    def get_top_tracks_sync(self, period: str = "week", limit: int = 10) -> List[Dict[str, Any]]:
        """Query top played tracks for day, week, month, or all_time."""
        norm_period = str(period or "week").strip().lower()
        safe_limit = max(1, min(50, int(limit or 10)))
        now = int(time.time())

        with self.db.get_connection() as conn:
            if norm_period in ("all_time", "all", "all-time"):
                cursor = conn.execute(
                    """
                    SELECT artist, COALESCE(canonical_title, title) AS can_title, album, SUM(total_plays) AS plays
                    FROM tracked_songs
                    WHERE total_plays > 0
                    GROUP BY LOWER(artist), LOWER(COALESCE(canonical_title, title))
                    ORDER BY plays DESC, MAX(last_played) DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                )
            else:
                days = {"day": 1, "daily": 1, "week": 7, "weekly": 7, "month": 30, "monthly": 30, "year": 365, "yearly": 365}.get(norm_period, 7)
                cutoff = now - (days * 86400)
                cursor = conn.execute(
                    """
                    SELECT t.artist, COALESCE(t.canonical_title, t.title) AS can_title, t.album, COUNT(h.event_id) AS plays
                    FROM play_history h
                    JOIN tracked_songs t ON h.song_id = t.song_id
                    WHERE h.played_at >= ?
                    GROUP BY LOWER(t.artist), LOWER(COALESCE(t.canonical_title, t.title))
                    ORDER BY plays DESC, MAX(h.played_at) DESC
                    LIMIT ?
                    """,
                    (cutoff, safe_limit),
                )
            rows = cursor.fetchall()

        return [
            {"rank": idx, "artist": artist, "title": can_title, "album": album or "", "plays": int(plays)}
            for idx, (artist, can_title, album, plays) in enumerate(rows, start=1)
        ]

    def get_track_stats_sync(self, artist: str, title: str) -> Dict[str, Any]:
        """Fetch total plays and timestamps for a track by artist and title/canonical title."""
        if not artist or not title:
            return {"plays": 0, "first_played": None, "last_played": None}
        can_title = compute_canonical_title(title)
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT SUM(total_plays), MIN(first_played), MAX(last_played)
                FROM tracked_songs
                WHERE LOWER(artist) = LOWER(?) AND (LOWER(title) = LOWER(?) OR LOWER(COALESCE(canonical_title, title)) = LOWER(?))
                """,
                (artist.strip(), title.strip(), can_title.strip()),
            ).fetchone()
            plays = int(row[0]) if (row and row[0] is not None) else 0
            first_p = row[1] if (row and row[1] is not None) else None
            last_p = row[2] if (row and row[2] is not None) else None
        return {"plays": plays, "first_played": first_p, "last_played": last_p}

    def get_analytics_summary_sync(self) -> Dict[str, Any]:
        """Aggregate high-level analytics and database metrics."""
        now = int(time.time())
        day_start = now - 86400
        week_start = now - (7 * 86400)
        month_start = now - (30 * 86400)

        db_size_str = "0 KB"
        try:
            if hasattr(self.db, "db_path") and os.path.isfile(self.db.db_path):
                sz = os.path.getsize(self.db.db_path)
                db_size_str = f"{sz / 1048576:.2f} MB" if sz >= 1048576 else f"{sz / 1024:.1f} KB"
        except OSError:
            pass

        with self.db.get_connection() as conn:
            songs_cnt = conn.execute("SELECT COUNT(*) FROM tracked_songs WHERE total_plays > 0").fetchone()[0] or 0
            artists_cnt = conn.execute("SELECT COUNT(DISTINCT LOWER(artist)) FROM tracked_songs WHERE total_plays > 0").fetchone()[0] or 0
            total_plays = conn.execute("SELECT COUNT(*) FROM play_history").fetchone()[0] or 0
            masters_cnt = conn.execute("SELECT COUNT(*) FROM artwork_masters").fetchone()[0] or 0
            p_today = conn.execute("SELECT COUNT(*) FROM play_history WHERE played_at >= ?", (day_start,)).fetchone()[0] or 0
            p_week = conn.execute("SELECT COUNT(*) FROM play_history WHERE played_at >= ?", (week_start,)).fetchone()[0] or 0
            p_month = conn.execute("SELECT COUNT(*) FROM play_history WHERE played_at >= ?", (month_start,)).fetchone()[0] or 0
            r_plays = conn.execute("SELECT COUNT(*) FROM play_history WHERE source = 'radio'").fetchone()[0] or 0
            albs_cnt = conn.execute("SELECT COUNT(*) FROM album_completions WHERE release_type = 'album'").fetchone()[0] or 0
            eps_cnt = conn.execute("SELECT COUNT(*) FROM album_completions WHERE release_type = 'ep'").fetchone()[0] or 0

            top_t = conn.execute(
                """
                SELECT artist, COALESCE(canonical_title, title), SUM(total_plays) as plays
                FROM tracked_songs WHERE total_plays > 0
                GROUP BY LOWER(artist), LOWER(COALESCE(canonical_title, title))
                ORDER BY plays DESC, MAX(last_played) DESC LIMIT 1
                """
            ).fetchone()
            top_track_str = f"{top_t[0]} - {top_t[1]} ({top_t[2]} plays)" if top_t else None

            top_a = conn.execute(
                """
                SELECT artist, SUM(total_plays) as plays
                FROM tracked_songs WHERE total_plays > 0
                GROUP BY LOWER(artist)
                ORDER BY plays DESC, MAX(last_played) DESC LIMIT 1
                """
            ).fetchone()
            top_artist_str = f"{top_a[0]} ({top_a[1]} plays)" if top_a else None

            last_row = conn.execute("SELECT MAX(played_at) FROM play_history").fetchone()
            last_ts = last_row[0] if (last_row and last_row[0]) else None
            last_scrobble = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_ts)) if last_ts else None

        return {
            "db_tracked_songs_total": songs_cnt,
            "db_unique_artists_total": artists_cnt,
            "db_total_play_events": total_plays,
            "db_file_size": db_size_str,
            "db_masters_cached": masters_cnt,
            "plays_today": p_today,
            "plays_this_week": p_week,
            "plays_this_month": p_month,
            "radio_plays_total": r_plays,
            "completed_albums_total": albs_cnt,
            "completed_eps_total": eps_cnt,
            "top_track_current": top_track_str,
            "top_artist_current": top_artist_str,
            "last_scrobbled_at": last_scrobble,
        }

    @staticmethod
    def clear_analytics_on_conn(conn) -> None:
        """Truncate play_history, tracked_songs, and album_completions tables."""
        conn.execute("DELETE FROM play_history")
        conn.execute("DELETE FROM tracked_songs")
        conn.execute("DELETE FROM album_completions")


PlaybackAnalyticsEngine = PixooAnalytics
