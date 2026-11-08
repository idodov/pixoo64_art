"""Display layer builder (HTTP text/OSD items) and Hub display/scheduler mixin."""
import asyncio
from datetime import datetime
import json
import logging
import time
from typing import Dict, List, Optional
from homeassistant.helpers.event import async_call_later

from ..models import Config, MediaData, get_bidi, has_bidi, unidecode
from ..renderers.clock import AnalogClockRenderer
from ..storage.analytics import PixooAnalytics

_LOGGER = logging.getLogger(__name__)


class DisplayLayerBuilder:
    """Builds HTTP text item payloads including OSD, clock, weather, and track info."""

    @staticmethod
    def build_text_items(
        config: Config,
        media_data: MediaData,
        osd_mode: Optional[str],
        last_volume_level: float,
        font_color: str,
        bg_color: str,
        scope: str = "all",
    ) -> List[Dict]:
        text_items = []
        y_info = 3 if getattr(config, "overlay_top", True) else 56
        align_mode = getattr(config, "overlay_align", "Clock Right, Temp Left")
        show_clk = getattr(config, "show_clock", True)
        show_tmp = getattr(config, "temperature", False)

        if align_mode == "Clock Left, Temp Right":
            x_c, x_t = 3, 47
        elif align_mode == "Centered":
            x_c, x_t = (22, 3) if (show_clk and not show_tmp) else ((44, 24) if (show_tmp and not show_clk) else (36, 3))
        else:
            x_c, x_t = 44, 3

        def _append_clk_tmp(y_pos: int):
            if show_clk:
                w_c = min(32, max(16, 64 - x_c))
                h_c = min(16, max(6, 64 - y_pos))
                text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_pos, "dir": 0, "font": 18, "TextWidth": w_c, "Textheight": h_c, "speed": 100, "align": 1, "color": font_color})
            if show_tmp:
                t_val = getattr(media_data, "temperature", None)
                t_type = 22 if t_val else 17
                w_t = min(20, max(14, 64 - x_t))
                h_t = min(6, max(6, 64 - y_pos))
                text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_pos, "dir": 0, "font": 18, "TextWidth": w_t, "Textheight": h_t, "speed": 100, "align": 1, "color": font_color, "TextString": str(t_val) if t_type == 22 else ""})

        if osd_mode:
            if osd_mode == "Pause":
                return []
            elif osd_mode == "Volume":
                pct = int((last_volume_level or 0) * 100)
                bars = int((pct / 100) * 10)
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 20, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": f"VOL {pct}%", "color": font_color})
                text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 32, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": "=" * bars + "-" * (10 - bars), "color": font_color})
            _append_clk_tmp(y_info)
            return text_items

        if getattr(config, "cassette_mode", False):
            _append_clk_tmp(56)
            return text_items

        y_text = 0 if getattr(config, "top_text", False) else 48
        d_artist = unidecode(media_data.artist) if media_data.artist else ""
        d_title = unidecode(media_data.title) if media_data.title else ""
        txt = f"{d_artist} - {d_title}"
        if len(txt) > 14:
            txt += "        "
        rtl = 1 if has_bidi(txt) else 0
        is_burned = getattr(config, "burned", False)

        if getattr(config, "special_mode", False):
            text_items.append({"TextId": 1, "type": 14, "x": 3, "y": 1, "dir": 0, "font": 18, "TextWidth": 33, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})
            text_items.append({"TextId": 2, "type": 5, "x": 1, "y": 1, "dir": 0, "font": 18, "TextWidth": 63, "Textheight": 6, "speed": 100, "align": 2, "color": font_color})
            t_val = getattr(media_data, "temperature", None)
            t_type = 22 if t_val else 17
            text_items.append({"TextId": 3, "type": t_type, "x": 48, "y": 1, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": str(t_val) if t_type == 22 else ""})
            if getattr(config, "show_text", True) and not getattr(media_data, "playing_tv", False) and not is_burned:
                a_rtl, t_rtl = (1 if has_bidi(d_artist) else 0), (1 if has_bidi(d_title) else 0)
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 42, "dir": a_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(d_artist) if a_rtl else d_artist, "color": font_color})
                text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 52, "dir": t_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(d_title) if t_rtl else d_title, "color": font_color})
        else:
            if getattr(config, "show_text", True) and not getattr(media_data, "playing_tv", False) and not is_burned:
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": y_text, "dir": rtl, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(txt) if rtl else txt, "color": font_color})
            _append_clk_tmp(y_info)

        return text_items


class HubDisplayMixin:
    """Mixin for PixooHub managing text/lyrics/clock/progress schedulers and display power/notifications."""

    async def _handle_tv_display(self, configured_mode: str) -> bool:
        await asyncio.gather(
            self.control_light("off"),
            self.control_wled_light("off"),
            return_exceptions=True,
        )
        if not getattr(self.config, "tv_mode", False) or self.media_data.picture == "TV_IS_ON":
            target_channel = 0 if getattr(self, "last_valid_index", 0) in (4, -1) or getattr(self, "last_valid_index", 0) < 0 else self.last_valid_index
            await self.pixoo_device.send_command({"Command": "Draw/ClearHttpText"})
            self._active_text_ids = set()
            self._active_text_layers = {}
            await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": target_channel})
            if getattr(self.config, "full_control", False) or self.ui_state.get("full_control", False):
                self.device_screen_on = False
                await asyncio.sleep(0.1)
                await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 0})
            else:
                self.device_screen_on = True
                await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1})
            self.is_art_visible, self._active_song_key = False, None
            if self.sensor:
                self.sensor.update_state("TV", {"artist": "TV", "media_title": "TV", "active_mode": "TV", "configured_mode": configured_mode, "lyrics_available": False, "has_timing": False, "image_source": "Internal", "pixoo64_channel": target_channel, "brightness": self.device_brightness, "screen_power": "On" if self.device_screen_on else "Off", "ai_generating": False, "ai_status": "Idle"})
            return True
        return False

    async def _run_live_slider_display(self, is_spotify_slider: bool) -> None:
        if is_spotify_slider:
            self.spotify_slider_status, self.spotify_slider_artist = f"Loading Live Slider for {self.media_data.artist}...", self.media_data.artist
            self._update_prefetch_sensor_state()
            await self.spotify_service.prepare_slider_for_media(self.media_data)
            if getattr(self.config, "special_mode_spotify_slider", False):
                await self.spotify_service.spotify_album_art_animation(self.pixoo_device, self.media_data, self.select_index)
            else:
                await self.spotify_service.spotify_albums_slide(self.pixoo_device, self.media_data, self.select_index, send_to_device=True)
            ok = getattr(self.media_data, "spotify_slide_pass", False)
            self.spotify_slider_status = f"Active Live ({self.media_data.slider_frames} frames)" if ok else f"Live Failed: {self.media_data.slider_error or 'No albums found'}"
            self.spotify_slider_frames = self.media_data.slider_frames if ok else 0
        else:
            self.spotify_slider_status, self.spotify_slider_artist = f"Loading Artist Gallery for {self.media_data.artist}...", self.media_data.artist
            self._update_prefetch_sensor_state()
            await self.fallback_service.play_artist_gallery_slide(self.pixoo_device, self.media_data, send_to_device=True)
            ok = getattr(self.media_data, "artist_slide_pass", False)
            self.spotify_slider_status = f"Active Live ({self.media_data.slider_frames} frames)" if ok else f"Live Failed: {self.media_data.slider_error or 'No artist images found'}"
            self.spotify_slider_frames = self.media_data.slider_frames if ok else 0
        if ok:
            self._is_animation_active = True
        self._mark_hardware_text_wiped()

    _ALL_MANAGED_TEXT_IDS = frozenset((1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15, 19, 20, 21))

    def _mark_hardware_text_wiped(self) -> None:
        """Record that hardware HTTP text layers were wiped by ResetHttpGifId / SendHttpGif."""
        self._active_text_layers = {}
        self._active_text_ids = set()
        self.last_text_payload_hash = None

    def request_text_render(self, force: bool = False) -> None:
        if self.notification_manager.is_active or getattr(self, "chart_active", False):
            return
        if force:
            self._force_next_text_render = True
        self._cleanup_timers(["_pending_render_unsub"])
        delay = 0.02 if force else 0.08
        self._pending_render_unsub = async_call_later(self.hass, delay, self._execute_text_render)

    async def _execute_text_render(self, now=None) -> None:
        self._pending_render_unsub = None
        if self.notification_manager.is_active or getattr(self, "chart_active", False):
            return
        force = getattr(self, "_force_next_text_render", False)
        self._force_next_text_render = False
        await self._render_and_send_text_layers(force=force)

    async def _prepare_text_items(self) -> tuple[list[dict], int, set]:
        items = []
        font_color = getattr(self.media_data, "lyrics_font_color", "#FFFFFF")
        bg_color = getattr(self.media_data, "background_color", "#000000")

        if self.osd_mode:
            items.extend(await self._build_text_items_list(font_color, bg_color, scope="static"))
        elif self.lyrics_active_mode and self.current_lyrics_items is not None:
            items.extend(self.current_lyrics_items)
        else:
            if not self.cached_static_items:
                self.cached_static_items = await self._build_text_items_list(font_color, bg_color, scope="static")
            items.extend(self.cached_static_items)

        if getattr(self.media_data, "show_progress_bar", False) and not self.osd_mode:
            pos = self._get_current_media_position()
            bar_str, _ = self.progress_manager.calculate(pos, getattr(self.media_data, "media_duration", 0.0))
            self.last_progress_str = bar_str
            pb = await self.progress_manager.get_payload_item(self.media_data)
            if pb:
                items.extend(pb)

        used_ids = {item.get("TextId") for item in items if "TextId" in item}
        active_hsh = hash(json.dumps(items, sort_keys=True))
        return items, active_hsh, used_ids

    async def _render_and_send_text_layers(self, force: bool = False) -> None:
        if (
            not self.is_art_visible
            or self.notification_manager.is_active
            or getattr(self, "chart_active", False)
            or (not force and getattr(self, "_is_processing_image", False))
        ):
            return
        self._cleanup_timers(["_pending_render_unsub"])
        self._force_next_text_render = False

        items, active_hsh, current_ids = await self._prepare_text_items()
        prev_layers = getattr(self, "_active_text_layers", {})

        # 1. Blank discontinued text IDs in-place without calling ClearHttpText
        # (Draw/ClearHttpText wipes ALL text layers on Pixoo firmware regardless of arguments).
        ids_to_clear = set(prev_layers.keys()) - current_ids
        blank_items = []
        if ids_to_clear:
            for t_id in sorted(ids_to_clear):
                blank_items.append({
                    "TextId": t_id,
                    "type": 22,
                    "x": 0,
                    "y": 0,
                    "dir": 0,
                    "font": 2,
                    "TextWidth": 64,
                    "Textheight": 16,
                    "speed": 0,
                    "align": 2,
                    "TextString": "",
                    "color": "#000000",
                })
                prev_layers.pop(t_id, None)

        # 2. Check if text layers actually changed
        has_changed = (
            force
            or bool(blank_items)
            or active_hsh != getattr(self, "last_text_payload_hash", None)
            or any(t_id not in prev_layers for t_id in current_ids)
        )
        if not has_changed:
            return

        # 3. Always dispatch full active items + blanking items via Draw/SendHttpItemList.
        # This guarantees persistent widgets (digital clock, temp) are never lost or
        # swallowed by a previous frame decode, updating in-place with zero flicker.
        items_to_send = list(blank_items) + list(items)
        if items_to_send:
            await self.pixoo_device.send_command({"Command": "Draw/SendHttpItemList", "ItemList": items_to_send}, force=force)

        self._active_text_layers = {
            item["TextId"]: json.dumps(item, sort_keys=True)
            for item in items
            if "TextId" in item
        }
        self._active_text_ids = current_ids
        self.last_text_payload_hash = active_hsh

    async def _send_frame_with_text(self, b64_frame: str, pic_speed: int = 10000, channel_switch: bool = False) -> None:
        """Send the image frame and active HTTP text layers back-to-back under a single device lock."""
        self._cleanup_timers(["_pending_render_unsub"])
        self._force_next_text_render = False
        self.is_art_visible = True

        items: list[dict] = []
        active_hsh: Optional[int] = None
        current_ids: set = set()
        if not self.notification_manager.is_active and not getattr(self, "chart_active", False):
            items, active_hsh, current_ids = await self._prepare_text_items()

        cmds = []
        if channel_switch:
            cmds.append({"Command": "Channel/SetIndex", "SelectIndex": 4})
            self.select_index = 4
        cmds.append({"Command": "Draw/ResetHttpGifId"})
        cmds.append({
            "Command": "Draw/SendHttpGif",
            "PicNum": 1,
            "PicWidth": 64,
            "PicOffset": 0,
            "PicID": 0,
            "PicSpeed": pic_speed,
            "PicData": b64_frame,
        })
        frame_payload = {"Command": "Draw/CommandList", "CommandList": cmds}
        text_payload = {"Command": "Draw/SendHttpItemList", "ItemList": items} if items else None

        self._mark_hardware_text_wiped()
        frame_ok, text_ok = await self.pixoo_device.send_frame_and_text(frame_payload, text_payload)
        if frame_ok and text_ok and items:
            self._active_text_layers = {
                item["TextId"]: json.dumps(item, sort_keys=True)
                for item in items
                if "TextId" in item
            }
            self._active_text_ids = current_ids
            self.last_text_payload_hash = active_hsh

    async def _resend_text_after_image(self) -> None:
        """Immediately re-apply active text layers after a multi-frame animation upload."""
        self._mark_hardware_text_wiped()
        self.is_art_visible = True
        await self._render_and_send_text_layers(force=True)

    async def _calculate_and_schedule_next(self, send_now: bool = True) -> None:
        if self.notification_manager.is_active or getattr(self, "chart_active", False) or not self.lyrics_active_mode:
            return
        self.scheduler_generation_id += 1
        gen_id = self.scheduler_generation_id
        pos = self._get_current_media_position() - getattr(self.config, "lyrics_sync", 0.0)
        layout, delay = self.media_data.lyrics_provider.get_refresh_plan(pos)
        self.current_lyrics_items = []
        font_id = getattr(self.config, "lyrics_font", 2)

        if layout:
            for i, it in enumerate(layout[:6]):
                self.current_lyrics_items.append({"TextId": i + 10, "type": 22, "x": 0, "y": int(it["y"]), "dir": int(it["dir"]), "font": font_id, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": it["text"], "color": getattr(self.media_data, "lyrics_font_color", "#FFFFFF")})

        if send_now:
            self.request_text_render()
        self._cleanup_timers(["_lyrics_timer_unsub"])

        async def _next_lyrics(_now=None):
            if self.scheduler_generation_id == gen_id:
                await self._calculate_and_schedule_next()

        self._lyrics_timer_unsub = async_call_later(self.hass, delay if delay is not None else 5.0, _next_lyrics)

    def _schedule_analog_clock_tick(self, processed_data: Optional[dict] = None) -> None:
        self._cleanup_timers(["_clock_timer_unsub"])
        if not getattr(self.config, "analog_clock", False) or not self.is_art_visible or getattr(self, "chart_active", False):
            return
        if processed_data is not None:
            self._current_clock_pil_img, self._current_clock_song_key = processed_data.get("pil_image"), self._active_song_key
        if not self._current_clock_pil_img or not self._current_clock_song_key:
            return
        self.clock_timer_gen_id += 1
        gen_id = self.clock_timer_gen_id
        now = datetime.now()
        delay = (60 - now.second - (now.microsecond / 1_000_000.0)) + 0.5
        if delay <= 0.5:
            delay = 60.0

        async def _tick(event_time):
            self._clock_timer_unsub = None
            if (
                self.clock_timer_gen_id != gen_id
                or not getattr(self.config, "analog_clock", False)
                or not self.is_art_visible
                or getattr(self, "chart_active", False)
                or getattr(self, "_is_processing_image", False)
                or self.notification_manager.is_active
                or self.osd_mode == "Pause"
            ):
                return
            current_song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
            if not self._current_clock_pil_img or self._current_clock_song_key != current_song_key:
                return
            clock_b64 = await self.hass.async_add_executor_job(self.image_processor.generate_analog_clock_frame, self._current_clock_pil_img, self.media_data)
            if (
                self.clock_timer_gen_id != gen_id
                or self._current_clock_song_key != current_song_key
                or getattr(self, "_is_processing_image", False)
                or self.notification_manager.is_active
                or self.osd_mode == "Pause"
            ):
                return
            if clock_b64:
                self._current_rendered_b64 = clock_b64
                self._cleanup_timers(["_pending_render_unsub"])
                self._current_live_gif_url = self.media_data.live_display_url
                await self._send_frame_with_text(clock_b64)
                self.update_sensor_callback()
            self._schedule_analog_clock_tick()

        self._clock_timer_unsub = async_call_later(self.hass, delay, _tick)

    async def _update_progress_bar_loop(self) -> None:
        if self.notification_manager.is_active or getattr(self, "_is_processing_image", False):
            return
        state = self.hass.states.get(self.media_player)
        if not state or state.state not in ["playing", "on"]:
            return

        # Failsafe watchdog: check if the media_player is playing a different track or playlist
        curr_t = str(state.attributes.get("media_title") or "")
        clean_t = self.media_data.clean_title(curr_t) if getattr(self.config, "clean_title", True) else curr_t
        curr_p = str(state.attributes.get("media_playlist") or "")
        curr_alb = str(state.attributes.get("album_name") or state.attributes.get("media_album_name") or "")
        prev_t = str(getattr(self.media_data, "title", "") or "")
        prev_p = str(getattr(self.media_data, "playlist", "") or "")
        prev_alb = str(getattr(self.media_data, "album", "") or "")
        if clean_t and (
            clean_t.strip().lower() != prev_t.strip().lower()
            or (curr_p and prev_p and curr_p.strip().lower() != prev_p.strip().lower())
            or (curr_alb and prev_alb and curr_alb.strip().lower() != prev_alb.strip().lower())
        ):
            _LOGGER.info("Pixoo64 watchdog detected song/playlist change in progress loop: '%s' -> '%s'. Triggering update.", prev_t, clean_t)
            self.hass.async_create_task(self.force_update())
            return

        pos = self._get_current_media_position()
        dur = float(getattr(self.media_data, "media_duration", 0.0) or 0.0)
        elapsed_wall = time.monotonic() - getattr(self, "_track_started_monotonic", time.monotonic())
        played_sec = max(pos, elapsed_wall)

        is_radio = getattr(self.media_data, "playing_radio", False)
        pic_src = getattr(self.media_data, "pic_source", None)
        is_radio_logo = getattr(self.media_data, "radio_logo", False)

        if not self._scrobbled_current_track and PixooAnalytics.is_scrobble_eligible(
            played_sec,
            dur,
            getattr(self.media_data, "play_recorded", False),
            getattr(self.media_data, "playing_tv", False),
            is_radio,
            getattr(self.media_data, "artist", ""),
            getattr(self.media_data, "title", ""),
            pic_source=pic_src,
            is_radio_logo=is_radio_logo,
        ):
            self._scrobbled_current_track = True
            self.media_data.play_recorded = True
            artist = getattr(self.media_data, "artist", "")
            title = getattr(self.media_data, "title", "")
            album = getattr(self.media_data, "album", None)
            source_tag = "radio" if is_radio else "stream"

            async def _record_and_refresh():
                await self.storage_manager.async_record_playback(artist, title, album, source=source_tag)
                await self.chart_controller.on_track_scrobbled(artist, title, album)
                await self.chart_controller.async_refresh_periods_and_leaderboard()
                await self.async_update_analytics_sensor()
                if self.sensor:
                    t_stats = await self.storage_manager.async_get_track_stats(artist, title)
                    attrs = dict(self.sensor._attr_extra_state_attributes or {})
                    attrs["current_track_plays"] = t_stats.get("plays", 0)
                    attrs["current_track_rank"] = self.get_current_track_rank(artist, title)
                    self.sensor.update_state(self.sensor._attr_native_value, attrs)

            self.hass.async_create_task(_record_and_refresh())

        gen_id = self.progress_timer_gen_id

        async def _next_prog(_now=None):
            if self.progress_timer_gen_id == gen_id:
                await self._update_progress_bar_loop()

        if not getattr(self.config, "progress_bar_enabled", False) or getattr(self, "chart_active", False):
            if not self._scrobbled_current_track:
                self._cleanup_timers(["_progress_timer_unsub"])
                self._progress_timer_unsub = async_call_later(self.hass, 5.0, _next_prog)
            return

        bar_str, delay = self.progress_manager.calculate(pos, dur)
        if self.is_art_visible and (bar_str != self.last_progress_str or self.last_text_payload_hash is None):
            self.last_progress_str = bar_str
            self.request_text_render()

        self._cleanup_timers(["_progress_timer_unsub"])
        self._progress_timer_unsub = async_call_later(self.hass, delay if delay is not None else 5.0, _next_prog)

    def _stop_lyrics_scheduler(self) -> None:
        self.lyrics_active_mode = False
        self.scheduler_generation_id += 1
        self.current_lyrics_items = []

    def _stop_clock_scheduler(self) -> None:
        self.clock_timer_gen_id += 1
        self._current_clock_pil_img = self._current_clock_song_key = None
        self._cleanup_timers(["_clock_timer_unsub"])

    async def _send_off_command(self, force_screen_off: bool = False) -> None:
        if getattr(self, "chart_active", False):
            if not self.ui_state.get("master_control", True):
                await self.async_cancel_chart(restore_view=False)
            else:
                return

        # Failsafe: Never turn off or switch away if master_control is active and media_player is actively playing music or paused
        st = self.hass.states.get(self.media_player) if getattr(self, "hass", None) else None
        if self.ui_state.get("master_control", True) and st and (self._is_player_active(st) or (st.state == "paused" and not force_screen_off)):
            _LOGGER.warning(
                "Pixoo64 _send_off_command blocked: %s is actively playing or paused without timeout. Preserving display.",
                self.media_player,
            )
            return

        was_pause = bool(force_screen_off or self.osd_mode == "Pause" or getattr(self, "_pause_timed_out", False))
        is_full_control = bool(self.ui_state.get("full_control", False) or getattr(self.config, "full_control", False))
        should_screen_off = is_full_control

        self.is_art_visible = self.ai_generating = self._is_animation_active = False
        self._active_song_key = self.osd_mode = self.prefetch_next_artist = self.prefetch_next_title = None
        self.ai_status = self.prefetch_status = self.spotify_slider_status = self.playlist_prefetch_status = "Idle"
        self._early_slider_sent_for = self._prefetched_media = self.spotify_slider_artist = self.spotify_slider_last_error = None
        self.spotify_slider_frames = 0
        self._last_rendered_pic_url = self._last_rendered_album = self._last_rendered_artist = self._current_live_gif_url = None
        self.cached_static_items, self.last_text_payload_hash, self.last_progress_str = [], None, ""

        self._stop_clock_scheduler()
        self._stop_lyrics_scheduler()
        self._cleanup_timers()
        self._cancel_tasks(["_prefetch_task", "_playlist_prefetch_task", "_early_send_task"])
        await asyncio.gather(
            self.control_light("off"),
            self.control_wled_light("off"),
            return_exceptions=True,
        )

        target_channel = 0 if getattr(self, "last_valid_index", 0) in (4, -1) or getattr(self, "last_valid_index", 0) < 0 else self.last_valid_index
        _LOGGER.info("Pixoo64 _send_off_command: force_screen_off=%s, was_pause=%s, should_screen_off=%s, target_channel=%s", force_screen_off, was_pause, should_screen_off, target_channel)

        await self.pixoo_device.send_command({"Command": "Draw/ClearHttpText"}, force=True)
        self._active_text_ids = set()
        self._active_text_layers = {}
        await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": target_channel}, force=True)
        await asyncio.sleep(0.15)

        if should_screen_off:
            self.device_screen_on = False
            await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 0}, force=True)
            await asyncio.sleep(0.4)
            await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 0}, force=True)
        else:
            self.device_screen_on = True
            await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1}, force=True)
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs.update({
                "media_player": self.media_player,
                "pixoo64_channel": target_channel,
                "brightness": self.device_brightness,
                "screen_power": "On" if self.device_screen_on else "Off",
                "active_mode": "Channel",
                "ai_generating": False,
                "ai_status": "Idle",
                "chart_active": False,
                "chart_leaderboard": self.chart_controller.last_leaderboard,
                "chart_metadata": getattr(self, "chart_metadata", {}),
                "has_temperature_sensor": bool(getattr(self.config, "temperature_sensor", None)),
            })
            self.sensor.update_state("Off", attrs)

    async def _execute_pause_timeout(self, now=None) -> None:
        self._pause_timeout_unsub = None
        st = self.hass.states.get(self.media_player) if getattr(self, "hass", None) else None
        if st and self._is_player_active(st):
            _LOGGER.debug("Pixoo64 pause timeout aborted: media_player is actively playing.")
            self._pause_timed_out = False
            return
        _LOGGER.info("Pixoo64 Pause screen timeout fired! Turning off display and returning to channel.")
        self._pause_timed_out = True
        await self._send_off_command(force_screen_off=True)

    async def async_handle_notification_service(self, call) -> None:
        await self.async_send_notification_payload(dict(call.data))

    async def async_send_notification_payload(self, payload: dict) -> None:
        message = payload.get("message") or payload.get("title") or payload.get("model")
        if not message:
            return
        if getattr(self, "chart_active", False):
            await self.async_cancel_chart(restore_view=False)
        was_screen_on = True
        try:
            curr_ch = await self.pixoo_device.get_current_channel_index()
            if curr_ch is not None and 0 <= curr_ch <= 3:
                self.last_valid_index = self.select_index = curr_ch
            was_screen_on = await self.pixoo_device.get_screen_on_state()
        except Exception:
            pass
        media_state = self.hass.states.get(self.media_player)
        is_full_ctrl = bool(getattr(self.config, "full_control", False) or self.ui_state.get("full_control", False))
        if not (media_state and media_state.state in ["playing", "on"]) and is_full_ctrl and not self.is_art_visible:
            was_screen_on = False
        self.notification_manager.is_active = True
        self._stop_lyrics_scheduler()
        self._cleanup_timers()
        self._cancel_tasks()
        self._active_text_ids = set()
        self._active_text_layers = {}
        await self.notification_manager.display(payload)
        rechecked = self.hass.states.get(self.media_player)
        if rechecked and rechecked.state in ["playing", "on"]:
            if payload.get("burned_text") in (False, "false", "0", "no", "off"):
                await self.pixoo_device.send_command({"Command": "Draw/ClearHttpText"})
            self._active_text_ids = set()
            self._active_text_layers = {}
            self.is_art_visible, self._active_song_key = False, None
            await self.force_update()
        elif is_full_ctrl and not was_screen_on:
            target_ret = 0 if getattr(self, "last_valid_index", 0) in (4, -1) or getattr(self, "last_valid_index", 0) < 0 else self.last_valid_index
            await self.pixoo_device.send_command({"Command": "Draw/ClearHttpText"})
            self._active_text_ids = set()
            self._active_text_layers = {}
            await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": target_ret})
            await asyncio.sleep(0.1)
            await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 0})
            self.is_art_visible, self._active_song_key = False, None
        else:
            target_ret = 0 if getattr(self, "last_valid_index", 0) in (4, -1) or getattr(self, "last_valid_index", 0) < 0 else self.last_valid_index
            await self.pixoo_device.send_command({"Command": "Draw/ClearHttpText"})
            self._active_text_ids = set()
            self._active_text_layers = {}
            await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": target_ret})
            await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1})
