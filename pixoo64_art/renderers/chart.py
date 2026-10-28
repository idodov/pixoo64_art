"""Hit Parade Chart visual renderer and playback session controller for Pixoo64."""
import asyncio
import logging
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from PIL import Image, ImageDraw

from ..models import unidecode
from ..storage.analytics import compute_track_fingerprint
from ..storage.database import compute_canonical_title, normalize_string
from .cassette import MicroPixelFont

if TYPE_CHECKING:
    from ..hub.hub import PixooHub

_LOGGER = logging.getLogger(__name__)


class ChartRenderer:
    """Renders 64x64 Hit Parade intro cards, rank badges, fallback icons, and bottom overlays."""

    @staticmethod
    def _clean_label(text: str, max_px: int = 58) -> str:
        raw = unidecode(str(text or "")).upper().strip()
        cleaned = "".join(ch if ch in MicroPixelFont.GLYPHS else " " for ch in raw)
        cleaned = " ".join(cleaned.split())
        while cleaned and MicroPixelFont.get_text_width(cleaned) > max_px:
            cleaned = cleaned[:-1].rstrip()
        return cleaned or "---"

    @classmethod
    def _draw_centered_text(cls, draw: ImageDraw.ImageDraw, y: int, text: str, color: tuple) -> None:
        clean = cls._clean_label(text, 60)
        w = MicroPixelFont.get_text_width(clean)
        x = max(2, (64 - w) // 2)
        MicroPixelFont.draw_text(draw, x, y, clean, color)

    @staticmethod
    def _create_gradient_bg(top_rgb: tuple = (8, 8, 20), bot_rgb: tuple = (20, 20, 40)) -> Image.Image:
        img = Image.new("RGB", (64, 64))
        draw = ImageDraw.Draw(img)
        for y in range(64):
            t = y / 63.0
            r = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * t)
            g = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * t)
            b = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * t)
            draw.line([(0, y), (63, y)], fill=(r, g, b))
        return img

    @staticmethod
    def _draw_trophy_icon(draw: ImageDraw.ImageDraw, cx: int = 32, cy: int = 20) -> None:
        gold = (255, 215, 0)
        shine = (255, 245, 150)
        dark_gold = (185, 140, 10)
        # Cup body
        draw.rectangle([cx - 7, cy - 8, cx + 7, cy - 1], fill=gold)
        draw.rectangle([cx - 5, cy, cx + 5, cy + 2], fill=gold)
        # Handles
        draw.rectangle([cx - 10, cy - 7, cx - 8, cy - 3], outline=dark_gold)
        draw.rectangle([cx + 8, cy - 7, cx + 10, cy - 3], outline=dark_gold)
        # Stem & Pedestal
        draw.rectangle([cx - 2, cy + 3, cx + 2, cy + 6], fill=dark_gold)
        draw.rectangle([cx - 6, cy + 7, cx + 6, cy + 9], fill=gold)
        # Highlight
        draw.line([(cx - 5, cy - 7), (cx - 5, cy - 2)], fill=shine)

    @staticmethod
    def _draw_vinyl_fallback_icon(draw: ImageDraw.ImageDraw, cx: int = 32, cy: int = 24) -> None:
        draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=(22, 22, 30), outline=(70, 70, 95))
        draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], outline=(45, 45, 65))
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(215, 165, 40))
        draw.point((cx, cy), fill=(10, 10, 16))

    @classmethod
    def render_intro_card(
        cls, chart_type: str, timeframe: str, period_label: str, limit: int, empty: bool = False
    ) -> Image.Image:
        img = cls._create_gradient_bg((8, 8, 20), (20, 20, 40))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 63, 63], outline=(255, 215, 0))
        draw.rectangle([2, 2, 61, 61], outline=(50, 50, 85))
        cls._draw_trophy_icon(draw, 32, 17)

        ct_l = chart_type.lower()
        if "artist" in ct_l:
            title_line = f"TOP {limit} ARTISTS" if limit < 10 else "TOP ARTISTS"
        elif "ep" in ct_l:
            title_line = "COMPLETED EPS"
        elif "album" in ct_l:
            title_line = "FULL ALBUMS"
        elif "radio" in ct_l:
            title_line = f"TOP {limit} RADIO"
        else:
            title_line = f"TOP {limit} TRACKS"

        sub_line = period_label if period_label and period_label != "Current" else timeframe
        cls._draw_centered_text(draw, 34, "HIT PARADE", (255, 215, 0))
        cls._draw_centered_text(draw, 43, title_line, (255, 255, 255))
        cls._draw_centered_text(draw, 52, "NO PLAYS YET" if empty else sub_line, (0, 229, 255))
        return img

    @classmethod
    def render_rank_slide(
        cls,
        item: Dict[str, Any],
        chart_type: str,
        art_img: Optional[Image.Image],
        pulse_bright: bool = True,
    ) -> Image.Image:
        rank = int(item.get("rank", 1))
        plays = int(item.get("plays", 0))
        artist = str(item.get("artist") or "")
        title = str(item.get("title") or "")
        album = str(item.get("album") or "")

        if art_img is not None:
            canvas = art_img.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
        else:
            canvas = cls._create_gradient_bg((12, 12, 28), (28, 18, 44))
            f_draw = ImageDraw.Draw(canvas)
            cls._draw_vinyl_fallback_icon(f_draw, 32, 22)

        # Semi-transparent dark bottom strip (Rows 46-63, 72% opacity black)
        overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rectangle([0, 46, 63, 63], fill=(0, 0, 0, 185))

        # 1. Top-Left Rank Badge
        rank_str = f"#{rank}"
        text_w = MicroPixelFont.get_text_width(rank_str)
        badge_w = max(13, text_w + 3)
        badge_h = 9
        if rank == 1:
            bg_col, fg_col = (255, 215, 0, 245), (0, 0, 0)
        elif rank == 2:
            bg_col, fg_col = (192, 192, 192, 240), (0, 0, 0)
        elif rank == 3:
            bg_col, fg_col = (205, 127, 50, 240), (0, 0, 0)
        else:
            bg_col, fg_col = (20, 20, 30, 215), (0, 229, 255)

        ov_draw.rectangle([2, 2, 2 + badge_w, 2 + badge_h], fill=bg_col)

        # 2. Top-Right Plays Badge
        play_str = f"{plays}x"
        play_text_w = MicroPixelFont.get_text_width(play_str)
        play_badge_w = max(14, play_text_w + 4)
        play_x = 62 - play_badge_w
        ov_draw.rectangle([play_x, 2, 61, 2 + badge_h], fill=(15, 18, 30, 225))

        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)

        # Draw badges text
        MicroPixelFont.draw_text(draw, 4, 4, rank_str, fg_col)
        play_col = (255, 215, 0) if rank == 1 else (0, 229, 255)
        MicroPixelFont.draw_text(draw, play_x + 2, 4, play_str, play_col)

        # 3. Bottom Strip Text (Line 1 @ Row 48, Line 2 @ Row 56)
        if "artist" in chart_type.lower():
            line1_text = artist
            line2_text = "TOP ARTIST"
        elif "album" in chart_type.lower() or "ep" in chart_type.lower():
            line1_text = album or title
            line2_text = artist
        else:
            line1_text = title
            line2_text = artist

        line1 = cls._clean_label(line1_text, 58)
        line2 = cls._clean_label(line2_text, 58)
        MicroPixelFont.draw_text(draw, 3, 48, line1, (255, 255, 255))
        sub_fg = (255, 215, 0) if rank == 1 else (0, 229, 255)
        MicroPixelFont.draw_text(draw, 3, 56, line2, sub_fg)

        # Pulsating 1px gold frame border around the entire 64x64 canvas for #1
        if rank == 1:
            border_col = (255, 215, 0) if pulse_bright else (160, 120, 10)
            draw.rectangle([0, 0, 63, 63], outline=border_col)

        return canvas


class ChartController:
    """Manages active album completion sessions, leaderboard state, and chart carousel execution."""

    def __init__(self, hub: "PixooHub") -> None:
        self.hub = hub
        self._chart_task: Optional[asyncio.Task] = None
        self.album_session: Optional[Dict[str, Any]] = None
        self.available_periods: List[str] = ["Current"]
        self.last_leaderboard: List[Dict[str, Any]] = []

    def inspect_queue_for_album_session(self, state_attrs: dict, artist: str, title: str, album: str) -> None:
        """Inspect media_player queue attributes and initialize/teardown ActiveAlbumSession."""
        clean_artist = normalize_string(artist) or "unknown"
        clean_album = normalize_string(album) or "unknown"
        if not artist or not album or clean_album in ("unknown", "none", "unknown_album"):
            self.album_session = None
            return

        album_key = f"album:{clean_artist}_{clean_album}"
        if self.album_session and self.album_session.get("album_key") != album_key:
            self.album_session = None

        raw_queue = (
            state_attrs.get("queue")
            or state_attrs.get("queue_items")
            or state_attrs.get("playlist_items")
            or state_attrs.get("media_queue")
            or state_attrs.get("upcoming_tracks")
        )
        if not isinstance(raw_queue, list):
            return

        matched_fps = set()
        matched_canonical = set()
        target_album_l = album.strip().lower()
        target_artist_l = artist.strip().lower()
        for q_item in raw_queue:
            if not isinstance(q_item, dict):
                continue
            q_alb = str(q_item.get("album") or q_item.get("media_album_name") or "").strip()
            q_art = str(q_item.get("artist") or q_item.get("media_artist") or artist).strip()
            q_tit = str(q_item.get("title") or q_item.get("media_title") or q_item.get("name") or "").strip()
            if q_tit and q_alb.lower() == target_album_l and (not q_art or q_art.lower() == target_artist_l):
                matched_fps.add(compute_track_fingerprint(artist, q_tit))
                matched_canonical.add(compute_canonical_title(q_tit))

        if title:
            matched_fps.add(compute_track_fingerprint(artist, title))
            matched_canonical.add(compute_canonical_title(title))

        unique_canonical_count = len(matched_canonical)
        if unique_canonical_count < 3:
            self.album_session = None
            return

        is_deluxe = any(w in target_album_l for w in ("deluxe", "special edition", "expanded", "complete"))
        release_type = "ep" if (unique_canonical_count <= 6 and not is_deluxe) else "album"

        if self.album_session and self.album_session.get("album_key") == album_key:
            self.album_session["required_fingerprints"].update(matched_fps)
            self.album_session["release_type"] = release_type
        else:
            self.album_session = {
                "artist": artist,
                "album": album,
                "album_key": album_key,
                "required_fingerprints": matched_fps,
                "played_fingerprints": set(),
                "release_type": release_type,
                "logged": False,
            }

    async def on_track_scrobbled(self, artist: str, title: str, album: Optional[str]) -> None:
        """Update ActiveAlbumSession when a track satisfies the 30s scrobble threshold."""
        if not self.album_session or not artist or not title or not album:
            return
        album_key = f"album:{normalize_string(artist) or 'unknown'}_{normalize_string(album) or 'unknown'}"
        if self.album_session.get("album_key") != album_key:
            self.album_session = None
            return

        fp = compute_track_fingerprint(artist, title)
        req = self.album_session["required_fingerprints"]
        if fp in req:
            self.album_session["played_fingerprints"].add(fp)
            threshold = math.ceil(0.9 * len(req))
            if len(self.album_session["played_fingerprints"]) >= threshold and not self.album_session["logged"]:
                self.album_session["logged"] = True
                rel_type = self.album_session.get("release_type", "album")
                await self.hub.storage_manager.async_record_album_completion(album_key, artist, album, release_type=rel_type)
                _LOGGER.info("Recorded full %s completion: %s - %s", rel_type.upper(), artist, album)

    async def async_refresh_periods_and_leaderboard(self) -> List[Dict[str, Any]]:
        """Update dynamic chart_period options and sensor leaderboard attribute."""
        cfg = self.hub.config
        chart_type = getattr(cfg, "chart_type", "Top Tracks")
        timeframe = getattr(cfg, "chart_timeframe", "Weekly")
        period_label = getattr(cfg, "chart_period", "Current")
        limit = int(getattr(cfg, "chart_size_limit", 10))
        first_dow = getattr(cfg, "first_day_of_week", "Sunday")

        metadata = await self.hub.storage_manager.async_get_chart_metadata(first_dow)
        self.hub.chart_metadata = metadata

        avail_types = metadata.get("available_types", [])
        if avail_types and chart_type not in avail_types:
            chart_type = avail_types[0]
            cfg.chart_type = chart_type

        avail_tf = metadata.get("available_timeframes", [])
        if avail_tf and timeframe not in avail_tf:
            timeframe = avail_tf[0]
            cfg.chart_timeframe = timeframe

        periods = await self.hub.storage_manager.async_get_available_periods(timeframe, first_dow, chart_type)
        self.available_periods = periods or (["All History"] if timeframe in ("All-Time", "all-time") else ["Current"])
        if period_label not in self.available_periods:
            period_label = self.available_periods[0] if self.available_periods else "Current"
            cfg.chart_period = period_label

        items = await self.hub.storage_manager.async_get_leaderboard(
            chart_type, timeframe, period_label, limit, first_dow
        )
        self.last_leaderboard = items
        if self.hub.update_sensor_callback:
            self.hub.update_sensor_callback()
        return items

    async def async_cancel_chart(self, restore_view: bool = True) -> None:
        """Immediately abort an active chart sequence and optionally restore current view."""
        was_active = self.hub.chart_active
        self.hub.chart_active = False
        if self._chart_task and not self._chart_task.done():
            self._chart_task.cancel()
            try:
                await self._chart_task
            except asyncio.CancelledError:
                pass
        self._chart_task = None
        if was_active and restore_view:
            await self.hub.async_restore_current_view()

    async def async_create_chart(self, override_params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Query leaderboard and launch the animated countdown sequence on the Pixoo64."""
        await self.async_cancel_chart(restore_view=False)
        cfg = self.hub.config
        params = override_params or {}
        chart_type = str(params.get("chart_type") or getattr(cfg, "chart_type", "Top Tracks"))
        timeframe = str(params.get("timeframe") or getattr(cfg, "chart_timeframe", "Weekly"))
        period_label = str(params.get("period") or getattr(cfg, "chart_period", "Current"))
        direction = str(params.get("direction") or getattr(cfg, "chart_direction", "Countdown (10 -> 1)"))
        limit = int(params.get("limit") or getattr(cfg, "chart_size_limit", 10))
        slide_sec = float(params.get("slide_duration") or getattr(cfg, "chart_slide_duration", 4))
        first_dow = getattr(cfg, "first_day_of_week", "Sunday")

        items = await self.hub.storage_manager.async_get_leaderboard(
            chart_type, timeframe, period_label, limit, first_dow
        )
        self.last_leaderboard = items
        self._chart_task = self.hub.hass.async_create_task(
            self._run_chart_sequence(items, chart_type, timeframe, period_label, direction, limit, slide_sec)
        )
        return items

    async def _send_pil_frame(self, img: Image.Image) -> None:
        b64 = await self.hub.hass.async_add_executor_job(self.hub.image_processor.gbase64, img)
        if b64:
            await self.hub.pixoo.send_command({
                "Command": "Draw/CommandList",
                "CommandList": [
                    {"Command": "Draw/ResetHttpGifId"},
                    {
                        "Command": "Draw/SendHttpGif",
                        "PicNum": 1, "PicWidth": 64, "PicOffset": 0,
                        "PicID": 0, "PicSpeed": 1000, "PicData": b64,
                    },
                ],
            })

    async def _run_chart_sequence(
        self, items: List[Dict[str, Any]], chart_type: str, timeframe: str, period_label: str, direction: str, limit: int, slide_sec: float
    ) -> None:
        self.hub.chart_active = True
        saved_live_url = getattr(self.hub.media_data, "live_display_url", None)
        try:
            await self.hub.pixoo.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1})
            intro_img = await self.hub.hass.async_add_executor_job(
                ChartRenderer.render_intro_card, chart_type, timeframe, period_label, limit, not bool(items)
            )
            ordered = list(reversed(items)) if "10 -> 1" in direction or "Countdown" in direction else list(items)
            slides: List[tuple[Dict[str, Any], Image.Image, Optional[Image.Image]]] = []
            gif_frames: List[Image.Image] = [intro_img]
            for entry in ordered:
                art = await self.hub.storage_manager.async_get_chart_artwork(entry, chart_type)
                slide_hi = await self.hub.hass.async_add_executor_job(ChartRenderer.render_rank_slide, entry, chart_type, art, True)
                slide_lo = (
                    await self.hub.hass.async_add_executor_job(ChartRenderer.render_rank_slide, entry, chart_type, art, False)
                    if int(entry.get("rank", 0)) == 1 else None
                )
                slides.append((entry, slide_hi, slide_lo))
                gif_frames.append(slide_hi)

            chart_gif_url = await self.hub.image_processor.async_save_live_display_gif(
                gif_frames, int(max(1.5, slide_sec) * 1000), f"chart_{chart_type}_{timeframe}_{period_label}"
            )
            if chart_gif_url:
                self.hub.media_data.live_display_url = chart_gif_url
            if self.hub.update_sensor_callback:
                self.hub.update_sensor_callback()

            await self.hub.pixoo.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1}, force=True)
            await self.hub.pixoo.send_command({"Command": "Channel/SetIndex", "SelectIndex": 4}, force=True)
            await self.hub.pixoo.send_command({"Command": "Draw/ResetHttpGifId"}, force=True)
            await asyncio.sleep(0.1)

            total_frames = len(gif_frames)
            slide_speed_ms = max(1000, int(slide_sec * 1000))

            for offset, frame in enumerate(gif_frames):
                if not self.hub.chart_active:
                    break
                b64 = await self.hub.hass.async_add_executor_job(self.hub.image_processor.gbase64, frame)
                if b64:
                    await self.hub.pixoo.send_command({
                        "Command": "Draw/SendHttpGif",
                        "PicNum": total_frames,
                        "PicWidth": 64,
                        "PicOffset": offset,
                        "PicID": 0,
                        "PicSpeed": slide_speed_ms,
                        "PicData": b64,
                    })
                    await asyncio.sleep(0.08)

            total_duration = total_frames * max(1.5, slide_sec)
            await asyncio.sleep(total_duration)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Error running Hit Parade chart sequence: %s", err)
        finally:
            self.hub.media_data.live_display_url = saved_live_url
            if self.hub.chart_active:
                self.hub.chart_active = False
                await self.hub.async_restore_current_view()
            elif self.hub.update_sensor_callback:
                self.hub.update_sensor_callback()
