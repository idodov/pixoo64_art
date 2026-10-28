"""Song timing profiler and Hub state/configuration management mixin."""
from datetime import datetime, timezone
import logging
from time import perf_counter
from typing import Any, Optional, Tuple
from homeassistant.helpers.event import async_call_later

from ..const import (
    CONF_CHART_SIZE_LIMIT, CONF_CHART_SLIDE_DURATION, CONF_FIRST_DAY_OF_WEEK, CONF_LIGHT_ENTITY,
    CONF_MAX_CACHED_ALBUMS, CONF_PERSISTENT_CACHE_ENABLED, CONF_PLAYLIST_PREFETCH, CONF_WLED_IP,
    DEFAULT_CHART_SIZE_LIMIT, DEFAULT_CHART_SLIDE_DURATION, DEFAULT_FIRST_DAY_OF_WEEK,
    DEFAULT_MAX_CACHED_ALBUMS, DEFAULT_PERSISTENT_CACHE_ENABLED,
)

_LOGGER = logging.getLogger(__name__)


class SongProfiler:
    """Benchmarks per-song pipeline execution stages and frame delivery."""

    def __init__(self, title: str = "") -> None:
        self.title, self.start, self.first_frame = title, perf_counter(), None
        self.timings: dict[str, float] = {}
        self.counters: dict[str, Any] = {}

    def add(self, key: str, duration: float) -> None:
        self.timings[key] = self.timings.get(key, 0.0) + duration

    def set(self, key: str, value: Any) -> None:
        self.counters[key] = value

    def mark_first_frame(self) -> None:
        if self.first_frame is None:
            self.first_frame = perf_counter() - self.start

    def build_attributes(self) -> dict[str, Any]:
        total = perf_counter() - self.start
        attrs: dict[str, Any] = {
            "profile_song": self.title, "profile_total": round(total, 3),
            "profile_first_frame": round(self.first_frame, 3) if self.first_frame is not None else None,
        }
        attrs.update({f"profile_{k}": round(v, 3) for k, v in self.timings.items()})
        attrs.update({f"profile_{k}": v for k, v in self.counters.items()})
        return attrs

    def build_log_line(self) -> str:
        total = perf_counter() - self.start
        parts = [f"song='{self.title}'", f"total={total:.3f}s"]
        if self.first_frame is not None:
            parts.append(f"first_frame={self.first_frame:.3f}s")
        parts.extend(f"{k}={v:.3f}s" for k, v in sorted(self.timings.items()))
        parts.extend(f"{k}={v}" for k, v in sorted(self.counters.items()))
        return "[PROFILE] " + " ".join(parts)


class HubStateAndConfigMixin:
    """Provides hardware telemetry sync, UI logic matrix, and timer/task helpers for PixooHub."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(self.ui_state)
        attrs.update({
            "media_player": self.media_player, "pixoo64_channel": self.last_valid_index,
            "brightness": self.device_brightness, "screen_power": "On" if self.device_screen_on else "Off",
            "current_track_plays": getattr(self.sensor, "_attr_extra_state_attributes", {}).get("current_track_plays", 0) if self.sensor else 0,
            "current_track_rank": getattr(self.sensor, "_attr_extra_state_attributes", {}).get("current_track_rank", None) if self.sensor else None,
            "ai_generating": getattr(self, "ai_generating", False), "ai_status": getattr(self, "ai_status", "Idle"),
            "chart_active": getattr(self, "chart_active", False),
            "chart_leaderboard": getattr(self.chart_controller, "last_leaderboard", []) if hasattr(self, "chart_controller") else [],
            "chart_metadata": getattr(self, "chart_metadata", {}),
            "has_temperature_sensor": bool(getattr(self.config, "temperature_sensor", None)),
        })
        if self._current_live_gif_url:
            attrs["live_display_url"] = self._current_live_gif_url
        if getattr(self.media_data, "original_image_url", None):
            attrs["original_image_url"] = self.media_data.original_image_url
        if self.profile_data:
            attrs.update(self.profile_data)
        return attrs

    def _consume_prefetched_media(self, is_force_ai: bool) -> Tuple[bool, Optional[dict]]:
        if getattr(self, "_prefetched_media", None) and not is_force_ai:
            p_art, p_tit = str(self._prefetched_media.artist or "").strip().lower(), str(self._prefetched_media.title or "").strip().lower()
            c_art, c_tit = str(self.media_data.artist or "").strip().lower(), str(self.media_data.title or "").strip().lower()
            processed_data = getattr(self._prefetched_media, "processed_data", None)
            if p_art and c_art and p_art == c_art and p_tit and c_tit and (p_tit == c_tit or p_tit.startswith(c_tit) or c_tit.startswith(p_tit)) and processed_data:
                for attr in ("pic_url", "original_image_url", "pic_source", "live_display_url", "vinyl_frames_b64", "cassette_frames_b64", "slider_frames_b64", "slider_album_urls", "slider_frames"):
                    setattr(self.media_data, attr, getattr(self._prefetched_media, attr, [] if "frames_" in attr or "urls" in attr else None))
                self._prefetched_media = None
                return True, processed_data
            self._prefetched_media = None
        return False, None

    def _publish_main_sensor_state(
        self, processed_data: dict, effective_mode: str, configured_mode: str, lyrics_avail: bool, has_timing: bool, new_lyrics_found: bool, duration: float, prefetched_hit: bool, track_plays: int = 0, track_rank: Any = None
    ) -> None:
        if not self.sensor:
            return
        color1, color2, color3 = processed_data.get("color1"), processed_data.get("color2"), processed_data.get("color3")
        sensor_attrs = {
            "artist": self.media_data.artist, "media_title": self.media_data.title, "media_player": self.media_player,
            "current_track_plays": int(track_plays or 0), "current_track_rank": track_rank,
            "image_source": self.media_data.pic_source,
            "image_url": self.media_data.original_image_url or (self.media_data.picture if (self.media_data.picture and str(self.media_data.picture).startswith("https://") and "/api/media_player_proxy/" not in str(self.media_data.picture)) else None) or self.media_data.pic_url,
            "original_image_url": self.media_data.original_image_url,
            "live_display_url": self._current_live_gif_url,
            "active_mode": effective_mode, "configured_mode": configured_mode, "lyrics_available": lyrics_avail, "has_timing": has_timing,
            "font_color": processed_data.get("font_color", "#FFFFFF"), "background_color": processed_data.get("background_color", "#000000"),
            "background_color_rgb": processed_data.get("background_color_rgb"), "brightness_lower_part": processed_data.get("brightness_lower_part"),
            "color1": color1, "color2": color2, "color3": color3, "wled_colors": [color1, color2, color3],
            "general_cache_size": len(self.image_processor.image_cache), "general_cache_limit": self.image_processor.cache_size,
            "playlist_prefetch_setting": getattr(self.config, "playlist_prefetch_range", "Disabled"),
            "playlist_prefetch_status": self.playlist_prefetch_status, "playlist_queue_total": self.playlist_queue_total,
            "playlist_queue_position": self.playlist_queue_position, "playlist_cached_count": self.playlist_cached_count,
            "playlist_window_range": self.playlist_window_range, "process_duration": f"{duration:.2f}s (RAM)" if prefetched_hit else f"{duration:.2f}s",
            "progress_bar_active": getattr(self.media_data, "show_progress_bar", False), "lyrics_found": new_lyrics_found,
            "pixoo64_channel": self.last_valid_index, "brightness": self.device_brightness, "screen_power": "On" if self.device_screen_on else "Off",
            "prefetch_status": self.prefetch_status, "prefetch_next_artist": self.prefetch_next_artist, "prefetch_next_title": self.prefetch_next_title,
            "slider_status": self.spotify_slider_status, "slider_frames": self.spotify_slider_frames, "slider_last_error": self.spotify_slider_last_error,
            "ai_generating": False, "ai_status": "Idle", "chart_active": getattr(self, "chart_active", False),
            "chart_leaderboard": getattr(self.chart_controller, "last_leaderboard", []) if hasattr(self, "chart_controller") else [],
            "chart_metadata": getattr(self, "chart_metadata", {}),
            "has_temperature_sensor": bool(getattr(self.config, "temperature_sensor", None)),
            **self.profile_data,
        }
        self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)

    def update_channel_sensor_attribute(self, channel_idx: int) -> None:
        try:
            ch = int(channel_idx)
            if 0 <= ch <= 3:
                self.last_valid_index = self.select_index = ch
                self.is_art_visible = False
        except (ValueError, TypeError):
            pass
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["pixoo64_channel"] = self.last_valid_index
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    def update_brightness_sensor_attribute(self, brightness: int) -> None:
        try:
            self.device_brightness = max(0, min(100, int(brightness)))
        except (ValueError, TypeError):
            pass
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["brightness"] = self.device_brightness
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    def update_power_sensor_attribute(self, is_on: bool) -> None:
        self.device_screen_on = bool(is_on)
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["screen_power"] = "On" if self.device_screen_on else "Off"
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    def set_ai_generating(self, is_generating: bool, status: str = "Idle") -> None:
        self.ai_generating, self.ai_status = is_generating, status
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["ai_generating"], attrs["ai_status"] = self.ai_generating, self.ai_status
            if is_generating and (getattr(self.config, "force_ai", False) or self.ui_state.get("display_mode") == "Force AI"):
                attrs["active_mode"] = attrs["configured_mode"] = "Force AI"
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    async def _sync_hardware_state_from_device(self, allow_channel_update: bool = True) -> None:
        try:
            conf = await self.pixoo_device.get_all_conf()
            if not conf:
                return
            if "LightSwitch" in conf:
                self.device_screen_on = conf.get("LightSwitch", 1) == 1
                if not self.device_screen_on:
                    self.is_art_visible = False
            if "Brightness" in conf:
                try:
                    self.device_brightness = int(conf["Brightness"])
                except (ValueError, TypeError):
                    pass
            if allow_channel_update and "SelectIndex" in conf:
                try:
                    curr_ch = int(conf["SelectIndex"])
                    if 0 <= curr_ch <= 3:
                        self.last_valid_index = self.select_index = curr_ch
                        self.is_art_visible = False
                except (ValueError, TypeError):
                    pass
            elif not self.device_screen_on:
                self.is_art_visible = False
            if self.sensor:
                attrs = dict(self.sensor._attr_extra_state_attributes or {})
                attrs.update({"pixoo64_channel": self.last_valid_index, "brightness": self.device_brightness, "screen_power": "On" if self.device_screen_on else "Off"})
                self.sensor.update_state(self.sensor._attr_native_value, attrs)
        except Exception as e:
            _LOGGER.debug("Hardware state sync error: %s", e)

    def _cleanup_timers(self, timers=None) -> None:
        for attr in timers or ["_progress_timer_unsub", "_lyrics_timer_unsub", "_pending_render_unsub", "_prefetch_timer_unsub", "_early_send_timer_unsub", "_pause_timeout_unsub", "_volume_osd_timer_unsub", "_clock_timer_unsub"]:
            unsub = getattr(self, attr, None)
            if unsub:
                unsub()
                setattr(self, attr, None)

    def _cancel_tasks(self, tasks=None) -> None:
        for attr in tasks or ["current_task", "debounce_task", "_prefetch_task", "_playlist_prefetch_task", "_early_send_task", "_lyrics_bg_task"]:
            task = getattr(self, attr, None)
            if task and not task.done():
                task.cancel()
            setattr(self, attr, None)

    def _get_current_media_position(self) -> float:
        pos = getattr(self.media_data, "media_position", 0.0) or 0.0
        updated_at = getattr(self.media_data, "media_position_updated_at", None)
        if updated_at:
            try:
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                pos += (datetime.now(timezone.utc) - updated_at).total_seconds()
            except Exception:
                pass
        return pos

    def _update_prefetch_sensor_state(self) -> None:
        if not self.sensor:
            return
        old_attrs = dict(self.sensor._attr_extra_state_attributes) if self.sensor._attr_extra_state_attributes else {}
        attrs = dict(old_attrs)
        attrs.update({
            "prefetch_status": self.prefetch_status, "prefetch_next_artist": self.prefetch_next_artist,
            "prefetch_next_title": self.prefetch_next_title, "slider_status": self.spotify_slider_status,
            "slider_frames": self.spotify_slider_frames, "slider_artist": self.spotify_slider_artist,
            "spotify_slider_last_error": self.spotify_slider_last_error,
            "general_cache_size": len(self.image_processor.image_cache), "general_cache_limit": self.image_processor.cache_size,
            "playlist_prefetch_setting": getattr(self.config, "playlist_prefetch_range", "Disabled"),
            "playlist_prefetch_status": self.playlist_prefetch_status, "playlist_queue_total": self.playlist_queue_total,
            "playlist_queue_position": self.playlist_queue_position, "playlist_cached_count": self.playlist_cached_count,
            "playlist_window_range": self.playlist_window_range, "pixoo64_channel": self.last_valid_index,
            "brightness": self.device_brightness, "screen_power": "On" if self.device_screen_on else "Off",
            "chart_active": getattr(self, "chart_active", False),
            "chart_leaderboard": getattr(self.chart_controller, "last_leaderboard", []) if hasattr(self, "chart_controller") else [],
        })
        if self._current_live_gif_url:
            attrs["live_display_url"] = self._current_live_gif_url
        if getattr(self.media_data, "original_image_url", None):
            attrs["original_image_url"] = self.media_data.original_image_url
        if attrs != old_attrs:
            self.sensor.update_state(getattr(self.sensor, "_attr_native_value", "Initializing"), attrs)

    @property
    def is_ai_available(self) -> bool:
        options, data = self.entry.options, self.entry.data
        key = options.get("pollinations_key") or data.get("pollinations_key") or getattr(self.config, "pollinations", "")
        return bool(key and isinstance(key, str) and len(str(key).strip()) > 5)

    @property
    def is_spotify_available(self) -> bool:
        options, data = self.entry.options, self.entry.data
        cid = options.get("spotify_client_id") or data.get("spotify_client_id") or getattr(self.config, "spotify_client_id", "")
        csec = options.get("spotify_client_secret") or data.get("spotify_client_secret") or getattr(self.config, "spotify_client_secret", "")
        return bool(len(str(cid).strip()) > 5 and len(str(csec).strip()) > 5)

    def _apply_logic_matrix(self) -> None:
        options, data = self.entry.options, self.entry.data
        self.config.pollinations = options.get("pollinations_key", data.get("pollinations_key", ""))
        self.config.ai_fallback = options.get("ai_model", data.get("ai_model", "black-forest-labs/flux.1-schnell"))
        self.config.spotify_client_id = options.get("spotify_client_id", data.get("spotify_client_id", ""))
        self.config.spotify_client_secret = options.get("spotify_client_secret", data.get("spotify_client_secret", ""))
        self.config.musicbrainz = options.get("musicbrainz_enabled", data.get("musicbrainz_enabled", True))
        self.config.internet_archive = options.get("internet_archive_enabled", data.get("internet_archive_enabled", True))
        self.config.audiodb_enabled = options.get("audiodb_enabled", data.get("audiodb_enabled", True))
        self.config.prefetch_enabled = options.get("prefetch_enabled", data.get("prefetch_enabled", False))
        self.config.tidal_client_id = options.get("tidal_client_id", data.get("tidal_client_id", ""))
        self.config.tidal_client_secret = options.get("tidal_client_secret", data.get("tidal_client_secret", ""))
        self.config.lastfm, self.config.discogs = options.get("lastfm_key", data.get("lastfm_key", "")), options.get("discogs_token", data.get("discogs_token", ""))
        self.config.tv_mode, self.config.temperature_sensor = options.get("tv_mode", data.get("tv_mode", False)), options.get("temperature_entity", data.get("temperature_entity"))
        self.config.osd_overlay = options.get("osd_overlay", data.get("osd_overlay", "Enabled"))
        self.config.pause_timeout = options.get("pause_timeout", data.get("pause_timeout", "15s"))
        self.config.volume_osd_duration = options.get("volume_osd_duration", data.get("volume_osd_duration", "2s"))
        self.config.enable_persistent_cache = bool(options.get(CONF_PERSISTENT_CACHE_ENABLED, data.get(CONF_PERSISTENT_CACHE_ENABLED, DEFAULT_PERSISTENT_CACHE_ENABLED)))
        self.config.max_cached_albums = int(options.get(CONF_MAX_CACHED_ALBUMS, data.get(CONF_MAX_CACHED_ALBUMS, DEFAULT_MAX_CACHED_ALBUMS)))
        self.config.first_day_of_week = str(options.get(CONF_FIRST_DAY_OF_WEEK, data.get(CONF_FIRST_DAY_OF_WEEK, DEFAULT_FIRST_DAY_OF_WEEK)))
        self.config.chart_slide_duration = int(options.get(CONF_CHART_SLIDE_DURATION, data.get(CONF_CHART_SLIDE_DURATION, DEFAULT_CHART_SLIDE_DURATION)))
        self.config.chart_size_limit = int(options.get(CONF_CHART_SIZE_LIMIT, data.get(CONF_CHART_SIZE_LIMIT, DEFAULT_CHART_SIZE_LIMIT)))
        self.config.chart_type = self.ui_state.get("chart_type", getattr(self.config, "chart_type", "Top Tracks"))
        self.config.chart_timeframe = self.ui_state.get("chart_timeframe", getattr(self.config, "chart_timeframe", "Weekly"))
        self.config.chart_period = self.ui_state.get("chart_period", getattr(self.config, "chart_period", "Current"))
        self.config.chart_direction = self.ui_state.get("chart_direction", getattr(self.config, "chart_direction", "Countdown (10 -> 1)"))

        self.config.full_control = self.ui_state.get("full_control", False)
        self.config.progress_bar_enabled = self.ui_state.get("progress_bar", True)
        self.config.text_bg = self.config.clock_bg = self.ui_state.get("text_background", True)
        self.config.artwork_race_mode = bool(self.ui_state.get("artwork_race_mode", options.get("artwork_race_mode", data.get("artwork_race_mode", False))))
        self.config.lyrics_sync = float(self.ui_state.get("lyrics_sync", 0.0))
        self.config.image_filter = self.ui_state.get("image_filter", getattr(self.config, "image_filter", "None"))
        self.config.playlist_prefetch_range = options.get(CONF_PLAYLIST_PREFETCH, data.get(CONF_PLAYLIST_PREFETCH, "Disabled"))
        self.config.light_entity = options.get(CONF_LIGHT_ENTITY, data.get(CONF_LIGHT_ENTITY, []))
        self.config.wled_ip = options.get(CONF_WLED_IP, data.get(CONF_WLED_IP, ""))
        self.config.only_at_night = options.get("only_at_night", data.get("only_at_night", True))

        crop_mode = self.ui_state.get("crop_mode", getattr(self.config, "crop_mode", "No Crop"))
        self.config.crop_mode, self.config.crop_borders, self.config.crop_extra = crop_mode, (crop_mode in ["Crop", "Extra Crop"]), (crop_mode == "Extra Crop")

        text_position = self.ui_state.get("text_position", "Bottom")
        self.config.show_text, top_text = (text_position != "Hidden"), (text_position == "Top")
        overlay_pos = self.ui_state.get("overlay_position", "Auto (Opposite of Text)")
        if overlay_pos == "Top":
            self.config.overlay_top, top_text = True, (False if (self.config.show_text and top_text) else top_text)
        elif overlay_pos == "Bottom":
            self.config.overlay_top, top_text = False, (True if (self.config.show_text and not top_text) else top_text)
        else:
            self.config.overlay_top = (not top_text) if self.config.show_text else True
        self.config.top_text = top_text

        overlay_info = str(self.ui_state.get("overlay_info", options.get("overlay_info", data.get("overlay_info", "Clock"))))
        self.config.show_clock, self.config.temperature = ("clock" in overlay_info.lower()), ("temp" in overlay_info.lower())
        self.config.overlay_align = self.ui_state.get("overlay_align", "Clock Right, Temp Left")

        display_mode = self.ui_state.get("display_mode", "Standard")
        if (display_mode == "Spotify Slider" and not self.is_spotify_available) or (display_mode == "Force AI" and not self.is_ai_available):
            display_mode = self.ui_state["display_mode"] = "Standard"

        m = display_mode.lower()
        self.config.show_lyrics, self.config.burned, self.config.special_mode = (m == "lyrics"), (m == "burned"), ("special" in m)
        self.config.vinyl_mode, self.config.cassette_mode, self.config.analog_clock = ("vinyl" in m), ("cassette" in m or "tape" in m), ("analog clock" in m)
        self.config.burned_text, self.config.clock_Analog = self.config.burned, self.config.analog_clock
        self.config.spotify_slide = ("slider" in m and "artist" not in m) and self.is_spotify_available
        self.config.artist_slide = "artist slide" in m or "artist gallery" in m
        self.config.force_ai = (display_mode == "Force AI" or bool(self.ui_state.get("force_ai", False))) and self.is_ai_available
        self.cached_static_items, self.last_text_payload_hash = [], None

    def _fetch_external_temperature(self) -> None:
        temp_ent = getattr(self.config, "temperature_sensor", None)
        if temp_ent:
            s = self.hass.states.get(temp_ent)
            if s and s.state not in ("unknown", "unavailable"):
                try:
                    self.media_data.temperature = f"{int(float(s.state))}{s.attributes.get('unit_of_measurement', '').lower()}"
                    return
                except Exception:
                    pass
        self.media_data.temperature = None

    def _is_player_active(self, state) -> bool:
        if not state:
            return False
        if state.state == "playing":
            return True
        if state.state == "on":
            title = state.attributes.get("media_title") or state.attributes.get("title")
            app, source = str(state.attributes.get("app_name") or "").lower(), str(state.attributes.get("source") or "").lower()
            return bool((title and str(title).strip()) or ("tv" in source or "tv" in app or "hdmi" in source))
        return False

    async def async_ui_update(self, key: str, value) -> None:
        self.ui_state[key] = value
        if key == "chart_timeframe":
            self.ui_state["chart_period"] = "Current"
            if self.select_entities.get("chart_period"):
                self.select_entities["chart_period"]._attr_current_option = "Current"
        self._apply_logic_matrix()
        self.cached_static_items, self.last_text_payload_hash, self.last_progress_str = [], None, ""

        if key in ("chart_type", "chart_timeframe", "chart_period", "chart_direction"):
            await self.chart_controller.async_refresh_periods_and_leaderboard()
            return
        if key == "master_control":
            if not value:
                self.hass.async_create_task(self._send_off_command())
            else:
                self._active_song_key = None
                self.hass.async_create_task(self.force_update())
            return
        if key == "pause_timeout":
            if self.osd_mode == "Pause":
                pause_setting = str(value)
                if pause_setting in ["Disabled (0s)", "0s", "Disabled"]:
                    self.hass.async_create_task(self._send_off_command(force_screen_off=True))
                elif pause_setting != "Never":
                    self._cleanup_timers(["_pause_timeout_unsub"])
                    import re
                    m = re.search(r"\d+", str(pause_setting))
                    delay_sec = int(m.group(0)) if m else 15
                    _LOGGER.info("Pixoo64 pause timeout changed via UI to %s seconds while paused", delay_sec)
                    self._pause_timeout_unsub = async_call_later(self.hass, delay_sec, self._execute_pause_timeout)
            return

        image_affecting_keys = {
            "display_mode", "crop_mode", "image_filter", "force_ai", "artwork_race_mode",
            "text_background", "text_position", "overlay_info", "overlay_position", "overlay_align",
        }
        if key not in image_affecting_keys:
            if key == "progress_bar" and hasattr(self, "media_data"):
                self.media_data.show_progress_bar = self.config.progress_bar_enabled and getattr(self.media_data, "media_duration", 0) > 0
            if self.is_art_visible and not getattr(self, "chart_active", False):
                if self.lyrics_active_mode:
                    self.hass.async_create_task(self._calculate_and_schedule_next())
                else:
                    self.request_text_render(force=True)
                if key == "progress_bar":
                    self.progress_timer_gen_id += 1
                    self.hass.async_create_task(self._update_progress_bar_loop())
            return

        self._early_slider_sent_for = self._prefetched_media = None
        self.image_processor.image_cache.clear()
        if hasattr(self, "media_data"):
            for attr in ("vinyl_frames_b64", "cassette_frames_b64", "slider_frames_b64", "slider_album_urls"):
                setattr(self.media_data, attr, [])
            self.media_data.slider_artist_pic_url = self.media_data.slider_error = None
            self.media_data.slider_frames = 0
            self.media_data.spotify_slide_pass = self.media_data.artist_slide_pass = False

        self._last_rendered_pic_url = self._last_rendered_album = self._last_rendered_artist = None
        self._last_rendered_mode = self._last_rendered_filter = self._last_rendered_crop = None
        self._cancel_tasks(["current_task", "_prefetch_task", "_playlist_prefetch_task", "_early_send_task"])
        self._active_song_key = None
        if not getattr(self, "chart_active", False):
            self.current_task = self.hass.async_create_task(self.force_update())
