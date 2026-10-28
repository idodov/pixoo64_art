"""LRCLib synced lyrics provider, parser, and visual layout builder."""

from collections import OrderedDict
import difflib
import re
from typing import TYPE_CHECKING, Optional
import aiohttp

from ..models import get_bidi, has_bidi
from .base import BaseProvider

if TYPE_CHECKING:
    from ..models import Config


class LyricsProvider(BaseProvider):
    """Fetches, parses, and builds 64x64 synced lyrics timelines from LRCLib."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession) -> None:
        self.config = config
        self.session = session
        self.lyrics_cache: OrderedDict[str, list] = OrderedDict()
        self.visual_timeline: list[dict] = []
        self.current_song_key: Optional[str] = None
        self.current_frame_index: int = -1
        self.filler_regex = re.compile(
            r"(?:[\s\W]+(?:oh+|ooh+|yeah|yea|woah|la+|na+)[\W]*)+$", re.IGNORECASE
        )

    async def _fetch_from_api(
        self, artist: str, title: str, duration: int
    ) -> list[dict]:
        fetched_lyrics = []
        base_url_get = "https://lrclib.net/api/get"
        params = {"artist_name": artist, "track_name": title}
        headers = {"User-Agent": "Pixoo64-HomeAssistant-Integration/2.0"}

        try:
            async with self.session.get(
                base_url_get, params=params, headers=headers, timeout=10
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("syncedLyrics"):
                        fetched_lyrics = self._parse_lrc(data["syncedLyrics"])
        except Exception:
            pass

        if not fetched_lyrics:
            try:
                base_url_search = "https://lrclib.net/api/search"
                search_params = {"q": f"{artist} {title}"}
                async with self.session.get(
                    base_url_search, params=search_params, headers=headers, timeout=10
                ) as response:
                    if response.status == 200:
                        results = await response.json()
                        if results and isinstance(results, list):
                            best_candidate = None
                            best_score = 0
                            for item in results:
                                if not item.get("syncedLyrics"):
                                    continue
                                score = self._calculate_fuzzy_score(
                                    artist,
                                    title,
                                    float(duration) if duration else 0,
                                    item.get("artistName"),
                                    item.get("trackName"),
                                    item.get("duration"),
                                )
                                if score > 60 and score > best_score:
                                    best_score = score
                                    best_candidate = item
                            if best_candidate:
                                fetched_lyrics = self._parse_lrc(
                                    best_candidate["syncedLyrics"]
                                )
            except Exception:
                pass

        return fetched_lyrics

    async def prefetch_lyrics(
        self, artist: str, title: str, duration: int = 0
    ) -> None:
        """Silently fetch and cache lyrics for the next track in the background."""
        if not artist or not title:
            return
        new_key = f"{artist}|{title}".lower()

        if new_key in self.lyrics_cache:
            return

        fetched_lyrics = await self._fetch_from_api(artist, title, duration)

        if fetched_lyrics:
            if len(self.lyrics_cache) >= 40:
                self.lyrics_cache.popitem(last=False)
            self.lyrics_cache[new_key] = fetched_lyrics

    async def get_lyrics(
        self,
        artist: Optional[str],
        title: str,
        album: Optional[str] = None,
        duration: int = 0,
    ) -> list[dict]:
        if not artist or not title:
            return []
        new_key = f"{artist}|{title}".lower()

        if new_key == self.current_song_key:
            return self.lyrics_cache.get(new_key, [])

        self.visual_timeline = []
        self.current_song_key = new_key

        if new_key in self.lyrics_cache:
            self.lyrics_cache.move_to_end(new_key)
            raw_lyrics = self.lyrics_cache[new_key]
            self._build_visual_timeline(raw_lyrics)
            return raw_lyrics

        fetched_lyrics = await self._fetch_from_api(artist, title, duration)

        if len(self.lyrics_cache) >= 40:
            self.lyrics_cache.popitem(last=False)
        self.lyrics_cache[new_key] = fetched_lyrics
        self._build_visual_timeline(fetched_lyrics)
        return fetched_lyrics

    def _calculate_fuzzy_score(
        self, src_artist, src_title, src_dur, tgt_artist, tgt_title, tgt_dur
    ):
        if not tgt_artist or not tgt_title:
            return 0
        dur_diff = abs(src_dur - (tgt_dur or 0))
        if src_dur > 0 and dur_diff > 20:
            return 0

        def norm(s):
            return str(s).lower().strip()

        seq_a = difflib.SequenceMatcher(None, norm(src_artist), norm(tgt_artist))
        seq_t = difflib.SequenceMatcher(None, norm(src_title), norm(tgt_title))
        similarity = (seq_a.ratio() * 0.4) + (seq_t.ratio() * 0.6)
        return (similarity * 100) - (dur_diff * 2)

    def _parse_lrc(self, lrc_text: str) -> list[dict]:
        if not lrc_text:
            return []
        parsed = []
        pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
        for line in lrc_text.split("\n"):
            match = pattern.match(line)
            if match:
                minutes, seconds, text = (
                    int(match.group(1)),
                    float(match.group(2)),
                    match.group(3).strip(),
                )
                if not text:
                    continue
                parsed.append(
                    {"seconds": int(minutes * 60 + seconds + 0.5), "lyrics": text}
                )

        if not parsed:
            return []
        cleaned = []
        current_block = parsed[0].copy()
        for i in range(1, len(parsed)):
            if parsed[i]["seconds"] == current_block["seconds"]:
                current_block["lyrics"] += "\n" + parsed[i]["lyrics"]
            else:
                cleaned.append(current_block)
                current_block = parsed[i].copy()
        cleaned.append(current_block)
        return cleaned

    def _get_text_width(self, text: str) -> int:
        """Calculate the approximate pixel width of a string for Pixoo font."""
        width = 0
        for char in text:
            if char in "WM@%A":
                width += 6
            elif char in "mwQO":
                width += 5
            elif char in "Iijl1!.,:;'\"|":
                width += 2
            elif char in "tf()[]{}":
                width += 3
            elif char.isspace():
                width += 3
            elif char.isupper():
                width += 5
            elif char.islower():
                width += 4
            elif "\u0590" <= char <= "\u05ff":
                width += 5
            else:
                width += 4
            width += 1
        return width - 1 if width > 0 else 0

    def _basic_wrap(self, text: str, max_px: int) -> list[str]:
        text = text.replace("-", " - ")
        words = text.split()
        lines, current_line, current_width = [], [], 0
        space_width = self._get_text_width(" ") + 1

        for word in words:
            word_width = self._get_text_width(word)
            if not current_line:
                current_line.append(word)
                current_width = word_width
            elif current_width + space_width + word_width <= max_px:
                current_line.append(word)
                current_width += space_width + word_width
            else:
                lines.append(current_line)
                current_line = [word]
                current_width = word_width

        if current_line:
            lines.append(current_line)
        return [l.replace(" - ", "-") for l in [" ".join(line) for line in lines]]

    def _smart_wrap(self, text: str, max_px: int) -> list[str]:
        strict_max = max_px - 4

        for width in range(42, strict_max + 1, 2):
            lines = self._basic_wrap(text, width)
            if len(lines) <= 6:
                return lines

        cleaned_text = self.filler_regex.sub("", text).strip()
        if len(cleaned_text) < len(text):
            for width in range(42, strict_max + 1, 2):
                lines = self._basic_wrap(cleaned_text, width)
                if len(lines) <= 6:
                    return lines

        lines = self._basic_wrap(text, strict_max)
        return lines[:6]

    def _build_visual_timeline(self, raw_lyrics: list[dict]) -> None:
        self.visual_timeline = []
        self.current_frame_index = -1
        if not raw_lyrics:
            return
        n = len(raw_lyrics)
        for i in range(n):
            current = raw_lyrics[i]
            text, start_time = current["lyrics"], current["seconds"]
            next_start = (
                raw_lyrics[i + 1]["seconds"] if i + 1 < n else start_time + 60.0
            )
            word_count = len(text.split())
            reading_duration = max(3.0, min(2.0 + (word_count * 0.4), 8.0))
            calculated_end_time = start_time + reading_duration
            gap_to_next = next_start - calculated_end_time
            end_time = (
                next_start
                if 0 < gap_to_next < 2.5
                else min(calculated_end_time, next_start)
            )
            if end_time <= start_time:
                end_time = start_time + 1.0

            max_px = 64
            layout_items = []
            raw_blocks = text.split("\n")
            final_render_lines = []

            for block_idx, block in enumerate(raw_blocks):
                if len(final_render_lines) >= 6:
                    break
                wrapped = self._smart_wrap(block, max_px)
                slots_remaining = 6 - len(final_render_lines)
                if len(wrapped) > slots_remaining:
                    if slots_remaining == 1:
                        wrapped = [" ".join(wrapped)]
                    else:
                        wrapped = wrapped[: slots_remaining - 1] + [
                            " ".join(wrapped[slots_remaining - 1 :])
                        ]
                if has_bidi(text):
                    wrapped = [get_bidi(line) for line in wrapped]
                for line_idx, line in enumerate(wrapped):
                    if line.strip():
                        final_render_lines.append(
                            (line.strip(), line_idx == 0 and block_idx > 0)
                        )

            if len(final_render_lines) >= 6:
                font_height, block_gap, current_y = 10, 0, 1
            else:
                font_height, block_gap = 12, 2
                current_y = (
                    64
                    - (
                        (len(final_render_lines) * font_height)
                        + (
                            sum(1 for _, is_new in final_render_lines if is_new)
                            * block_gap
                        )
                    )
                ) // 2

            for line_text, is_new_block in final_render_lines:
                if has_bidi(text):
                    line_text = (
                        line_text.replace("(", "###TEMP###")
                        .replace(")", "(")
                        .replace("###TEMP###", ")")
                    )
                if is_new_block:
                    current_y += block_gap
                layout_items.append(
                    {
                        "y": current_y,
                        "h": font_height,
                        "dir": 1 if has_bidi(line_text) else 0,
                        "text": line_text,
                    }
                )
                current_y += font_height

            self.visual_timeline.append(
                {"start": start_time, "end": end_time, "layout": layout_items}
            )

    def get_refresh_plan(self, current_pos: float) -> tuple[Optional[list], Optional[float]]:
        if not self.visual_timeline:
            return None, None
        active_index = -1
        if 0 <= self.current_frame_index < len(self.visual_timeline):
            frame = self.visual_timeline[self.current_frame_index]
            if frame["start"] <= current_pos < frame["end"]:
                active_index = self.current_frame_index
        if active_index == -1:
            for i, frame in enumerate(self.visual_timeline):
                if frame["start"] <= current_pos < frame["end"]:
                    active_index = i
                    break
                if frame["start"] > current_pos:
                    break

        if active_index != -1:
            self.current_frame_index = active_index
            frame = self.visual_timeline[active_index]
            next_event_time = frame["end"]
            if active_index + 1 < len(self.visual_timeline):
                next_start = self.visual_timeline[active_index + 1]["start"]
                if next_start - next_event_time < 0.2:
                    next_event_time = next_start
            return frame["layout"], max(0.1, next_event_time - current_pos)

        self.current_frame_index = -1
        next_event_time = -1
        for frame in self.visual_timeline:
            if frame["start"] > current_pos:
                next_event_time = frame["start"]
                break

        if next_event_time != -1:
            return [], max(0.1, next_event_time - current_pos)
        return [], None

    async def check_lyrics_availability(
        self, artist: str, title: str, duration: int
    ) -> bool:
        """Check if synced lyrics exist for the track without building visual timeline."""
        if not artist or not title or duration <= 0:
            return False

        new_key = f"{artist}|{title}".lower()
        if new_key in self.lyrics_cache:
            return len(self.lyrics_cache[new_key]) > 0

        fetched = await self._fetch_from_api(artist, title, duration)
        if len(self.lyrics_cache) >= 40:
            self.lyrics_cache.popitem(last=False)
        self.lyrics_cache[new_key] = fetched
        return len(fetched) > 0

    def ensure_timeline_built(self, artist: str, title: str) -> None:
        """Build visual timeline only when lyrics display is actually requested."""
        if not artist or not title:
            return
        new_key = f"{artist}|{title}".lower()
        if new_key != self.current_song_key:
            self.current_song_key = new_key
            raw_lyrics = self.lyrics_cache.get(new_key, [])
            self._build_visual_timeline(raw_lyrics)
