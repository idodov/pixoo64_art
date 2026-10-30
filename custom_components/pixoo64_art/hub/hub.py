"""Core PixooHub orchestrating media player events, persistent storage, analytics, and hardware."""
import asyncio
from datetime import datetime, timedelta
import logging
import time
from time import perf_counter
from typing import Any, Dict, List, Optional

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from ..const import CONF_MEDIA_PLAYER, CONF_PIXOO_IP
from ..device import PixooDevice
from ..image.processor import ImageProcessor
from ..models import Config, MediaData
from ..providers.fallback import FallbackService
from ..providers.spotify import SpotifyService
from ..renderers.chart import ChartController
from ..renderers.notifications import NotificationManager
from ..renderers.progress import ProgressBarManager
from ..storage import PixooStorageManager
from ..storage.database import compute_canonical_title
from .display_builder import DisplayLayerBuilder, HubDisplayMixin
from .lighting import AmbientLightingController, HubPrefetchMixin
from .profiler import HubStateAndConfigMixin, SongProfiler

_LOGGER = logging.getLogger(__name__)


class PixooHub(HubStateAndConfigMixin, HubDisplayMixin, HubPrefetchMixin):
    """Central coordinator for Pixoo64 media display, hybrid caching, and playback analytics."""

    def __init__(self, hass, entry) -> None:
        self.hass, self.entry = hass, entry
        self.pixoo_ip, self.media_player = entry.data[CONF_PIXOO_IP], entry.data[CONF_MEDIA_PLAYER]
        self._current_live_gif_url, self.ui_state, self.sensor, self.analytics_sensor, self.select_entities = None, {}, None, None, {}
        self.config, self._unsub_listeners, self._image_lock = Config(entry), [], asyncio.Lock()
        self._active_song_key = self._prefetched_media = None
        self.select_index = self.last_valid_index = 0
        self.device_brightness, self.device_screen_on, self.ai_generating, self.ai_status, self.chart_active = 100, True, False, "Idle", False

        self.websession = async_get_clientsession(hass)
        self.storage_manager = PixooStorageManager(self.hass, self.config)
        self.pixoo_device = self.pixoo = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.hass, self.config, self.websession, storage_manager=self.storage_manager)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.media_data = MediaData(self.hass, self.config, self.image_processor, self.websession)
        self.fallback_service = FallbackService(self.config, self.image_processor, self.websession, self.spotify_service, self.pixoo_device, hub=self)
        self.progress_manager, self.notification_manager = ProgressBarManager(self.config, self.hass), NotificationManager(self.config, self.pixoo_device, self.image_processor, self.hass)
        self.lighting, self.layer_builder = AmbientLightingController(self.hass, self.websession, self.config), DisplayLayerBuilder()
        self.chart_controller = ChartController(self)

        self.is_art_visible = self.lyrics_active_mode = self._is_animation_active = False
        self.last_text_payload_hash, self.last_progress_str = None, ""
        self.cached_static_items, self.current_lyrics_items = [], []
        self.progress_timer_gen_id = self.scheduler_generation_id = self.clock_timer_gen_id = 0
        self._current_clock_pil_img = self._current_clock_song_key = None
        self._current_rendered_b64 = self._current_rendered_pil_img = None
        self._pause_timed_out = False

        self.osd_mode, self.last_volume_level = None, 0.0
        self._scrobbled_current_track, self._track_started_monotonic = False, 0.0
        self.current_task = self.debounce_task = self._prefetch_task = self._playlist_prefetch_task = self._early_send_task = self._lyrics_bg_task = None
        self._progress_timer_unsub = self._clock_timer_unsub = self._lyrics_timer_unsub = self._pending_render_unsub = None
        self._prefetch_timer_unsub = self._early_send_timer_unsub = self._pause_timeout_unsub = self._volume_osd_timer_unsub = None
        self._force_next_text_render = self._is_processing_image = False

        self._early_slider_sent_for = self.prefetch_next_artist = self.prefetch_next_title = None
        self.prefetch_status = self.spotify_slider_status = self.playlist_prefetch_status = "Idle"
        self.spotify_slider_frames = self.playlist_queue_total = self.playlist_cached_count = 0
        self.spotify_slider_artist = self.spotify_slider_last_error = self.playlist_queue_position = None
        self.playlist_window_range, self.profile_data = "None", {}

    async def control_light(self, action: str, rgb_color: Optional[tuple] = None, is_night: bool = True) -> None:
        await self.lighting.control_light(action, rgb_color, is_night)

    async def control_wled_light(self, action: str, colors: Optional[list] = None, is_night: bool = True) -> None:
        await self.lighting.control_wled_light(action, colors, is_night)

    async def _build_text_items_list(self, font_color: str, bg_color: str, scope: str = "all"):
        return self.layer_builder.build_text_items(self.config, self.media_data, self.osd_mode, self.last_volume_level, font_color, bg_color, scope=scope)

    def set_sensor(self, sensor) -> None:
        self.sensor = sensor

    def set_sensors(self, status_sensor, analytics_sensor) -> None:
        self.sensor = status_sensor
        self.analytics_sensor = analytics_sensor

    async def async_update_analytics_sensor(self) -> None:
        if not getattr(self, "analytics_sensor", None):
            return
        try:
            stats = await self.storage_manager.async_get_analytics_summary()
            total_plays = stats.get("db_total_play_events", 0)
            self.analytics_sensor.update_state(total_plays, stats)
        except Exception as e:
            _LOGGER.debug("Could not update analytics sensor: %s", e)

    def get_current_track_rank(self, artist: str, title: str) -> Optional[int]:
        if not artist or not title or not hasattr(self, "chart_controller"):
            return None
        leaderboard = getattr(self.chart_controller, "last_leaderboard", []) or []
        c_art = str(artist).strip().lower()
        c_tit = compute_canonical_title(title).strip().lower()
        for item in leaderboard:
            if str(item.get("artist", "")).strip().lower() == c_art:
                i_tit = compute_canonical_title(item.get("title", "")).strip().lower()
                if c_tit == i_tit or c_tit in i_tit or i_tit in c_tit:
                    return item.get("rank")
        return None

    def update_sensor_callback(self) -> None:
        period_ent = self.select_entities.get("chart_period")
        if period_ent and getattr(period_ent, "hass", None):
            period_ent.async_write_ha_state()
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs.update({
                "chart_active": self.chart_active,
                "chart_leaderboard": self.chart_controller.last_leaderboard,
                "chart_metadata": getattr(self, "chart_metadata", {}),
                "has_temperature_sensor": bool(getattr(self.config, "temperature_sensor", None)),
            })
            live_url = getattr(self.media_data, "live_display_url", None) or self._current_live_gif_url
            if live_url:
                attrs["live_display_url"] = live_url
            self.sensor.update_state(getattr(self.sensor, "_attr_native_value", "Ready"), attrs)

    async def async_create_chart(self, override_params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return await self.chart_controller.async_create_chart(override_params)

    async def async_cancel_chart(self, restore_view: bool = True) -> None:
        await self.chart_controller.async_cancel_chart(restore_view=restore_view)

    async def async_restore_current_view(self) -> None:
        self.is_art_visible, self._active_song_key = False, None
        await self.force_update()

    async def async_clear_cache(self, scope: str = "all") -> None:
        await self.storage_manager.async_clear_cache(scope)
        self.image_processor.image_cache.clear()
        self.image_processor.raw_image_cache.clear()
        self.fallback_service._artwork_cache.clear()
        self._prefetched_media = None
        for attr in ("vinyl_frames_b64", "cassette_frames_b64", "slider_frames_b64", "slider_album_urls"):
            setattr(self.media_data, attr, [])
        await self.chart_controller.async_refresh_periods_and_leaderboard()
        await self.async_update_analytics_sensor()

    async def initialize(self) -> None:
        await self.storage_manager.async_initialize()
        await self._sync_hardware_state_from_device(allow_channel_update=True)
        await asyncio.sleep(0.5)
        self._apply_logic_matrix()
        await self.chart_controller.async_refresh_periods_and_leaderboard()
        await self.async_update_analytics_sensor()
        async def _daily_prune(_now=None):
            await self.storage_manager.async_prune(max_masters=getattr(self.config, "max_cached_albums", 1000))

        async def _periodic_channel_poll(_now=None):
            try:
                if self.osd_mode == "Pause" or not self.device_screen_on:
                    return
                curr_ch = await self.pixoo_device.get_current_channel_index()
                if curr_ch is not None and 0 <= curr_ch <= 3:
                    if curr_ch != self.last_valid_index:
                        self.last_valid_index = self.select_index = curr_ch
                        self.update_channel_sensor_attribute(curr_ch)
                    if self.is_art_visible:
                        self.is_art_visible = False
            except Exception as e:
                _LOGGER.debug("Periodic channel poll note: %s", e)

        self._unsub_listeners.append(async_track_state_change_event(self.hass, [self.media_player], self.safe_state_change_callback))
        self._unsub_listeners.append(async_track_time_interval(self.hass, _daily_prune, timedelta(hours=24)))
        self._unsub_listeners.append(async_track_time_interval(self.hass, _periodic_channel_poll, timedelta(seconds=15)))

        async def _delayed_startup():
            await asyncio.sleep(4.0)
            state = self.hass.states.get(self.media_player)
            if state and self._is_player_active(state):
                self._active_song_key = None
                await self.force_update()
            else:
                await self.control_light("off")
                await self.control_wled_light("off")
                try:
                    curr_ch = await self.pixoo_device.get_current_channel_index()
                    if curr_ch == 4:
                        target_ch = 0 if getattr(self, "last_valid_index", 0) in (4, -1) or getattr(self, "last_valid_index", 0) < 0 else self.last_valid_index
                        await self.pixoo_device.send_command({
                            "Command": "Draw/CommandList",
                            "CommandList": [
                                {"Command": "Draw/ClearHttpText"},
                                {"Command": "Draw/ResetHttpGifId"},
                            ],
                        })
                        await asyncio.sleep(0.05)
                        await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": target_ch})
                        self.update_channel_sensor_attribute(target_ch)
                except Exception:
                    pass

        self.hass.async_create_task(_delayed_startup())

    async def terminate(self) -> None:
        await self.async_cancel_chart(restore_view=False)
        for unsub in self._unsub_listeners:
            unsub()
        self._cleanup_timers()
        self._cancel_tasks()
        self.image_processor.shutdown()
        try:
            await self.control_light("off")
            await self.control_wled_light("off")
        except Exception:
            pass

    async def _handle_media_change(self, event) -> None:
        if self.notification_manager.is_active or not self.ui_state.get("master_control", True):
            return
        live_state = self.hass.states.get(self.media_player)
        new_state = live_state or event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not new_state:
            return
        if self.chart_active:
            if self._is_player_active(new_state):
                await self.media_data.update(new_state)
                if self.media_data.track_changed:
                    self._scrobbled_current_track, self._track_started_monotonic = False, time.monotonic()
                    self.chart_controller.inspect_queue_for_album_session(dict(new_state.attributes), self.media_data.artist, self.media_data.title, self.media_data.album or "")
                self.progress_timer_gen_id += 1
                await self._update_progress_bar_loop()
            return

        pause_setting = self.ui_state.get("pause_timeout") or getattr(self.config, "pause_timeout", "15s")
        if new_state.state == "paused":
            if getattr(self, "_pause_timed_out", False):
                return
            if pause_setting not in ["Disabled (0s)", "0s", "Disabled"]:
                if self.osd_mode == "Pause":
                    return
                self._stop_lyrics_scheduler()
                self._stop_clock_scheduler()
                self._cleanup_timers(["_progress_timer_unsub", "_pending_render_unsub", "_pause_timeout_unsub", "_volume_osd_timer_unsub"])
                self.progress_timer_gen_id += 1
                self.osd_mode = "Pause"
                self.cached_static_items, self.last_text_payload_hash = [], None
                pause_b64 = await self.hass.async_add_executor_job(
                    self.image_processor.generate_pause_frame,
                    getattr(self, "_current_rendered_pil_img", None),
                    self.media_data,
                )
                if pause_b64:
                    if getattr(self, "_is_animation_active", False):
                        await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": 4}, force=True)
                        self._is_animation_active = False
                    await self.pixoo_device.send_command({"Command": "Draw/ClearHttpText"}, force=True)
                    await self.pixoo_device.send_command({"Command": "Draw/ResetHttpGifId"}, force=True)
                    await asyncio.sleep(0.05)
                    await self.pixoo_device.send_command({
                        "Command": "Draw/SendHttpGif",
                        "PicNum": 1,
                        "PicWidth": 64,
                        "PicOffset": 0,
                        "PicID": 0,
                        "PicSpeed": 10000,
                        "PicData": pause_b64,
                    }, force=True)
                if self.sensor:
                    self.update_sensor_callback()
                if pause_setting != "Never":
                    import re
                    m = re.search(r"\d+", str(pause_setting))
                    delay_sec = int(m.group(0)) if m else 15
                    _LOGGER.info("Pixoo64 paused! Scheduling pause timeout in %s seconds (setting=%s)", delay_sec, pause_setting)
                    self._pause_timeout_unsub = async_call_later(self.hass, delay_sec, self._execute_pause_timeout)
            else:
                self._pause_timed_out = True
                _LOGGER.info("Pixoo64 paused with pause screen disabled. Turning off display.")
                await self._send_off_command(force_screen_off=True)
                self._stop_lyrics_scheduler()
            return

        is_resuming_from_pause = bool(self.osd_mode == "Pause" or getattr(self, "_pause_timed_out", False) or (old_state and old_state.state == "paused"))
        if is_resuming_from_pause and self._is_player_active(new_state):
            self._pause_timed_out = False
            self.osd_mode = None
            self._active_song_key = None
            self._cleanup_timers(["_pause_timeout_unsub"])
            if getattr(self, "_current_live_gif_url", None):
                self.media_data.live_display_url = self._current_live_gif_url
            if self.sensor:
                self.update_sensor_callback()

        if not self._is_player_active(new_state):
            if not getattr(self, "_pause_timed_out", False):
                await self._send_off_command()
                self._stop_lyrics_scheduler()
            return

        if old_state and self._is_player_active(old_state):
            new_vol, old_vol = new_state.attributes.get("volume_level"), old_state.attributes.get("volume_level")
            if new_vol is not None and old_vol is not None and new_vol != old_vol:
                self.last_volume_level = new_vol
                vol_setting = self.ui_state.get("volume_osd", "2s")
                if vol_setting not in ["Disabled (0s)", "0s", "Disabled"]:
                    self.osd_mode = "Volume"
                    self.request_text_render(force=True)
                    self._cleanup_timers(["_volume_osd_timer_unsub"])
                    async def _clear_vol_osd(_now=None):
                        if self.osd_mode == "Volume":
                            self.osd_mode = None
                            self.request_text_render(force=True)
                    self._volume_osd_timer_unsub = async_call_later(self.hass, int(vol_setting.replace("s", "").split()[0]), _clear_vol_osd)
                cur_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
                is_same_song_showing = self.is_art_visible and getattr(self, "_active_song_key", None) == cur_key
                if old_state.attributes.get("media_title") == new_state.attributes.get("media_title") and old_state.attributes.get("entity_picture") == new_state.attributes.get("entity_picture") and is_same_song_showing:
                    self.progress_timer_gen_id += 1
                    await self._update_progress_bar_loop()
                    return

        raw_new_title = str(new_state.attributes.get("media_title") or "")
        cleaned_new_title = (self.media_data.clean_title(raw_new_title) if getattr(self.config, "clean_title", True) else raw_new_title).strip().lower()
        new_track_artist = str(new_state.attributes.get("media_artist") or "").strip().lower()
        current_title, current_artist = str(self.media_data.title or "").strip().lower(), str(self.media_data.artist or "").strip().lower()
        new_picture, old_picture = new_state.attributes.get("entity_picture"), getattr(self.media_data, "picture", None)
        new_alb = str(new_state.attributes.get("album_name") or new_state.attributes.get("media_album_name") or "").strip().lower()
        cur_alb = str(getattr(self.media_data, "album", "") or "").strip().lower()
        pic_diff = bool(new_picture and new_picture != old_picture)

        new_playlist = str(new_state.attributes.get("media_playlist") or "").strip().lower()
        cur_playlist = str(getattr(self.media_data, "playlist", "") or "").strip().lower()
        playlist_diff = bool(new_playlist and cur_playlist and new_playlist != cur_playlist)

        new_track_num = new_state.attributes.get("media_track")
        cur_track_num = getattr(self.media_data, "track_number", None)
        track_num_diff = bool(new_track_num is not None and cur_track_num is not None and str(new_track_num) != str(cur_track_num))

        old_pos = float(getattr(self.media_data, "media_position", 0.0) or 0.0)
        try:
            new_pos = float(new_state.attributes.get("media_position", old_pos))
        except (ValueError, TypeError):
            new_pos = old_pos
        pos_restarted = bool(old_pos > 20.0 and new_pos < 3.0)

        is_same_track = (
            cleaned_new_title
            and cleaned_new_title == current_title
            and new_track_artist == current_artist
            and not pic_diff
            and new_alb == cur_alb
            and not playlist_diff
            and not track_num_diff
            and not pos_restarted
        )

        if is_same_track:
            try:
                self.media_data.media_position = new_pos
                self.media_data.media_duration = float(new_state.attributes.get("media_duration", self.media_data.media_duration))
                pos_str = new_state.attributes.get("media_position_updated_at")
                self.media_data.media_position_updated_at = pos_str if isinstance(pos_str, datetime) else (datetime.fromisoformat(pos_str.replace("Z", "+00:00")) if pos_str else self.media_data.media_position_updated_at)
            except Exception:
                pass
            if not self._is_processing_image and self.is_art_visible and f"{current_artist}_{current_title}" == self._active_song_key:
                self.progress_timer_gen_id += 1
                await self._update_progress_bar_loop()
                if self.prefetch_status in ["Idle", "No next song detected", "Cancelled", ""]:
                    self._schedule_prefetch()
            if self._is_processing_image or (self.is_art_visible and f"{current_artist}_{current_title}" == self._active_song_key):
                return

        self._stop_lyrics_scheduler(); self._stop_clock_scheduler(); self._cleanup_timers()
        self._cancel_tasks(["_prefetch_task", "_playlist_prefetch_task", "current_task", "_early_send_task", "_lyrics_bg_task"])
        self._active_song_key = None
        await self.media_data.update(new_state)
        self._fetch_external_temperature()
        if not self.media_data.title and not getattr(self.media_data, "playing_tv", False):
            await self._send_off_command(); return
        self.prefetch_status, self.prefetch_next_artist, self.prefetch_next_title, self._current_live_gif_url = "Idle", None, None, None
        self.media_data.live_display_url = None
        self._update_prefetch_sensor_state()
        self.current_task = self.hass.async_create_task(self._process_and_send())
        self._playlist_prefetch_task = self.hass.async_create_task(self._run_playlist_prefetch())

    async def _process_and_send(self) -> None:
        if self.chart_active: return
        self._is_processing_image = True
        async with self._image_lock:
            profiler = SongProfiler(f"{getattr(self.media_data, 'artist', '') or ''} - {getattr(self.media_data, 'title', '') or ''}")
            try:
                self._apply_logic_matrix()
                if self.prefetch_next_title and (self.prefetch_next_title == self.media_data.title or self.prefetch_next_artist == self.media_data.artist):
                    self.prefetch_status, self.prefetch_next_artist, self.prefetch_next_title = "Idle", None, None
                    self._update_prefetch_sensor_state()
                current_song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
                if current_song_key != getattr(self, "_active_song_key", None):
                    self._scrobbled_current_track, self._track_started_monotonic = False, time.monotonic()
                    self.media_data.play_recorded = False
                    st = self.hass.states.get(self.media_player)
                    if st:
                        self.chart_controller.inspect_queue_for_album_session(dict(st.attributes), self.media_data.artist, self.media_data.title, self.media_data.album or "")

                current_mode = self.ui_state.get("display_mode", "Standard")
                current_filter, current_crop = getattr(self.config, "image_filter", "None"), getattr(self.config, "crop_mode", "No Crop")
                is_force_ai = (current_mode == "Force AI" or getattr(self.config, "force_ai", False)) and getattr(self.config, "pollinations", None) and not getattr(self.media_data, "radio_logo", False) and not getattr(self.media_data, "playing_tv", False)
                if is_force_ai:
                    self.set_ai_generating(True, "Generating AI Artwork...")

                has_timing = getattr(self.media_data, "media_duration", 0) > 0 and not getattr(self.media_data, "playing_radio", False) and not getattr(self.media_data, "playing_tv", False)
                lyrics_avail = getattr(self.media_data, "lyrics_available", False) and has_timing
                configured_mode = current_mode
                new_lyrics_found = getattr(self.config, "show_lyrics", False) and lyrics_avail and len(self.media_data.lyrics) > 0
                effective_mode = "Standard" if (configured_mode == "Lyrics" and not new_lyrics_found) else configured_mode

                if getattr(self.media_data, "playing_tv", False) and await self._handle_tv_display(configured_mode):
                    return

                start_time = time.perf_counter()
                current_album, current_artist, current_pic_url = self.media_data.album, self.media_data.artist, self.media_data.picture
                can_skip = (
                    current_mode == getattr(self, "_last_rendered_mode", None) and current_filter == getattr(self, "_last_rendered_filter", None)
                    and current_crop == getattr(self, "_last_rendered_crop", None) and current_song_key == getattr(self, "_active_song_key", None)
                    and ((current_pic_url and current_pic_url == getattr(self, "_last_rendered_pic_url", None) and "token=" not in current_pic_url) or (current_album and current_album == getattr(self, "_last_rendered_album", None) and not getattr(self.media_data, "radio_logo", False)))
                    and new_lyrics_found == getattr(self, "lyrics_active_mode", False) and self.is_art_visible and getattr(self.media_data, "pic_source", None) != "Internal"
                    and not any(getattr(self.config, k, False) for k in ("vinyl_mode", "cassette_mode", "burned", "force_ai", "analog_clock", "spotify_slide", "artist_slide"))
                )
                if can_skip:
                    self.is_art_visible, self.last_text_payload_hash, self._active_song_key, self._is_processing_image = True, None, current_song_key, False
                    self.cached_static_items = await self._build_text_items_list(getattr(self.media_data, "lyrics_font_color", "#FFFFFF"), getattr(self.media_data, "background_color", "#000000"), scope="static")
                    self.progress_timer_gen_id += 1
                    if not new_lyrics_found:
                        await self._render_and_send_text_layers(force=True)
                    else:
                        self.lyrics_active_mode = True
                        await self._calculate_and_schedule_next()
                    await self._update_progress_bar_loop()
                    self._schedule_prefetch()
                    return

                self._last_rendered_mode, self._last_rendered_filter, self._last_rendered_crop = current_mode, current_filter, current_crop
                prefetched_hit, processed_data = self._consume_prefetched_media(is_force_ai)
                t0_art = perf_counter()
                try:
                    if not processed_data:
                        saved_gif_url = self.media_data.live_display_url
                        processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
                        if prefetched_hit and saved_gif_url:
                            self.media_data.live_display_url = saved_gif_url
                finally:
                    profiler.add("artwork_pipeline", perf_counter() - t0_art)

                processed_data = processed_data or await self.hass.async_add_executor_job(self.fallback_service._get_fallback_black_image_data, self.media_data)
                base64_image = processed_data.get("base64_image")
                self._current_rendered_b64 = base64_image
                self._current_rendered_pil_img = processed_data.get("pil_image")
                font_color, bg_color_str, bg_color_rgb = processed_data.get("font_color", "#FFFFFF"), processed_data.get("background_color", "#000000"), processed_data.get("background_color_rgb", (0, 0, 0))
                color1, color2, color3 = processed_data.get("color1"), processed_data.get("color2"), processed_data.get("color3")

                sun_state = self.hass.states.get("sun.sun")
                is_night = (sun_state.state == "below_horizon") if (sun_state and sun_state.state in ["above_horizon", "below_horizon"]) else (datetime.now().hour >= 18 or datetime.now().hour < 7)
                if not getattr(self.media_data, "playing_tv", False):
                    self.hass.async_create_task(self.control_light("on", bg_color_rgb, is_night))
                    self.hass.async_create_task(self.control_wled_light("on", [color1, color2, color3], is_night))

                not_special_stream = not getattr(self.media_data, "radio_logo", False) and not getattr(self.media_data, "playing_tv", False)
                is_spotify_slider = getattr(self.config, "spotify_slide", False) and not_special_stream
                is_artist_slider = getattr(self.config, "artist_slide", False) and not_special_stream
                is_vinyl = getattr(self.config, "vinyl_mode", False) and not_special_stream
                is_cassette = getattr(self.config, "cassette_mode", False) and not_special_stream
                is_analog_clock = getattr(self.config, "analog_clock", False) and not getattr(self.media_data, "playing_tv", False)

                early_slider_match = (is_spotify_slider or is_artist_slider) and self._early_slider_sent_for == f"slider_{current_song_key}"
                if early_slider_match:
                    setattr(self.media_data, "spotify_slide_pass" if is_spotify_slider else "artist_slide_pass", True)
                early_vinyl_match = bool(is_vinyl and self._early_slider_sent_for == f"vinyl_{current_song_key}")
                early_cassette_match = bool(is_cassette and self._early_slider_sent_for == f"cassette_{current_song_key}")
                self._early_slider_sent_for = None

                if is_vinyl and not early_vinyl_match:
                    vinyl_frames = getattr(self.media_data, "vinyl_frames_b64", None) or await self.hass.async_add_executor_job(self.image_processor.generate_vinyl_frames, processed_data.get("pil_image"), self.media_data)
                    if vinyl_frames:
                        await self._send_early_frames(vinyl_frames, 70 if len(vinyl_frames) > 16 else 140, "", "Vinyl")
                        profiler.mark_first_frame()
                        early_vinyl_match = True
                if is_cassette and not early_cassette_match:
                    cassette_frames = getattr(self.media_data, "cassette_frames_b64", None) or await self.hass.async_add_executor_job(self.image_processor.generate_cassette_frames, processed_data.get("pil_image"), self.media_data)
                    if cassette_frames:
                        await self._send_early_frames(cassette_frames, 100, "", "Cassette")
                        profiler.mark_first_frame()
                        early_cassette_match = True
                if is_analog_clock:
                    self._current_clock_pil_img, self._current_clock_song_key = processed_data.get("pil_image"), current_song_key
                    base64_image = await self.hass.async_add_executor_job(self.image_processor.generate_analog_clock_frame, self._current_clock_pil_img, self.media_data) or base64_image

                if not (early_slider_match or early_vinyl_match or early_cassette_match or is_spotify_slider or is_artist_slider):
                    was_anim = getattr(self, "_is_animation_active", False)
                    needs_wake = not self.is_art_visible or not self.device_screen_on
                    if not self.device_screen_on:
                        await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1}, force=True)
                    if needs_wake or was_anim:
                        await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": 4}, force=True)
                    await self.pixoo_device.send_command({"Command": "Draw/ResetHttpGifId"}, force=True)
                    await asyncio.sleep(0.05)
                    await self.pixoo_device.send_command({
                        "Command": "Draw/SendHttpGif",
                        "PicNum": 1,
                        "PicWidth": 64,
                        "PicOffset": 0,
                        "PicID": 0,
                        "PicSpeed": 10000,
                        "PicData": base64_image,
                    }, force=True)
                    self._is_animation_active = False
                    profiler.mark_first_frame()

                self.device_screen_on, self.is_art_visible = True, True
                if self._active_song_key != current_song_key:
                    self.last_text_payload_hash = None
                self._active_song_key = current_song_key
                self._last_rendered_album, self._last_rendered_artist, self._last_rendered_pic_url = current_album, current_artist, self.media_data.picture
                self.media_data.lyrics_font_color, self.media_data.background_color = font_color, bg_color_str
                self._fetch_external_temperature()
                self.cached_static_items = await self._build_text_items_list(font_color, bg_color_str, scope="static")
                self.progress_timer_gen_id += 1

                if (is_spotify_slider or is_artist_slider) and not early_slider_match:
                    await self._run_live_slider_display(is_spotify_slider)

                await asyncio.sleep(0.3)
                if new_lyrics_found != self.lyrics_active_mode:
                    self.lyrics_active_mode = new_lyrics_found
                    if self.lyrics_active_mode:
                        processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
                        await self.pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ResetHttpGifId"}, {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 10000, "PicData": processed_data.get("base64_image")}]})
                        await self._calculate_and_schedule_next()
                    else:
                        self._stop_lyrics_scheduler()
                elif self.lyrics_active_mode:
                    await self._calculate_and_schedule_next()

                self._is_processing_image = False
                if not self.lyrics_active_mode:
                    self.last_text_payload_hash = None
                    await self._render_and_send_text_layers(force=True)

                await self._update_progress_bar_loop()
                self._schedule_prefetch()
                self.hass.async_create_task(self._sync_hardware_state_from_device(allow_channel_update=False))
                if has_timing and not getattr(self.media_data, "playing_tv", False) and not getattr(self.media_data, "playing_radio", False):
                    l_key = f"{self.media_data.artist}|{self.media_data.title_original}".lower()
                    if not getattr(self.media_data, "lyrics_available", False) or l_key not in self.media_data.lyrics_provider.lyrics_cache:
                        self._cancel_tasks(["_lyrics_bg_task"])
                        self._lyrics_bg_task = self.hass.async_create_task(
                            self._async_resolve_lyrics(current_song_key, configured_mode)
                        )
                if is_analog_clock:
                    self._schedule_analog_clock_tick(processed_data)

                self.profile_data = profiler.build_attributes()
                self._current_live_gif_url = getattr(self.media_data, "live_display_url", None) if (is_analog_clock or is_vinyl or is_cassette or is_spotify_slider or is_artist_slider) else (processed_data.get("live_display_url") or getattr(self.media_data, "live_display_url", None))
                if not self._current_live_gif_url and not (is_analog_clock or is_vinyl or is_cassette or is_spotify_slider or is_artist_slider) and "pil_image" in processed_data:
                    album_tag = self.media_data.album if getattr(self.media_data, "album", None) else self.media_data.title
                    s_key = f"std_{self.media_data.artist}_{album_tag}_{current_filter}_{current_crop}"
                    self._current_live_gif_url = await self.image_processor.async_save_live_display_gif([processed_data["pil_image"]], 1000, s_key)
                    processed_data["live_display_url"] = self._current_live_gif_url
                self.media_data.live_display_url = self._current_live_gif_url
                t_stats = await self.storage_manager.async_get_track_stats(self.media_data.artist, self.media_data.title)
                c_plays = t_stats.get("plays", 0)
                c_rank = self.get_current_track_rank(self.media_data.artist, self.media_data.title)
                self._publish_main_sensor_state(
                    processed_data, effective_mode, configured_mode, lyrics_avail, has_timing, new_lyrics_found,
                    time.perf_counter() - start_time, prefetched_hit, track_plays=c_plays, track_rank=c_rank
                )
            except asyncio.CancelledError:
                pass
            except Exception as e:
                _LOGGER.error("Execution error: %s", e)
            finally:
                self.ai_generating, self.ai_status, self._is_processing_image = False, "Idle", False

    async def _async_resolve_lyrics(self, expected_song_key: str, configured_mode: str) -> None:
        """Fetch lyrics in the background without blocking image processing."""
        try:
            has_lyrics = await self.media_data.async_fetch_lyrics()
            if getattr(self, "_active_song_key", None) != expected_song_key or self.chart_active:
                return

            current_mode = self.ui_state.get("display_mode", configured_mode)
            show_lyrics_mode = (current_mode == "Lyrics")
            new_lyrics_found = bool(has_lyrics and show_lyrics_mode and len(getattr(self.media_data, "lyrics", [])) > 0)

            if self.sensor:
                attrs = dict(self.sensor._attr_extra_state_attributes or {})
                attrs["lyrics_available"] = bool(self.media_data.lyrics_available)
                attrs["lyrics_found"] = new_lyrics_found
                if new_lyrics_found:
                    attrs["active_mode"] = "Lyrics"
                self.sensor.update_state(self.sensor._attr_native_value, attrs)

            if new_lyrics_found:
                if not self.lyrics_active_mode:
                    self.lyrics_active_mode = True
                    self.media_data.lyrics_provider.ensure_timeline_built(self.media_data.artist, self.media_data.title_original)
                    processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
                    if processed_data and processed_data.get("base64_image"):
                        await self.pixoo_device.send_command({
                            "Command": "Draw/SendHttpGif",
                            "PicNum": 1,
                            "PicWidth": 64,
                            "PicOffset": 0,
                            "PicID": 0,
                            "PicSpeed": 10000,
                            "PicData": processed_data.get("base64_image"),
                        }, force=True)
                    await self._calculate_and_schedule_next()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.debug("Background lyrics resolution note: %s", e)
