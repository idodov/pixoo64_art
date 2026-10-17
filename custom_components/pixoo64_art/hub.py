"""The Core Hub managing UI states and delegating to pixoo_services."""
import asyncio
import logging
import time
import json
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict
from time import perf_counter
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_call_later

from .const import CONF_PIXOO_IP, CONF_MEDIA_PLAYER, CONF_PLAYLIST_PREFETCH, CONF_LIGHT_ENTITY, CONF_WLED_IP
from .pixoo_services import (
    AnalogClockRenderer, Config, PixooDevice, ImageProcessor, SpotifyService, FallbackService,
    LyricsProvider, MediaData, ProgressBarManager, NotificationManager,
    has_bidi, get_bidi, unidecode
)

_LOGGER = logging.getLogger(__name__)

# =========================================================================
# SONG PROFILER
# =========================================================================

class SongProfiler:
    def __init__(self, title: str = ""):
        self.title = title
        self.start = perf_counter()
        self.timings = {}
        self.counters = {}
        self.first_frame = None

    def add(self, key: str, duration: float):
        self.timings[key] = (
            self.timings.get(key, 0.0) + duration
        )

    def set(self, key: str, value):
        self.counters[key] = value

    def mark_first_frame(self):
        if self.first_frame is None:
            self.first_frame = perf_counter() - self.start

    def build_attributes(self):
        total = perf_counter() - self.start
        attrs = {
            "profile_song": self.title,
            "profile_total": round(total, 3),
            "profile_first_frame": (
                round(self.first_frame, 3)
                if self.first_frame is not None
                else None
            ),
        }
        for key, value in self.timings.items():
            attrs[f"profile_{key}"] = round(value, 3)
        for key, value in self.counters.items():
            attrs[f"profile_{key}"] = value
        return attrs

    def build_log_line(self):
        total = perf_counter() - self.start
        parts = [
            f"song='{self.title}'",
            f"total={total:.3f}s",
        ]
        if self.first_frame is not None:
            parts.append(
                f"first_frame={self.first_frame:.3f}s"
            )
        for key, value in sorted(
            self.timings.items()
        ):
            parts.append(
                f"{key}={value:.3f}s"
            )
        for key, value in sorted(
            self.counters.items()
        ):
            parts.append(
                f"{key}={value}"
            )
        return "[PROFILE] " + " ".join(parts)


# =========================================================================
# AMBIENT LIGHTING CONTROLLER
# =========================================================================

class AmbientLightingController:
    """Controls synchronized Home Assistant light entities and WLED LED strips."""

    def __init__(self, hass, websession, config: Config):
        self.hass = hass
        self.websession = websession
        self.config = config

    async def control_light(self, action: str, rgb_color: tuple = None, is_night: bool = True):
        if not is_night and getattr(self.config, 'only_at_night', False):
            _LOGGER.debug("Ambient light skipped: only_at_night is True and is_night is False")
            return
            
        light_entities = getattr(self.config, 'light_entity', [])
        if not light_entities:
            _LOGGER.debug("Ambient light skipped: no light entities configured")
            return
            
        entities = light_entities if isinstance(light_entities, list) else [light_entities]
        for entity_id in entities:
            service_data = {"entity_id": entity_id}
            if action == 'on' and rgb_color:
                r, g, b = int(rgb_color[0]), int(rgb_color[1]), int(rgb_color[2])
                if r == 0 and g == 0 and b == 0:
                    r, g, b = 255, 255, 255
                service_data["rgb_color"] = [r, g, b]
                service_data["transition"] = 1
                
            try:
                await self.hass.services.async_call("light", f"turn_{action}", service_data, blocking=False)
            except Exception as e:
                _LOGGER.error("Failed to control light %s: %s", entity_id, e)

    async def control_wled_light(self, action: str, colors: list = None, is_night: bool = True):
        if not is_night and getattr(self.config, 'only_at_night', False):
            return
            
        wled_ip = getattr(self.config, 'wled_ip', None)
        if not wled_ip:
            return
            
        payload = {"on": action == "on"}
        if action == "on" and colors:
            clean_colors = [c.lstrip('#') for c in colors if c]
            if clean_colors:
                effect_id = getattr(self.config, 'effect', 38)
                payload["bri"] = getattr(self.config, 'brightness', 255)
                payload["seg"] = [{"fx": effect_id, "col": clean_colors}]
                    
            url = f"http://{wled_ip}/json/state"
            try:
                async with self.websession.post(url, json=payload, timeout=5) as response:
                    response.raise_for_status()
            except Exception as e:
                _LOGGER.debug("Failed to control WLED at %s: %s", wled_ip, e)

# =========================================================================
# DISPLAY LAYER BUILDER (TEXT & OSD ITEMS)
# =========================================================================

class DisplayLayerBuilder:
    """Builds HTTP text item payloads including OSD, clock, weather, and track info."""

    @staticmethod
    def build_text_items(config: Config, media_data: MediaData, osd_mode: Optional[str], last_volume_level: float, font_color: str, bg_color: str, scope: str = "all") -> List[Dict]:
        text_items = []
        
        y_info = 3 if getattr(config, 'overlay_top', True) else 56
        align_mode = getattr(config, 'overlay_align', 'Clock Right, Temp Left')
        show_clk = getattr(config, 'show_clock', True)
        show_tmp = getattr(config, 'temperature', False)
        
        if align_mode == "Clock Left, Temp Right":
            x_c, x_t = 3, 47
        elif align_mode == "Centered":
            if show_clk and not show_tmp:
                x_c, x_t = 22, 3
            elif show_tmp and not show_clk:
                x_c, x_t = 44, 24
            else:
                x_c, x_t = 36, 3
        else: 
            x_c, x_t = 44, 3

        if osd_mode:
            if osd_mode == "Pause":
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 24, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": "PAUSED", "color": font_color})
            elif osd_mode == "Volume":
                pct = int((last_volume_level or 0) * 100)
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 20, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": f"VOL {pct}%", "color": font_color})
                bars = int((pct / 100) * 10)
                bar_str = "=" * bars + "-" * (10 - bars)
                text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 32, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": bar_str, "color": font_color})
                
            if show_clk:
                text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
            if show_tmp:
                t_val = getattr(media_data, 'temperature', None)
                t_type = 22 if t_val else 17
                t_str = str(t_val) if t_type == 22 else ""
                text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": t_str})
                
            return text_items

        if getattr(config, 'cassette_mode', False):
            cassette_y_info = 56
            if show_clk:
                text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": cassette_y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
            if show_tmp:
                t_val = getattr(media_data, 'temperature', None)
                t_type = 22 if t_val else 17
                t_str = str(t_val) if t_type == 22 else ""
                text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": cassette_y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": t_str})
            return text_items

        y_text = 0 if getattr(config, 'top_text', False) else 48
        
        d_artist = unidecode(media_data.artist) if media_data.artist else ""
        d_title = unidecode(media_data.title) if media_data.title else ""
        
        txt = f"{d_artist} - {d_title}"
        if len(txt) > 14:
            txt += "        "
        rtl = 1 if has_bidi(txt) else 0
        is_burned = getattr(config, 'burned', False)
        
        if getattr(config, 'special_mode', False):
            text_items.append({"TextId": 1, "type": 14, "x": 3, "y": 1, "dir": 0, "font": 18, "TextWidth": 33, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})
            text_items.append({"TextId": 2, "type": 5, "x": 1, "y": 1, "dir": 0, "font": 18, "TextWidth": 63, "Textheight": 6, "speed": 100, "align": 2, "color": font_color})
            
            t_val = getattr(media_data, 'temperature', None)
            t_type = 22 if t_val else 17
            t_str = str(t_val) if t_type == 22 else ""
            text_items.append({"TextId": 3, "type": t_type, "x": 48, "y": 1, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": t_str})

            show_http_text = getattr(config, 'show_text', True) and not getattr(media_data, 'playing_tv', False) and not is_burned
            
            if show_http_text:
                a_rtl = 1 if has_bidi(d_artist) else 0
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 42, "dir": a_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(d_artist) if a_rtl else d_artist, "color": font_color})
                t_rtl = 1 if has_bidi(d_title) else 0
                text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 52, "dir": t_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(d_title) if t_rtl else d_title, "color": font_color})

        else:
            if getattr(config, 'show_text', True) and not getattr(media_data, 'playing_tv', False) and not is_burned:
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": y_text, "dir": rtl, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(txt) if rtl else txt, "color": font_color})
                            
            if show_clk:
                text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
            
            if show_tmp:
                t_val = getattr(media_data, 'temperature', None)
                t_type = 22 if t_val else 17
                t_str = str(t_val) if t_type == 22 else ""
                text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": t_str})
                        
        return text_items

# =========================================================================
# CORE HUB
# =========================================================================
class PixooHub:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.pixoo_ip = entry.data[CONF_PIXOO_IP]
        self.media_player = entry.data[CONF_MEDIA_PLAYER]
        self._current_live_gif_url = None
        
        self.ui_state = {}
        self.config = Config(entry)
        self.sensor = None
        self._unsub_listeners = []
        self._image_lock = asyncio.Lock()
        self._active_song_key = None 
        self._prefetched_media = None
        
        
        self.select_index = 0
        self.last_valid_index = 0
        self.device_brightness = 100
        self.device_screen_on = True

        self.ai_generating = False
        self.ai_status = "Idle"

        self.websession = async_get_clientsession(hass)
        self.pixoo_device = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.hass, self.config, self.websession)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.media_data = MediaData(self.hass, self.config, self.image_processor, self.websession)
        self.fallback_service = FallbackService(self.config, self.image_processor, self.websession, self.spotify_service, self.pixoo_device, hub=self)
        self.progress_manager = ProgressBarManager(self.config, self.hass)
        self.notification_manager = NotificationManager(self.config, self.pixoo_device, self.image_processor, self.hass)

        self.lighting = AmbientLightingController(self.hass, self.websession, self.config)
        self.layer_builder = DisplayLayerBuilder()

        self.is_art_visible = False
        self.lyrics_active_mode = False
        self.last_text_payload_hash = None
        self.cached_static_items = []
        self.current_lyrics_items = []
        self.progress_timer_gen_id = 0
        self.scheduler_generation_id = 0
        self.last_progress_str = ""
        self.clock_timer_gen_id = 0
        self._current_clock_pil_img = None
        self._current_clock_song_key = None
        
        self.osd_mode = None
        self.last_volume_level = 0.0
        
        self.current_task = None
        self.debounce_task = None
        self._prefetch_task = None
        self._playlist_prefetch_task = None
        self._early_send_task = None
        self._progress_timer_unsub = None
        self._clock_timer_unsub = None
        self._lyrics_timer_unsub = None
        self._pending_render_unsub = None
        self._prefetch_timer_unsub = None
        self._early_send_timer_unsub = None
        self._pause_timeout_unsub = None
        self._volume_osd_timer_unsub = None
        self._force_next_text_render = False
        self._is_processing_image = False 
        
        self._early_slider_sent_for = None
        self.prefetch_status = "Idle"
        self.prefetch_next_artist = None
        self.prefetch_next_title = None

        self.spotify_slider_status = "Idle"
        self.spotify_slider_frames = 0
        self.spotify_slider_artist = None
        self.spotify_slider_last_error = None

        self.playlist_prefetch_status = "Idle"
        self.playlist_queue_total = 0
        self.playlist_queue_position = None
        self.playlist_cached_count = 0
        self.playlist_window_range = "None"
        
        self.profile_data = {}

    @property
    def extra_state_attributes(self):
        attrs = dict(self.ui_state)
        attrs["media_player"] = self.media_player
        attrs["pixoo64_channel"] = self.last_valid_index
        attrs["brightness"] = self.device_brightness
        attrs["screen_power"] = "On" if self.device_screen_on else "Off"
        attrs["ai_generating"] = getattr(self, "ai_generating", False)
        attrs["ai_status"] = getattr(self, "ai_status", "Idle")
        if self._current_live_gif_url:
            attrs["live_display_url"] = self._current_live_gif_url
        if self.profile_data:
            attrs.update(self.profile_data)
        return attrs

    def update_channel_sensor_attribute(self, channel_idx: int):
        try:
            ch = int(channel_idx)
            if 0 <= ch <= 3:
                self.last_valid_index = ch
                self.select_index = ch
                self.is_art_visible = False
        except (ValueError, TypeError):
            pass
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["pixoo64_channel"] = self.last_valid_index
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    def update_brightness_sensor_attribute(self, brightness: int):
        try:
            b_val = max(0, min(100, int(brightness)))
            self.device_brightness = b_val
        except (ValueError, TypeError):
            pass
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["brightness"] = self.device_brightness
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    def update_power_sensor_attribute(self, is_on: bool):
        self.device_screen_on = bool(is_on)
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["screen_power"] = "On" if self.device_screen_on else "Off"
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    def set_ai_generating(self, is_generating: bool, status: str = "Idle"):
        """Updates AI generation state and pushes telemetry immediately to sensor attributes."""
        self.ai_generating = is_generating
        self.ai_status = status
        if self.sensor:
            attrs = dict(self.sensor._attr_extra_state_attributes or {})
            attrs["ai_generating"] = self.ai_generating
            attrs["ai_status"] = self.ai_status
            if is_generating and (getattr(self.config, 'force_ai', False) or self.ui_state.get("display_mode") == "Force AI"):
                attrs["active_mode"] = "Force AI"
                attrs["configured_mode"] = "Force AI"
            self.sensor.update_state(self.sensor._attr_native_value, attrs)

    async def _sync_hardware_state_from_device(self, allow_channel_update: bool = True):
        """Polls the Pixoo device for brightness, power, and channel (ignoring channel 4)."""
        try:
            conf = await self.pixoo_device.get_all_conf()
            if conf:
                if "LightSwitch" in conf:
                    self.device_screen_on = (conf.get("LightSwitch", 1) == 1)
                    if not self.device_screen_on:
                        self.is_art_visible = False

                if "Brightness" in conf:
                    try:
                        self.device_brightness = int(conf["Brightness"])
                    except (ValueError, TypeError):
                        pass

            if allow_channel_update:
                curr_ch = await self.pixoo_device.get_current_channel_index()
                if curr_ch is not None and 0 <= curr_ch <= 3:
                    self.last_valid_index = curr_ch
                    self.select_index = curr_ch
                    self.is_art_visible = False
                elif curr_ch == 4 and self.device_screen_on:
                    pass
                else:
                    self.is_art_visible = False

            if self.sensor:
                attrs = dict(self.sensor._attr_extra_state_attributes or {})
                attrs["pixoo64_channel"] = self.last_valid_index
                attrs["brightness"] = self.device_brightness
                attrs["screen_power"] = "On" if self.device_screen_on else "Off"
                self.sensor.update_state(self.sensor._attr_native_value, attrs)
        except Exception as e:
            _LOGGER.debug("Hardware state sync error: %s", e)

    async def control_light(self, action: str, rgb_color: tuple = None, is_night: bool = True):
        await self.lighting.control_light(action, rgb_color, is_night)

    async def control_wled_light(self, action: str, colors: list = None, is_night: bool = True):
        await self.lighting.control_wled_light(action, colors, is_night)

    async def _build_text_items_list(self, font_color, bg_color, scope="all"):
        return self.layer_builder.build_text_items(
            self.config, self.media_data, self.osd_mode, 
            self.last_volume_level, font_color, bg_color, scope=scope
        )

    def _cleanup_timers(self, timers=None):
        default_timers = [
            '_progress_timer_unsub', '_lyrics_timer_unsub', 
            '_pending_render_unsub', '_prefetch_timer_unsub', 
            '_early_send_timer_unsub', '_pause_timeout_unsub',
            '_volume_osd_timer_unsub', '_clock_timer_unsub'
        ]
        for attr in (timers or default_timers):
            unsub = getattr(self, attr, None)
            if unsub:
                unsub()
                setattr(self, attr, None)

    def _cancel_tasks(self, tasks=None):
        default_tasks = ['current_task', 'debounce_task', '_prefetch_task', '_playlist_prefetch_task', '_early_send_task']
        for attr in (tasks or default_tasks):
            task = getattr(self, attr, None)
            if task and not task.done():
                task.cancel()
            setattr(self, attr, None)

    def set_sensor(self, sensor):
        self.sensor = sensor

    def _get_current_media_position(self) -> float:
        pos = getattr(self.media_data, 'media_position', 0.0) or 0.0
        updated_at = getattr(self.media_data, 'media_position_updated_at', None)
        if updated_at:
            try:
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                pos += (datetime.now(timezone.utc) - updated_at).total_seconds()
            except Exception:
                pass
        return pos

    def _update_prefetch_sensor_state(self):
        if not self.sensor:
            return
        old_attrs = dict(self.sensor._attr_extra_state_attributes) if self.sensor._attr_extra_state_attributes else {}
        attrs = dict(old_attrs)
        attrs["prefetch_status"] = self.prefetch_status
        attrs["prefetch_next_artist"] = self.prefetch_next_artist
        attrs["prefetch_next_title"] = self.prefetch_next_title
        attrs["slider_status"] = self.spotify_slider_status
        attrs["slider_frames"] = self.spotify_slider_frames
        attrs["slider_artist"] = self.spotify_slider_artist
        attrs["spotify_slider_last_error"] = self.spotify_slider_last_error
        attrs["general_cache_size"] = len(self.image_processor.image_cache)
        attrs["general_cache_limit"] = self.image_processor.cache_size
        attrs["playlist_prefetch_setting"] = getattr(self.config, 'playlist_prefetch_range', 'Disabled')
        attrs["playlist_prefetch_status"] = self.playlist_prefetch_status
        attrs["playlist_queue_total"] = self.playlist_queue_total
        attrs["playlist_queue_position"] = self.playlist_queue_position
        attrs["playlist_cached_count"] = self.playlist_cached_count
        attrs["playlist_window_range"] = self.playlist_window_range
        attrs["pixoo64_channel"] = self.last_valid_index
        attrs["brightness"] = self.device_brightness
        attrs["screen_power"] = "On" if self.device_screen_on else "Off"

        if self._current_live_gif_url:
            attrs["live_display_url"] = self._current_live_gif_url

        if attrs == old_attrs:
            return
        
        state_val = getattr(self.sensor, '_attr_native_value', "Initializing")
        self.sensor.update_state(state_val, attrs)

    async def initialize(self):
        await self._sync_hardware_state_from_device(allow_channel_update=True)
        await asyncio.sleep(0.5)
        self._apply_logic_matrix()

        self._unsub_listeners.append(
            async_track_state_change_event(self.hass, [self.media_player], self.safe_state_change_callback)
        )
        
        async def _delayed_startup():
            await asyncio.sleep(4.0)
            state = self.hass.states.get(self.media_player)
            if state and self._is_player_active(state):
                self._active_song_key = None
                await self.force_update()

        self.hass.async_create_task(_delayed_startup())

    async def terminate(self):
        for unsub in self._unsub_listeners:
            unsub()
        self._cleanup_timers()
        self._cancel_tasks()
        self.image_processor.shutdown()

    async def async_ui_update(self, key: str, value):
        self.ui_state[key] = value
        self._apply_logic_matrix()
        
        self.cached_static_items = []
        self.last_text_payload_hash = None
        self.last_progress_str = ""

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
                    self.hass.async_create_task(self._send_off_command())
                elif pause_setting != "Never":
                    timeout_val = int(pause_setting.replace("s", "").split()[0])
                    self._cleanup_timers(['_pause_timeout_unsub'])
                    self._pause_timeout_unsub = async_call_later(self.hass, timeout_val, self._execute_pause_timeout)
            return

        image_affecting_keys = {
            "display_mode", "crop_mode", "image_filter", 
            "force_ai", "text_background", "text_position",
            "overlay_info", "overlay_position", "overlay_align"
        }

        if key not in image_affecting_keys:
            if self.is_art_visible:
                if self.lyrics_active_mode:
                    self.hass.async_create_task(self._calculate_and_schedule_next())
                else:
                    self.request_text_render(force=True)

                if key == "progress_bar":
                    self.progress_timer_gen_id += 1
                    self.hass.async_create_task(self._update_progress_bar_loop())
            return

        self._early_slider_sent_for = None
        self._prefetched_media = None
        self.image_processor.image_cache.clear()
        
        if hasattr(self, 'media_data'):
            self.media_data.vinyl_frames_b64 = []
            self.media_data.cassette_frames_b64 = []
            self.media_data.slider_frames_b64 = []
            self.media_data.slider_album_urls = []
            self.media_data.slider_artist_pic_url = None
            self.media_data.slider_frames = 0
            self.media_data.spotify_slide_pass = False
            self.media_data.artist_slide_pass = False
            self.media_data.slider_error = None
            
        self._last_rendered_pic_url = None
        self._last_rendered_album = None
        self._last_rendered_artist = None
        self._last_rendered_mode = None
        
        self._cancel_tasks(['current_task', '_prefetch_task', '_early_send_task'])
        self._active_song_key = None 
        self.current_task = self.hass.async_create_task(self.force_update())

    async def _send_off_command(self):
        await self._sync_hardware_state_from_device(allow_channel_update=True)

        self.is_art_visible = False
        self._active_song_key = None
        self.osd_mode = None
        self.ai_generating = False
        self.ai_status = "Idle"
        
        self.prefetch_status = "Idle"
        self.prefetch_next_artist = None
        self.prefetch_next_title = None
        self._early_slider_sent_for = None
        self._prefetched_media = None
        self.spotify_slider_status = "Idle"
        self.spotify_slider_frames = 0
        self.spotify_slider_artist = None
        self.spotify_slider_last_error = None
        self.playlist_prefetch_status = "Idle"

        self._last_rendered_pic_url = None
        self._last_rendered_album = None
        self._last_rendered_artist = None
        self._current_live_gif_url = None
        
        self._stop_clock_scheduler()
        self._cleanup_timers(['_prefetch_timer_unsub', '_early_send_timer_unsub', '_pause_timeout_unsub', '_volume_osd_timer_unsub'])
        self._cancel_tasks(['_prefetch_task', '_playlist_prefetch_task', '_early_send_task'])
        
        await self.control_light('off')
        await self.control_wled_light('off')
        
        target_channel = getattr(self, 'last_valid_index', 0)
        if target_channel == 4 or target_channel < 0:
            target_channel = 0

        if getattr(self.config, 'full_control', False):
            self.device_screen_on = False
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},  
                    {"Command": "Draw/ResetHttpGifId"},
                    {"Command": "Channel/OnOffScreen", "OnOff": 0}
                ]
            })
        else:
            self.device_screen_on = True
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},  
                    {"Command": "Draw/ResetHttpGifId"},
                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                    {"Command": "Channel/SetIndex", "SelectIndex": target_channel}
                ]
            })

        if self.sensor:
            self.sensor.update_state("Off", {
                "media_player": self.media_player,
                "pixoo64_channel": target_channel,
                "brightness": self.device_brightness,
                "screen_power": "On" if self.device_screen_on else "Off",
                "active_mode": "Channel",
                "ai_generating": False,
                "ai_status": "Idle"
            })

    @property
    def is_ai_available(self) -> bool:
        options = self.entry.options
        data = self.entry.data
        key = options.get("pollinations_key") or data.get("pollinations_key") or getattr(self.config, "pollinations", "")
        return bool(key and isinstance(key, str) and len(str(key).strip()) > 5)

    @property
    def is_spotify_available(self) -> bool:
        options = self.entry.options
        data = self.entry.data
        cid = options.get("spotify_client_id") or data.get("spotify_client_id") or getattr(self.config, "spotify_client_id", "")
        csec = options.get("spotify_client_secret") or data.get("spotify_client_secret") or getattr(self.config, "spotify_client_secret", "")
        return bool(str(cid).strip() and str(csec).strip() and len(str(cid).strip()) > 5 and len(str(csec).strip()) > 5)

    def _apply_logic_matrix(self):
        options = self.entry.options
        data = self.entry.data

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
        self.config.lastfm = options.get("lastfm_key", data.get("lastfm_key", ""))
        self.config.discogs = options.get("discogs_token", data.get("discogs_token", ""))

        self.config.tv_mode = options.get("tv_mode", data.get("tv_mode", False))
        self.config.temperature_sensor = options.get("temperature_entity", data.get("temperature_entity"))
        
        self.config.osd_overlay = options.get("osd_overlay", data.get("osd_overlay", "Enabled"))
        self.config.pause_timeout = options.get("pause_timeout", data.get("pause_timeout", "15s"))
        self.config.volume_osd_duration = options.get("volume_osd_duration", data.get("volume_osd_duration", "2s"))
        
        self.config.full_control = self.ui_state.get("full_control", False)
        self.config.progress_bar_enabled = self.ui_state.get("progress_bar", True)
        self.config.text_bg = self.ui_state.get("text_background", True)

        self.config.lyrics_sync = float(self.ui_state.get("lyrics_sync", 0.0))
        self.config.image_filter = self.ui_state.get("image_filter", "None")
        
        self.config.playlist_prefetch_range = options.get(CONF_PLAYLIST_PREFETCH, data.get(CONF_PLAYLIST_PREFETCH, "Disabled"))

        self.config.light_entity = options.get(CONF_LIGHT_ENTITY, data.get(CONF_LIGHT_ENTITY, []))
        self.config.wled_ip = options.get(CONF_WLED_IP, data.get(CONF_WLED_IP, ""))
        self.config.only_at_night = options.get("only_at_night", data.get("only_at_night", True))

        crop_mode = self.ui_state.get("crop_mode", "No Crop")
        self.config.crop_mode = crop_mode
        self.config.crop_borders = crop_mode in ["Crop", "Extra Crop"]
        self.config.crop_extra = (crop_mode == "Extra Crop")

        text_position = self.ui_state.get("text_position", "Bottom")
        self.config.show_text = (text_position != "Hidden")
        top_text = (text_position == "Top")

        overlay_pos = self.ui_state.get("overlay_position", "Auto (Opposite of Text)")
        if overlay_pos == "Top":
            self.config.overlay_top = True
            if self.config.show_text and top_text:
                top_text = False
        elif overlay_pos == "Bottom":
            self.config.overlay_top = False
            if self.config.show_text and not top_text:
                top_text = True
        else:
            if self.config.show_text:
                self.config.overlay_top = not top_text
            else:
                self.config.overlay_top = True

        self.config.top_text = top_text

        overlay_info = self.ui_state.get("overlay_info", "Clock")
        self.config.show_clock = "Clock" in overlay_info
        self.config.temperature = "Temp" in overlay_info
        self.config.overlay_align = self.ui_state.get("overlay_align", "Clock Right, Temp Left")

        display_mode = self.ui_state.get("display_mode", "Standard")
        if display_mode == "Spotify Slider" and not self.is_spotify_available:
            display_mode = "Standard"
            self.ui_state["display_mode"] = "Standard"
        elif display_mode == "Force AI" and not self.is_ai_available:
            display_mode = "Standard"
            self.ui_state["display_mode"] = "Standard"

        m = display_mode.lower()
        self.config.show_lyrics = (m == "lyrics")
        self.config.burned = (m == "burned")
        self.config.special_mode = ("special" in m)
        self.config.vinyl_mode = ("vinyl" in m)
        self.config.cassette_mode = ("cassette" in m or "tape" in m)
        self.config.analog_clock = ("analog clock" in m)
        
        self.config.spotify_slide = ("slider" in m and "artist" not in m) and self.is_spotify_available
        self.config.artist_slide = ("artist slide" in m or "artist gallery" in m)
        self.config.force_ai = (display_mode == "Force AI" or bool(self.ui_state.get("force_ai", False))) and self.is_ai_available

        self.cached_static_items = []
        self.last_text_payload_hash = None

    def _fetch_external_temperature(self):
        temp_ent = getattr(self.config, 'temperature_sensor', None)
        if temp_ent:
            s = self.hass.states.get(temp_ent)
            if s and s.state not in ("unknown", "unavailable"):
                try:
                    val = float(s.state)
                    unit = s.attributes.get('unit_of_measurement', '')
                    self.media_data.temperature = f"{int(val)}{unit.lower()}"
                except Exception:
                    self.media_data.temperature = None
            else:
                self.media_data.temperature = None
        else:
            self.media_data.temperature = None

    def request_text_render(self, force: bool = False):
        if self.notification_manager.is_active:
            return
        if force:
            self._force_next_text_render = True
        self._cleanup_timers(['_pending_render_unsub'])
        self._pending_render_unsub = async_call_later(self.hass, 0.2, self._execute_text_render)

    async def _execute_text_render(self, now=None):
        self._pending_render_unsub = None
        if self.notification_manager.is_active:
            return
        force = getattr(self, '_force_next_text_render', False)
        self._force_next_text_render = False
        await self._render_and_send_text_layers(force=force)

    async def _render_and_send_text_layers(self, force: bool = False):
        if not self.is_art_visible or self.notification_manager.is_active or getattr(self, '_is_processing_image', False):
            return
        items = []
        font_color = getattr(self.media_data, 'lyrics_font_color', "#FFFFFF")
        bg_color = getattr(self.media_data, 'background_color', "#000000")
        
        if self.osd_mode:
            items.extend(await self._build_text_items_list(font_color, bg_color, scope="static"))
        elif self.lyrics_active_mode and self.current_lyrics_items:
            items.extend(self.current_lyrics_items)
        else:
            if not self.cached_static_items:
                self.cached_static_items = await self._build_text_items_list(font_color, bg_color, scope="static")
            items.extend(self.cached_static_items)
            
        if getattr(self.media_data, 'show_progress_bar', False) and not self.osd_mode:
            pos = self._get_current_media_position()
            bar_str, _ = self.progress_manager.calculate(pos, getattr(self.media_data, 'media_duration', 0.0))
            self.last_progress_str = bar_str
            
            pb = await self.progress_manager.get_payload_item(self.media_data)
            if pb:
                items.extend(pb)
            
        used_ids = {item.get("TextId") for item in items if "TextId" in item}
        for i in range(1, 22):
            if i not in used_ids:
                items.append({
                    "TextId": i, "type": 22, "x": 0, "y": 64, "dir": 0, "font": 2, 
                    "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 1, 
                    "TextString": "", "color": "#000000"
                })

        hsh = hash(json.dumps(items, sort_keys=True))
        if force or hsh != self.last_text_payload_hash:
            await self.pixoo_device.send_command({"Command": "Draw/SendHttpItemList", "ItemList": items})
            self.last_text_payload_hash = hsh

    async def _calculate_and_schedule_next(self):
        if self.notification_manager.is_active or not self.lyrics_active_mode:
            return
        self.scheduler_generation_id += 1
        gen_id = self.scheduler_generation_id
        
        pos = self._get_current_media_position()
        pos -= getattr(self.config, 'lyrics_sync', 0.0)
        
        layout, delay = self.media_data.lyrics_provider.get_refresh_plan(pos)

        self.current_lyrics_items = []
        font_id = getattr(self.config, 'lyrics_font', 2)
        
        for i in range(6):
            if layout and i < len(layout):
                it = layout[i]
                h = 16
                self.current_lyrics_items.append({
                    "TextId": i+10, "type": 22, "x": 0, "y": int(it['y']), 
                    "dir": int(it['dir']), "font": font_id, "TextWidth": 64, 
                    "Textheight": int(h), "speed": 0, "align": 2, 
                    "TextString": it['text'], 
                    "color": getattr(self.media_data, 'lyrics_font_color', "#FFFFFF")
                })
            else:
                self.current_lyrics_items.append({
                    "TextId": i+10, "type": 22, "x": 0, "y": 0, 
                    "dir": 0, "font": font_id, "TextWidth": 64, 
                    "Textheight": 12, "speed": 0, "align": 2, 
                    "TextString": "", "color": "#000000"
                })
                
        for i in range(1, 7):
            self.current_lyrics_items.append({
                "TextId": i, "type": 22, "x": 0, "y": 64, 
                "dir": 0, "font": 2, "TextWidth": 64, 
                "Textheight": 12, "speed": 0, "align": 1, 
                "TextString": "", "color": "#000000"
            })
            
        self.request_text_render()
        safe_delay = delay if delay is not None else 5.0
        
        async def _timer(now):
            if self.scheduler_generation_id == gen_id: 
                await self._calculate_and_schedule_next()
        
        self._cleanup_timers(['_lyrics_timer_unsub'])
        self._lyrics_timer_unsub = async_call_later(self.hass, safe_delay, _timer)

    def _schedule_prefetch(self):
        self._cleanup_timers(['_prefetch_timer_unsub'])
        if not self.media_data or getattr(self.media_data, 'media_duration', 0) <= 0:
            return

        is_force_ai = getattr(self.config, 'force_ai', False)
        is_anim_mode = (
            getattr(self.config, 'spotify_slide', False) or 
            getattr(self.config, 'artist_slide', False) or 
            getattr(self.config, 'vinyl_mode', False) or 
            getattr(self.config, 'cassette_mode', False) or
            is_force_ai
        )

        pos = self._get_current_media_position()
        dur = float(self.media_data.media_duration)
        
        # 25s buffer for heavy animations, exactly 10s for standard/lyrics
        prefetch_offset = 25.0 if is_anim_mode else 10.0
        delay = (dur - pos) - prefetch_offset

        if delay > 0:
            self._prefetch_timer_unsub = async_call_later(self.hass, delay, self._execute_prefetch)
        elif delay > -prefetch_offset:
            self.hass.async_create_task(self._execute_prefetch_task())

    async def _execute_prefetch(self, now=None):
        self._prefetch_timer_unsub = None
        await self._execute_prefetch_task()

    async def _execute_prefetch_task(self):
        try:
            self.prefetch_status = "Querying Next Song..."
            self._update_prefetch_sensor_state()
            
            next_info = await self._get_next_song_info()
            if next_info:
                artist, title_clean, album, url, title_original, duration = next_info
                
                if artist and title_clean:
                    self.prefetch_next_artist = artist
                    self.prefetch_next_title = title_clean
                    
                    if getattr(self.config, 'show_lyrics', False):
                        self.prefetch_status = "Downloading Art & Lyrics..."
                        self.hass.async_create_task(
                            self.media_data.lyrics_provider.prefetch_lyrics(artist, title_original, duration)
                        )
                    else:
                        self.prefetch_status = "Downloading Art..."
                    
                    if getattr(self.config, 'spotify_slide', False) or getattr(self.config, 'artist_slide', False):
                        self.spotify_slider_status = f"Prefetching for {artist}..."
                        self.spotify_slider_artist = artist
                        
                    self._update_prefetch_sensor_state()
                    
                    dummy_media = MediaData(self.hass, self.config, self.image_processor, self.websession)
                    dummy_media.artist = artist
                    dummy_media.title = title_clean
                    dummy_media.title_original = title_original
                    dummy_media.album = album
                    dummy_media.picture = url
                    dummy_media.queue_total = getattr(self.media_data, 'queue_total', 0)
                    dummy_media.track_number = getattr(self.media_data, 'track_number', 1) + 1
                    dummy_media.playing_tv = False
                    dummy_media.playing_radio = False
                    dummy_media.radio_logo = False
                    
                    self._cancel_tasks(['_prefetch_task'])
                    self._prefetch_task = self.hass.async_create_task(
                        self._run_prefetch_and_update_status(url, dummy_media)
                    )
            else:
                self.prefetch_status = "No next song detected"
                self.prefetch_next_artist = None
                self.prefetch_next_title = None
                if (getattr(self.config, 'spotify_slide', False) or getattr(self.config, 'artist_slide', False)) and self.spotify_slider_status not in ["Active Live", "Slider Sent Early"]:
                    self.spotify_slider_status = "No next queue detected"
                self._update_prefetch_sensor_state()
        except Exception as e:
            _LOGGER.debug("Error in prefetch task: %s", e)
            self.prefetch_status = f"Prefetch error: {e}"
            self._update_prefetch_sensor_state()

    async def _run_prefetch_and_update_status(self, url: str, dummy_media: MediaData):
        try:
            dummy_media.is_prefetch = True
            proc_img = await self.fallback_service.get_final_url(url, dummy_media)
            if not proc_img:
                proc_img = self.fallback_service._get_fallback_black_image_data()
            dummy_media.processed_data = proc_img
            self.prefetch_status = "Ready in RAM"
            
            is_slider = getattr(self.config, 'spotify_slide', False)
            is_artist_slider = getattr(self.config, 'artist_slide', False)
            is_vinyl = getattr(self.config, 'vinyl_mode', False)
            is_cassette = getattr(self.config, 'cassette_mode', False)
            
            if is_slider and not getattr(dummy_media, 'radio_logo', False):
                await self.spotify_service.prepare_slider_for_media(dummy_media)
                if getattr(self.config, 'special_mode_spotify_slider', False):
                    await self.spotify_service.spotify_album_art_animation(None, dummy_media, self.select_index)
                else:
                    await self.spotify_service.spotify_albums_slide(None, dummy_media, self.select_index, send_to_device=False)
                frames = getattr(dummy_media, 'slider_frames', 0)
                self.spotify_slider_frames = frames
                if frames >= 2:
                    self.spotify_slider_status = f"Ready in RAM ({frames} frames)"
                    self.prefetch_status = f"Slider Ready ({frames} frames)"
                else:
                    self.spotify_slider_status = f"Prefetch: {dummy_media.slider_error or 'No albums found'}"
            
            elif is_artist_slider and not getattr(dummy_media, 'radio_logo', False):
                await self.fallback_service.play_artist_gallery_slide(None, dummy_media, send_to_device=False)
                frames = getattr(dummy_media, 'slider_frames', 0)
                self.spotify_slider_frames = frames
                if frames >= 2:
                    self.spotify_slider_status = f"Ready in RAM ({frames} artist frames)"
                    self.prefetch_status = f"Gallery Ready ({frames} frames)"
                else:
                    self.spotify_slider_status = f"Prefetch: {dummy_media.slider_error or 'No artist images found'}"
            
            elif is_vinyl and not getattr(dummy_media, 'radio_logo', False):
                if proc_img and 'pil_image' in proc_img:
                    dummy_media.vinyl_frames_b64 = await self.hass.async_add_executor_job(
                        self.image_processor.generate_vinyl_frames, proc_img['pil_image'], dummy_media
                    )
                if dummy_media.vinyl_frames_b64:
                    self.prefetch_status = f"Vinyl Ready ({len(dummy_media.vinyl_frames_b64)} frames)"

            elif is_cassette and not getattr(dummy_media, 'radio_logo', False):
                if proc_img and 'pil_image' in proc_img:
                    dummy_media.cassette_frames_b64 = await self.hass.async_add_executor_job(
                        self.image_processor.generate_cassette_frames, proc_img['pil_image'], dummy_media
                    )
                if dummy_media.cassette_frames_b64:
                    self.prefetch_status = f"Cassette Ready ({len(dummy_media.cassette_frames_b64)} frames)"

            self._prefetched_media = dummy_media
            self._update_prefetch_sensor_state()
            
            if (is_slider or is_artist_slider or is_vinyl or is_cassette) and not getattr(dummy_media, 'radio_logo', False):
                has_frames = (
                    (len(getattr(dummy_media, 'slider_frames_b64', [])) >= 2) if (is_slider or is_artist_slider) else 
                    bool(dummy_media.vinyl_frames_b64) if is_vinyl else 
                    bool(dummy_media.cassette_frames_b64)
                )
                if has_frames:
                    pos = self._get_current_media_position()
                    dur = float(self.media_data.media_duration)
                    
                    if is_vinyl:
                        early_offset = 10
                    elif is_cassette:
                        early_offset = 3
                    else:
                        early_offset = 5
                        
                    time_to_early_send = (dur - pos) - early_offset
                    
                    if time_to_early_send > 0:
                        self._cleanup_timers(['_early_send_timer_unsub'])
                        async def _early_send_cb(now):
                            self._early_send_timer_unsub = None
                            self._cancel_tasks(['_early_send_task'])
                            if getattr(self.config, 'spotify_slide', False) or getattr(self.config, 'artist_slide', False):
                                self._early_send_task = self.hass.async_create_task(self._do_early_slider_send(dummy_media))
                            elif getattr(self.config, 'vinyl_mode', False):
                                self._early_send_task = self.hass.async_create_task(self._do_early_vinyl_send(dummy_media))
                            elif getattr(self.config, 'cassette_mode', False):
                                self._early_send_task = self.hass.async_create_task(self._do_early_cassette_send(dummy_media))
                        self._early_send_timer_unsub = async_call_later(self.hass, time_to_early_send, _early_send_cb)
                    elif time_to_early_send > -early_offset:
                        self._cancel_tasks(['_early_send_task'])
                        if is_slider or is_artist_slider:
                            self._early_send_task = self.hass.async_create_task(self._do_early_slider_send(dummy_media))
                        elif is_vinyl:
                            self._early_send_task = self.hass.async_create_task(self._do_early_vinyl_send(dummy_media))
                        elif is_cassette:
                            self._early_send_task = self.hass.async_create_task(self._do_early_cassette_send(dummy_media))
                            
        except asyncio.CancelledError:
            self.prefetch_status = "Cancelled"
            self.spotify_slider_status = "Prefetch Cancelled"
            self._update_prefetch_sensor_state()
        except Exception as e:
            self.prefetch_status = f"Failed: {e}"
            self.spotify_slider_status = f"Prefetch Error: {e}"
            self.spotify_slider_last_error = str(e)
            self._update_prefetch_sensor_state()

    async def _do_early_slider_send(self, dummy_media: MediaData):
        if not dummy_media:
            return
            
        self._is_processing_image = True
        self.prefetch_status = "Sending Slider Early..."
        self.spotify_slider_status = "Sending Early Slider to Pixoo..."
        self._update_prefetch_sensor_state()
        self._early_slider_sent_for = f"slider_{dummy_media.artist}_{dummy_media.title}".strip().lower()
        
        try:
            if getattr(self.config, 'artist_slide', False):
                await self.fallback_service.play_artist_gallery_slide(self.pixoo_device, dummy_media, send_to_device=True)
                pass_flag = getattr(dummy_media, 'artist_slide_pass', False)
            else:
                if getattr(self.config, 'special_mode_spotify_slider', False): 
                    await self.spotify_service.spotify_album_art_animation(self.pixoo_device, dummy_media, self.select_index)
                else: 
                    await self.spotify_service.spotify_albums_slide(self.pixoo_device, dummy_media, self.select_index, send_to_device=True)
                pass_flag = getattr(dummy_media, 'spotify_slide_pass', False)
                
            if pass_flag:
                self.prefetch_status = "Slider Sent Early"
                self.spotify_slider_status = f"Slider Sent Early ({dummy_media.slider_frames} frames)"
                self.spotify_slider_frames = dummy_media.slider_frames
                self.spotify_slider_artist = dummy_media.artist
            else:
                self.prefetch_status = "Early Slider Failed"
                self.spotify_slider_status = f"Early Slider Failed: {dummy_media.slider_error or 'Unknown'}"
                self.spotify_slider_last_error = dummy_media.slider_error
        except Exception as e:
            self.prefetch_status = f"Early Slider Error: {e}"
            self.spotify_slider_status = f"Early Slider Exception: {e}"
            self.spotify_slider_last_error = str(e)
        finally:
            self._is_processing_image = False
            self._update_prefetch_sensor_state()

    async def _do_early_vinyl_send(self, dummy_media: MediaData):
        if not dummy_media or not dummy_media.vinyl_frames_b64:
            return
            
        self._is_processing_image = True
        self.prefetch_status = "Sending Early Vinyl..."
        self._update_prefetch_sensor_state()
        
        self._early_slider_sent_for = f"vinyl_{dummy_media.artist}_{dummy_media.title}".strip().lower()
        
        try:
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Channel/SetIndex", "SelectIndex": 4},
                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                    {"Command": "Draw/ResetHttpGifId"}
                ]
            })
            for offset, b64_frame in enumerate(dummy_media.vinyl_frames_b64):
                await self.pixoo_device.send_command({
                    "Command": "Draw/SendHttpGif",
                    "PicNum": len(dummy_media.vinyl_frames_b64),
                    "PicWidth": 64,
                    "PicOffset": offset,
                    "PicID": 0,
                    "PicSpeed": 70 if len(dummy_media.vinyl_frames_b64) > 16 else 140,
                    "PicData": b64_frame
                })
            self.prefetch_status = "Vinyl Sent Early"
        except Exception as e:
            self.prefetch_status = f"Early Vinyl Error: {e}"
        finally:
            self._is_processing_image = False
            self._update_prefetch_sensor_state()

    async def _do_early_cassette_send(self, dummy_media: MediaData):
        if not dummy_media or not dummy_media.cassette_frames_b64:
            return
            
        self._is_processing_image = True
        self.prefetch_status = "Sending Early Cassette..."
        self._update_prefetch_sensor_state()
        
        self._early_slider_sent_for = f"cassette_{dummy_media.artist}_{dummy_media.title}".strip().lower()
        
        try:
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Channel/SetIndex", "SelectIndex": 4},
                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                    {"Command": "Draw/ResetHttpGifId"}
                ]
            })
            for offset, b64_frame in enumerate(dummy_media.cassette_frames_b64):
                await self.pixoo_device.send_command({
                    "Command": "Draw/SendHttpGif",
                    "PicNum": len(dummy_media.cassette_frames_b64),
                    "PicWidth": 64,
                    "PicOffset": offset,
                    "PicID": 0,
                    "PicSpeed": 100,
                    "PicData": b64_frame
                })
            self.prefetch_status = "Cassette Sent Early"
        except Exception as e:
            self.prefetch_status = f"Early Cassette Error: {e}"
        finally:
            self._is_processing_image = False
            self._update_prefetch_sensor_state()

    async def _fetch_player_queue(self) -> Tuple[List[Dict], Optional[int]]:
        state = self.hass.states.get(self.media_player)
        if not state:
            return [], None

        queue = state.attributes.get('queue', [])
        queue_pos = state.attributes.get('queue_position')

        if not queue and self.hass.services.has_service("sonos", "get_queue"):
            try:
                response = await self.hass.services.async_call(
                    "sonos", "get_queue", {"entity_id": self.media_player}, 
                    blocking=True, return_response=True
                )
                if response and self.media_player in response:
                    queue = response[self.media_player]
            except Exception as e:
                _LOGGER.debug("Failed to fetch Sonos queue: %s", e)

        if not isinstance(queue, list) or not queue:
            return [], None

        curr_title = (self.media_data.title or "").strip().lower()
        curr_artist = (self.media_data.artist or "").strip().lower()
        if curr_title:
            for idx, item in enumerate(queue):
                if not isinstance(item, dict):
                    continue
                t = str(item.get('title') or item.get('name') or item.get('media_title') or '').strip().lower()
                a = str(item.get('artist') or item.get('media_artist') or '').strip().lower()
                if curr_title in t or t in curr_title:
                    if not curr_artist or curr_artist in a or a in curr_artist:
                        return queue, idx

        if isinstance(queue_pos, int) and queue_pos > 0:
            norm_pos = queue_pos - 1
            if 0 <= norm_pos < len(queue):
                return queue, norm_pos

        return queue, None

    async def _get_next_song_info(self) -> Optional[Tuple[str, str, str, str, str, int]]:
        queue, current_idx = await self._fetch_player_queue()
        if not queue or current_idx is None:
            return None

        next_idx = current_idx + 1
        if 0 <= next_idx < len(queue):
            next_item = queue[next_idx]
            if isinstance(next_item, dict):
                artist = next_item.get('artist') or next_item.get('media_artist')
                title = next_item.get('title') or next_item.get('name') or next_item.get('media_title')
                album = next_item.get('album') or next_item.get('media_album_name') or ""
                url = next_item.get('image') or next_item.get('entity_picture')
                duration = next_item.get('duration') or next_item.get('media_duration') or 0
                
                if artist and title:
                    clean_flag = getattr(self.config, 'clean_title', True)
                    cleaned_title = self.media_data.clean_title(title) if clean_flag else title
                    return str(artist), str(cleaned_title), str(album), url, str(title), int(duration)
        return None

    async def _run_playlist_prefetch(self):
        is_force_ai = getattr(self.config, 'force_ai', False)
        is_prefetch_enabled = getattr(self.config, 'prefetch_enabled', False)
        if not is_prefetch_enabled and not is_force_ai:
            self.playlist_prefetch_status = "Disabled (Prefetch disabled)"
            self._update_prefetch_sensor_state()
            return

        if getattr(self.config, 'spotify_slide', False) or getattr(self.config, 'artist_slide', False): 
            self.playlist_prefetch_status = "Disabled (Slider active)"
            self._update_prefetch_sensor_state()
            return

        pref_setting = getattr(self.config, 'playlist_prefetch_range', 'Disabled')
        if pref_setting == 'Disabled':
            self.playlist_prefetch_status = "Disabled in settings"
            self._update_prefetch_sensor_state()
            return

        range_val = 5 if pref_setting == '±5 Songs' else 10
        queue, queue_pos = await self._fetch_player_queue()

        if not queue or queue_pos is None:
            self.playlist_prefetch_status = "No queue detected"
            self.playlist_queue_total = 0
            self.playlist_queue_position = None
            self.playlist_cached_count = 0
            self.playlist_window_range = "None"
            self._update_prefetch_sensor_state()
            return

        self.playlist_queue_total = len(queue)
        self.playlist_queue_position = queue_pos + 1

        start_idx = max(0, queue_pos - range_val)
        end_idx = min(len(queue), queue_pos + range_val + 1)
        self.playlist_window_range = f"Tracks {start_idx + 1} to {end_idx}"

        target_items = []
        for i in range(start_idx, end_idx):
            if i == queue_pos:
                continue
            target_items.append((i, queue[i]))

        cached_count = 0
        total_target = len(target_items)
        self.playlist_prefetch_status = f"Scanning {total_target} tracks in window..."
        self._update_prefetch_sensor_state()

        clean_flag = getattr(self.config, 'clean_title', True)
        for idx, item in target_items:
            if not isinstance(item, dict):
                continue
            artist = item.get('artist') or item.get('media_artist')
            title = item.get('title') or item.get('name') or item.get('media_title')
            album = item.get('album') or item.get('media_album_name') or ""
            url = item.get('image') or item.get('entity_picture')

            if not artist or not title:
                continue
            clean_t = str(self.media_data.clean_title(title) if clean_flag else title)
            clean_a = str(artist)
            song_key = f"{clean_a}_{album or clean_t}".strip().lower()

            if song_key in self.fallback_service._artwork_cache or (url and url in self.image_processor.raw_image_cache):
                cached_count += 1
                self.playlist_cached_count = cached_count
                continue

            dummy_media = MediaData(self.hass, self.config, self.image_processor, self.websession)
            dummy_media.artist = clean_a
            dummy_media.title = clean_t
            dummy_media.album = str(album)
            dummy_media.picture = url
            dummy_media.playing_tv = False
            dummy_media.playing_radio = False
            dummy_media.radio_logo = False

            try:
                res = await self.fallback_service.get_final_url(url, dummy_media)
                if res:
                    cached_count += 1
            except Exception:
                pass

            self.playlist_cached_count = cached_count
            self.playlist_prefetch_status = f"Caching... ({cached_count}/{total_target} ready)"
            self._update_prefetch_sensor_state()
            await asyncio.sleep(0.4)

        self.playlist_prefetch_status = f"Ready ({cached_count}/{total_target} cached in window)"
        self._update_prefetch_sensor_state()

    async def force_update(self):
        self._apply_logic_matrix()
        master_control = self.ui_state.get("master_control", True)
        if not master_control:
            await self._send_off_command()
            return
            
        state = self.hass.states.get(self.media_player)
        if state and self._is_player_active(state):
            self._stop_lyrics_scheduler()
            self._stop_clock_scheduler()
            self._cleanup_timers() 
            self._cancel_tasks(['current_task', '_playlist_prefetch_task', '_early_send_task'])

            await self.media_data.update()
            if not self.media_data.title and not getattr(self.media_data, 'playing_tv', False):
                await self._send_off_command()
                return

            self._fetch_external_temperature()
            queue, current_idx = await self._fetch_player_queue()
            if queue:
                self.media_data.queue_total = len(queue)
            if current_idx is not None:
                self.media_data.track_number = current_idx + 1

            self._active_song_key = None
            self.media_data.track_changed = True
            
            self.current_task = self.hass.async_create_task(self._process_and_send())
            self._playlist_prefetch_task = self.hass.async_create_task(self._run_playlist_prefetch())
        else:
            await self._send_off_command()

    async def _handle_media_change(self, event):
        if self.notification_manager.is_active:
            return
        master_control = self.ui_state.get("master_control", True)
        if not master_control:
            return
        
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not new_state:
            return
        
        pause_setting = self.ui_state.get("pause_timeout", "15s")
        is_pause_enabled = pause_setting not in ["Disabled (0s)", "0s", "Disabled"]

        if new_state.state == "paused":
            if is_pause_enabled:
                self._stop_lyrics_scheduler()
                self.osd_mode = "Pause"
                self.request_text_render(force=True)
                self._cleanup_timers(['_pause_timeout_unsub', '_volume_osd_timer_unsub'])
                if pause_setting != "Never":
                    timeout_val = int(pause_setting.replace("s", "").split()[0])
                    self._pause_timeout_unsub = async_call_later(self.hass, timeout_val, self._execute_pause_timeout)
                return
            else:
                await self._send_off_command()
                self._stop_lyrics_scheduler()
                return

        if old_state and old_state.state == "paused" and self._is_player_active(new_state):
            self._cleanup_timers(['_pause_timeout_unsub'])
            self.osd_mode = None
            self.request_text_render(force=True)

        if not self._is_player_active(new_state):
            await self._send_off_command()
            self._stop_lyrics_scheduler()
            return

        is_volume_change = False
        if old_state and self._is_player_active(old_state):
            new_vol = new_state.attributes.get("volume_level")
            old_vol = old_state.attributes.get("volume_level")
            if new_vol is not None and old_vol is not None and new_vol != old_vol:
                is_volume_change = True
                self.last_volume_level = new_vol

        vol_setting = self.ui_state.get("volume_osd", "2s")
        is_volume_osd_enabled = vol_setting not in ["Disabled (0s)", "0s", "Disabled"]

        if is_volume_change:
            if is_volume_osd_enabled:
                self.osd_mode = "Volume"
                self.request_text_render(force=True)
                vol_duration = int(vol_setting.replace("s", "").split()[0])
                self._cleanup_timers(['_volume_osd_timer_unsub'])
                
                def _clear_vol_osd(now):
                    if self.osd_mode == "Volume":
                        self.osd_mode = None
                        self.request_text_render(force=True)
                        
                self._volume_osd_timer_unsub = async_call_later(self.hass, vol_duration, _clear_vol_osd)
            
            old_title = old_state.attributes.get("media_title")
            new_title = new_state.attributes.get("media_title")
            if old_title == new_title:
                self.progress_timer_gen_id += 1
                await self._update_progress_bar_loop()
                return 

        raw_new_title = str(new_state.attributes.get("media_title") or "")
        clean_flag = getattr(self.config, 'clean_title', True)
        cleaned_new_title = (self.media_data.clean_title(raw_new_title) if clean_flag else raw_new_title).strip().lower()
        new_track_artist = str(new_state.attributes.get("media_artist") or "").strip().lower()
        current_title = str(self.media_data.title or "").strip().lower()
        current_artist = str(self.media_data.artist or "").strip().lower()

        # If the track is STILL the same (e.g., seeking/skipping forward or attribute update)
        if cleaned_new_title and cleaned_new_title == current_title and new_track_artist == current_artist:
            try:
                self.media_data.media_position = float(new_state.attributes.get('media_position', self.media_data.media_position))
                self.media_data.media_duration = float(new_state.attributes.get('media_duration', self.media_data.media_duration))
                pos_updated_at_str = new_state.attributes.get('media_position_updated_at')
                if isinstance(pos_updated_at_str, datetime):
                    self.media_data.media_position_updated_at = pos_updated_at_str
                elif pos_updated_at_str:
                    self.media_data.media_position_updated_at = datetime.fromisoformat(pos_updated_at_str.replace('Z', '+00:00'))
            except Exception:
                pass

            if self._is_processing_image:
                return

            if self.is_art_visible and f"{current_artist}_{current_title}" == self._active_song_key:
                self.progress_timer_gen_id += 1
                await self._update_progress_bar_loop()
                
                # ALWAYS reschedule prefetch to account for seeking/skipping forward!
                if self.prefetch_status in ["Idle", "No next song detected", "Cancelled", ""]:
                    self._schedule_prefetch()
                return

        self._stop_lyrics_scheduler()
        self._stop_clock_scheduler()
        self._cleanup_timers()
        self._cancel_tasks(['_prefetch_task', '_playlist_prefetch_task', 'current_task', '_early_send_task'])

        await self.media_data.update()
        self._fetch_external_temperature()

        if not self.media_data.title and not getattr(self.media_data, 'playing_tv', False):
            await self._send_off_command()
            return

        self.prefetch_status = "Idle"
        self.prefetch_next_artist = None
        self.prefetch_next_title = None

        self._current_live_gif_url = None
        if hasattr(self, 'media_data'):
            self.media_data.live_display_url = None
        
        self.current_task = self.hass.async_create_task(self._process_and_send())
        self._playlist_prefetch_task = self.hass.async_create_task(self._run_playlist_prefetch())

    async def safe_state_change_callback(self, event):
        self._cancel_tasks(['debounce_task'])
        self.debounce_task = asyncio.create_task(self._run_debounced_callback(event))

    async def _run_debounced_callback(self, event):
        try:
            await asyncio.sleep(0.5)
            await self._handle_media_change(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Error in state change callback: %s", e)

    async def _execute_pause_timeout(self, now=None):
        self._pause_timeout_unsub = None
        if self.osd_mode == "Pause":
            await self._send_off_command()

    async def _process_and_send(self):
        self._is_processing_image = True
        async with self._image_lock:
            artist_str = getattr(self.media_data, 'artist', '') or ''
            title_str = getattr(self.media_data, 'title', '') or ''
            profiler = SongProfiler(f"{artist_str} - {title_str}")
            try:
                await self._sync_hardware_state_from_device(allow_channel_update=True)

                current_song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
                current_mode = self.ui_state.get("display_mode", "Standard")
                current_filter = getattr(self.config, 'image_filter', 'None')
                current_crop = getattr(self.config, 'crop_mode', 'No Crop')

                # Immediate notification if AI generation will take place
                is_force_ai = (
                    (current_mode == "Force AI" or getattr(self.config, 'force_ai', False))
                    and getattr(self.config, 'pollinations', None)
                    and not getattr(self.media_data, 'radio_logo', False)
                    and not getattr(self.media_data, 'playing_tv', False)
                )
                if is_force_ai:
                    self.set_ai_generating(True, "Generating AI Artwork...")

                has_timing = (
                    getattr(self.media_data, 'media_duration', 0) > 0 
                    and not getattr(self.media_data, 'playing_radio', False) 
                    and not getattr(self.media_data, 'playing_tv', False)
                )
                lyrics_avail = getattr(self.media_data, 'lyrics_available', False) and has_timing
                configured_mode = current_mode
                new_lyrics_found = (
                    getattr(self.config, 'show_lyrics', False) 
                    and lyrics_avail 
                    and len(self.media_data.lyrics) > 0
                )

                effective_mode = configured_mode
                if configured_mode == "Lyrics" and not new_lyrics_found:
                    effective_mode = "Standard"

                if getattr(self.media_data, 'playing_tv', False):
                    self.hass.async_create_task(self.control_light('off'))
                    self.hass.async_create_task(self.control_wled_light('off'))
                    if not getattr(self.config, 'tv_mode', False) or self.media_data.picture == "TV_IS_ON":
                        target_channel = getattr(self, 'last_valid_index', 0)
                        if target_channel == 4 or target_channel < 0:
                            target_channel = 0
                        if getattr(self.config, 'full_control', False):
                            self.device_screen_on = False
                            await self.pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ClearHttpText"}, {"Command": "Draw/ResetHttpGifId"}, {"Command": "Channel/OnOffScreen", "OnOff": 0}]})
                        else:
                            self.device_screen_on = True
                            await self.pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ClearHttpText"}, {"Command": "Draw/ResetHttpGifId"}, {"Command": "Channel/OnOffScreen", "OnOff": 1}, {"Command": "Channel/SetIndex", "SelectIndex": target_channel}]})
                        self.is_art_visible = False
                        self._active_song_key = None
                        if self.sensor:
                            self.sensor.update_state("TV", {
                                "artist": "TV",
                                "media_title": "TV",
                                "active_mode": "TV",
                                "configured_mode": configured_mode,
                                "lyrics_available": False,
                                "has_timing": False,
                                "image_source": "Internal",
                                "pixoo64_channel": target_channel,
                                "brightness": self.device_brightness,
                                "screen_power": "On" if self.device_screen_on else "Off",
                                "ai_generating": False,
                                "ai_status": "Idle"
                            })
                        return
               
                start_time = time.perf_counter()
                current_album = self.media_data.album
                current_artist = self.media_data.artist
                current_pic_url = self.media_data.picture
                
                can_skip = False
                mode_changed = (current_mode != getattr(self, '_last_rendered_mode', None))
                filter_changed = (current_filter != getattr(self, '_last_rendered_filter', None))
                crop_changed = (current_crop != getattr(self, '_last_rendered_crop', None))

                if not (mode_changed or filter_changed or crop_changed):
                    if current_pic_url and current_pic_url == getattr(self, '_last_rendered_pic_url', None) and "token=" not in current_pic_url:
                        can_skip = True
                    elif current_album and current_album == getattr(self, '_last_rendered_album', None) and not getattr(self.media_data, 'radio_logo', False):
                        can_skip = True

                if can_skip:
                    if new_lyrics_found != getattr(self, 'lyrics_active_mode', False):
                        can_skip = False
                    elif not self.is_art_visible:
                        can_skip = False
                    elif getattr(self.config, 'vinyl_mode', False) or getattr(self.config, 'cassette_mode', False) or getattr(self.config, 'burned', False) or getattr(self.config, 'force_ai', False) or getattr(self.config, 'analog_clock', False):
                        can_skip = False
                    elif getattr(self.config, 'spotify_slide', False) or getattr(self.config, 'artist_slide', False):
                        can_skip = False

                if can_skip:
                    _LOGGER.debug("Skipping image processing: Same album/image detected (%s)", current_album)
                    self.is_art_visible = True
                    self.last_text_payload_hash = None
                    self._active_song_key = current_song_key
                    self._is_processing_image = False
                    
                    if getattr(self.config, 'progress_bar_enabled', False) and getattr(self.media_data, 'show_progress_bar', False):
                        pos = self._get_current_media_position()
                        bar_str, _ = self.progress_manager.calculate(pos, self.media_data.media_duration)
                        self.last_progress_str = bar_str
                    else:
                        self.progress_manager.current_bar_str = ""
                        self.last_progress_str = ""
                        
                    self.cached_static_items = await self._build_text_items_list(
                        getattr(self.media_data, 'lyrics_font_color', "#FFFFFF"), 
                        getattr(self.media_data, 'background_color', "#000000"), 
                        scope="static"
                    )
                    self.progress_timer_gen_id += 1

                    if not new_lyrics_found:
                        await self._render_and_send_text_layers(force=True)
                    else:
                        self.lyrics_active_mode = True
                        await self._calculate_and_schedule_next()

                    await self._update_progress_bar_loop()
                    self._schedule_prefetch()
                    
                    if self.sensor:
                        sensor_attrs = dict(self.sensor._attr_extra_state_attributes or {})
                        sensor_attrs.update({
                            "artist": self.media_data.artist,
                            "media_title": self.media_data.title,
                            "media_player": self.media_player,
                            "lyrics_found": new_lyrics_found,
                            "process_duration": "0.0s (Skipped)",
                            "pixoo64_channel": self.last_valid_index,
                            "brightness": self.device_brightness,
                            "screen_power": "On" if self.device_screen_on else "Off",
                            "active_mode": effective_mode,
                            "configured_mode": configured_mode,
                            "lyrics_available": lyrics_avail,
                            "has_timing": has_timing,
                            "ai_generating": False,
                            "ai_status": "Idle",
                        })
                        if self._current_live_gif_url:
                            sensor_attrs["live_display_url"] = self._current_live_gif_url
                        self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)
                    return

                self._last_rendered_mode = current_mode
                self._last_rendered_filter = current_filter
                self._last_rendered_crop = current_crop

                prefetched_hit = False
                processed_data = None
                if getattr(self, '_prefetched_media', None) and not is_force_ai:
                    p_art = str(self._prefetched_media.artist or '').strip().lower()
                    p_tit = str(self._prefetched_media.title or '').strip().lower()
                    c_art = str(self.media_data.artist or '').strip().lower()
                    c_tit = str(self.media_data.title or '').strip().lower()

                    if p_art == c_art and (p_tit in c_tit or c_tit in p_tit):
                        _LOGGER.debug("RAM Cache Hit! Adopting precomputed animation frames & GIF for %s", current_song_key)
                        prefetched_hit = True
                        processed_data = getattr(self._prefetched_media, 'processed_data', None)

                    if p_art == c_art and (p_tit in c_tit or c_tit in p_tit):
                        prefetched_hit = True
                        processed_data = getattr(self._prefetched_media, 'processed_data', None)
                        self.media_data.pic_url = self._prefetched_media.pic_url
                        self.media_data.pic_source = self._prefetched_media.pic_source
                        self.media_data.live_display_url = self._prefetched_media.live_display_url
                        self.media_data.vinyl_frames_b64 = self._prefetched_media.vinyl_frames_b64
                        self.media_data.cassette_frames_b64 = self._prefetched_media.cassette_frames_b64
                        self.media_data.slider_frames_b64 = getattr(self._prefetched_media, 'slider_frames_b64', [])
                        self.media_data.slider_album_urls = self._prefetched_media.slider_album_urls
                        self.media_data.slider_frames = self._prefetched_media.slider_frames
                        self._prefetched_media = None

                t0_art = perf_counter()
                try:
                    if not processed_data:
                        saved_gif_url = self.media_data.live_display_url
                        processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
                        if prefetched_hit and saved_gif_url:
                            self.media_data.live_display_url = saved_gif_url
                finally:
                    profiler.add("artwork_pipeline", perf_counter() - t0_art)

                if not processed_data:
                    processed_data = self.fallback_service._get_fallback_black_image_data()
                
                base64_image = processed_data.get('base64_image')
                font_color = processed_data.get('font_color', '#FFFFFF')
                bg_color_str = processed_data.get('background_color', '#000000')
                bg_color_rgb = processed_data.get('background_color_rgb', (0,0,0))
                color1 = processed_data.get('color1')
                color2 = processed_data.get('color2')
                color3 = processed_data.get('color3')

                sun_state = self.hass.states.get("sun.sun")
                if sun_state and sun_state.state in ["above_horizon", "below_horizon"]:
                    is_night = (sun_state.state == "below_horizon")
                else:
                    now_hour = datetime.now().hour
                    is_night = (now_hour >= 18 or now_hour < 7)

                if not getattr(self.media_data, 'playing_tv', False):
                    self.hass.async_create_task(self.control_light('on', bg_color_rgb, is_night))
                    self.hass.async_create_task(self.control_wled_light('on', [color1, color2, color3], is_night))
                
                is_spotify_slider = getattr(self.config, 'spotify_slide', False) and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False)
                is_artist_slider = getattr(self.config, 'artist_slide', False) and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False)
                is_vinyl = getattr(self.config, 'vinyl_mode', False) and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False)
                is_cassette = getattr(self.config, 'cassette_mode', False) and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False)
                is_analog_clock = getattr(self.config, 'analog_clock', False) and not getattr(self.media_data, 'playing_tv', False)

                early_slider_match = False
                if (is_spotify_slider or is_artist_slider) and self._early_slider_sent_for == f"slider_{current_song_key}":
                    early_slider_match = True
                    if is_spotify_slider:
                        self.media_data.spotify_slide_pass = True
                    else:
                        self.media_data.artist_slide_pass = True

                early_vinyl_match = bool(is_vinyl and self._early_slider_sent_for == f"vinyl_{current_song_key}")
                early_cassette_match = bool(is_cassette and self._early_slider_sent_for == f"cassette_{current_song_key}")

                self._early_slider_sent_for = None
                
                if is_vinyl and not early_vinyl_match:
                    t0_ev = perf_counter()
                    try:
                        vinyl_frames = getattr(self.media_data, 'vinyl_frames_b64', None)
                        if not vinyl_frames:
                            pil_img = processed_data.get('pil_image')
                            vinyl_frames = await self.hass.async_add_executor_job(
                                self.image_processor.generate_vinyl_frames, pil_img, self.media_data
                            )
                        
                        if vinyl_frames:
                            t0_send = perf_counter()
                            try:
                                await self.pixoo_device.send_command({
                                    "Command": "Draw/CommandList", 
                                    "CommandList": [
                                        {"Command": "Channel/SetIndex", "SelectIndex": 4},
                                        {"Command": "Channel/OnOffScreen", "OnOff": 1},
                                        {"Command": "Draw/ResetHttpGifId"}
                                    ]
                                })
                                for offset, b64_frame in enumerate(vinyl_frames):
                                    await self.pixoo_device.send_command({
                                        "Command": "Draw/SendHttpGif",
                                        "PicNum": len(vinyl_frames),
                                        "PicWidth": 64,
                                        "PicOffset": offset,
                                        "PicID": 0,
                                        "PicSpeed": 70 if len(vinyl_frames) > 16 else 140,
                                        "PicData": b64_frame
                                    })
                            finally:
                                profiler.add("pixoo_send", perf_counter() - t0_send)
                            
                            profiler.mark_first_frame()
                            early_vinyl_match = True
                            profiler.set("vinyl_frames", len(vinyl_frames))
                    finally:
                        profiler.add("early_vinyl", perf_counter() - t0_ev)

                if is_cassette and not early_cassette_match:
                    t0_ec = perf_counter()
                    try:
                        cassette_frames = getattr(self.media_data, 'cassette_frames_b64', None)
                        if not cassette_frames:
                            pil_img = processed_data.get('pil_image')
                            cassette_frames = await self.hass.async_add_executor_job(
                                self.image_processor.generate_cassette_frames, pil_img, self.media_data
                            )
                        if cassette_frames:
                            t0_send = perf_counter()
                            try:
                                await self.pixoo_device.send_command({
                                    "Command": "Draw/CommandList", 
                                    "CommandList": [
                                        {"Command": "Channel/SetIndex", "SelectIndex": 4},
                                        {"Command": "Channel/OnOffScreen", "OnOff": 1},
                                        {"Command": "Draw/ResetHttpGifId"}
                                    ]
                                })
                                for offset, b64_frame in enumerate(cassette_frames):
                                    await self.pixoo_device.send_command({
                                        "Command": "Draw/SendHttpGif",
                                        "PicNum": len(cassette_frames),
                                        "PicWidth": 64,
                                        "PicOffset": offset,
                                        "PicID": 0,
                                        "PicSpeed": 100,
                                        "PicData": b64_frame
                                    })
                            finally:
                                profiler.add("pixoo_send", perf_counter() - t0_send)
                            
                            profiler.mark_first_frame()
                            early_cassette_match = True
                            profiler.set("cassette_frames", len(cassette_frames))
                    finally:
                        profiler.add("early_cassette", perf_counter() - t0_ec)

                if is_analog_clock:
                    pil_img = processed_data.get('pil_image')
                    self._current_clock_pil_img = pil_img
                    self._current_clock_song_key = current_song_key
                    clock_b64 = await self.hass.async_add_executor_job(
                        self.image_processor.generate_analog_clock_frame, pil_img, self.media_data
                    )
                    if clock_b64:
                        base64_image = clock_b64

                if not early_slider_match and not early_vinyl_match and not early_cassette_match and not is_spotify_slider and not is_artist_slider:
                    image_cmd = {
                        "Command": "Draw/CommandList", 
                        "CommandList": [
                            {"Command": "Channel/SetIndex", "SelectIndex": 4},
                            {"Command": "Channel/OnOffScreen", "OnOff": 1}, 
                            {"Command": "Draw/ResetHttpGifId"}, 
                            {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 10000, "PicData": base64_image}
                        ]
                    }
                    t0_send = perf_counter()
                    try:
                        await self.pixoo_device.send_command(image_cmd)
                    finally:
                        profiler.add("pixoo_send", perf_counter() - t0_send)
                    
                    profiler.mark_first_frame()
                
                self.device_screen_on = True
                self.is_art_visible = True
                if self._active_song_key != current_song_key:
                    self.last_text_payload_hash = None 
                self._active_song_key = current_song_key
                self._last_rendered_album = current_album
                self._last_rendered_artist = current_artist
                self._last_rendered_pic_url = self.media_data.picture
                
                self.media_data.lyrics_font_color = font_color
                self.media_data.background_color = bg_color_str

                if getattr(self.config, 'progress_bar_enabled', False) and getattr(self.media_data, 'show_progress_bar', False):
                    pos = self._get_current_media_position()
                    bar_str, _ = self.progress_manager.calculate(pos, self.media_data.media_duration)
                    self.last_progress_str = bar_str
                else:
                    self.progress_manager.current_bar_str = ""
                    self.last_progress_str = ""

                self._fetch_external_temperature()
                self.cached_static_items = await self._build_text_items_list(font_color, bg_color_str, scope="static")
                self.progress_timer_gen_id += 1

                if is_spotify_slider and not early_slider_match:
                    t0_ss = perf_counter()
                    try:
                        self.spotify_slider_status = f"Loading Live Slider for {self.media_data.artist}..."
                        self.spotify_slider_artist = self.media_data.artist
                        self._update_prefetch_sensor_state()
                        await self.spotify_service.prepare_slider_for_media(self.media_data)
                        if getattr(self.config, 'special_mode_spotify_slider', False): 
                            await self.spotify_service.spotify_album_art_animation(self.pixoo_device, self.media_data, self.select_index)
                        else: 
                            await self.spotify_service.spotify_albums_slide(self.pixoo_device, self.media_data, self.select_index, send_to_device=True)
                        
                        if getattr(self.media_data, 'spotify_slide_pass', False):
                            self.spotify_slider_status = f"Active Live ({self.media_data.slider_frames} frames)"
                            self.spotify_slider_frames = self.media_data.slider_frames
                            profiler.set("spotify_frames", self.media_data.slider_frames)
                        else:
                            self.spotify_slider_status = f"Live Failed: {self.media_data.slider_error or 'No albums found'}"
                            self.spotify_slider_last_error = self.media_data.slider_error
                    finally:
                        profiler.add("spotify_slider", perf_counter() - t0_ss)

                elif is_artist_slider and not early_slider_match:
                    t0_as = perf_counter()
                    try:
                        self.spotify_slider_status = f"Loading Artist Gallery for {self.media_data.artist}..."
                        self.spotify_slider_artist = self.media_data.artist
                        self._update_prefetch_sensor_state()
                        
                        await self.fallback_service.play_artist_gallery_slide(self.pixoo_device, self.media_data, send_to_device=True)
                        
                        if getattr(self.media_data, 'artist_slide_pass', False):
                            self.spotify_slider_status = f"Active Live ({self.media_data.slider_frames} frames)"
                            self.spotify_slider_frames = self.media_data.slider_frames
                            profiler.set("artist_frames", self.media_data.slider_frames)
                        else:
                            self.spotify_slider_status = f"Live Failed: {self.media_data.slider_error or 'No artist images found'}"
                            self.spotify_slider_last_error = self.media_data.slider_error
                    finally:
                        profiler.add("artist_slider", perf_counter() - t0_as)

                await asyncio.sleep(0.3)

                if new_lyrics_found != self.lyrics_active_mode:
                    self.lyrics_active_mode = new_lyrics_found
                    if self.lyrics_active_mode:
                        processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
                        base64_image = processed_data.get('base64_image')
                        t0_send = perf_counter()
                        try:
                            await self.pixoo_device.send_command({
                                "Command": "Draw/CommandList", 
                                "CommandList": [
                                    {"Command": "Draw/ResetHttpGifId"}, 
                                    {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 10000, "PicData": base64_image}
                                ]
                            })
                        finally:
                            profiler.add("pixoo_send", perf_counter() - t0_send)

                        t0_ly = perf_counter()
                        try:
                            await self._calculate_and_schedule_next()
                        finally:
                            profiler.add("lyrics", perf_counter() - t0_ly)
                    else:
                        self._stop_lyrics_scheduler()
                elif self.lyrics_active_mode:
                    t0_ly = perf_counter()
                    try:
                        await self._calculate_and_schedule_next()
                    finally:
                        profiler.add("lyrics", perf_counter() - t0_ly)

                self._is_processing_image = False

                if not self.lyrics_active_mode:
                    self.last_text_payload_hash = None
                    t0_rnd = perf_counter()
                    try:
                        await self._render_and_send_text_layers(force=True)
                    finally:
                        profiler.add("render", perf_counter() - t0_rnd)

                await self._update_progress_bar_loop()
                self._schedule_prefetch()

                if is_analog_clock:
                    self._schedule_analog_clock_tick(processed_data)

                self.profile_data = profiler.build_attributes()
                _LOGGER.debug(profiler.build_log_line())

                if is_analog_clock or is_vinyl or is_cassette or is_spotify_slider or is_artist_slider:
                    self._current_live_gif_url = getattr(self.media_data, 'live_display_url', None)
                else:
                    self._current_live_gif_url = (
                        processed_data.get('live_display_url')
                        or getattr(self.media_data, 'live_display_url', None)
                    )
                    self.media_data.live_display_url = self._current_live_gif_url

                duration = time.perf_counter() - start_time

                sensor_attrs = {
                    "artist": self.media_data.artist,
                    "media_title": self.media_data.title,
                    "media_player": self.media_player,
                    "image_source": self.media_data.pic_source,
                    "image_url": self.media_data.pic_url,
                    "live_display_url": self._current_live_gif_url,
                    "active_mode": effective_mode,
                    "configured_mode": configured_mode,
                    "lyrics_available": lyrics_avail,
                    "has_timing": has_timing,
                    "font_color": font_color,
                    "background_color": bg_color_str,
                    "background_color_rgb": processed_data.get('background_color_rgb'),
                    "brightness_lower_part": processed_data.get('brightness_lower_part'),
                    "color1": color1,
                    "color2": color2,
                    "color3": color3,
                    "wled_colors": [color1, color2, color3],
                    "general_cache_size": len(self.image_processor.image_cache),
                    "general_cache_limit": self.image_processor.cache_size,
                    "playlist_prefetch_setting": getattr(self.config, 'playlist_prefetch_range', 'Disabled'),
                    "playlist_prefetch_status": self.playlist_prefetch_status,
                    "playlist_queue_total": self.playlist_queue_total,
                    "playlist_queue_position": self.playlist_queue_position,
                    "playlist_cached_count": self.playlist_cached_count,
                    "playlist_window_range": self.playlist_window_range,
                    "process_duration": f"{duration:.2f}s (RAM)" if prefetched_hit else f"{duration:.2f}s",
                    "progress_bar_active": getattr(self.media_data, 'show_progress_bar', False),
                    "lyrics_found": new_lyrics_found,
                    "pixoo64_channel": self.last_valid_index,
                    "brightness": self.device_brightness,
                    "screen_power": "On" if self.device_screen_on else "Off",
                    "slider_status": self.spotify_slider_status,
                    "slider_frames": self.spotify_slider_frames,
                    "slider_last_error": self.spotify_slider_last_error,
                    "ai_generating": False,
                    "ai_status": "Idle",
                }
                
                if self.profile_data:
                    sensor_attrs.update(self.profile_data)

                if self.sensor:
                    self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)

            except asyncio.CancelledError:
                pass
            except Exception as e:
                _LOGGER.error("Execution error: %s", e)
            finally:
                self.ai_generating = False
                self.ai_status = "Idle"
                self._is_processing_image = False

    async def _update_progress_bar_loop(self):
        if self.notification_manager.is_active or getattr(self, '_is_processing_image', False):
            return
        state = self.hass.states.get(self.media_player)
        if not state or state.state not in ["playing", "on"]:
            return
        if not getattr(self.config, 'progress_bar_enabled', False):
            return
            
        pos = self._get_current_media_position()
        bar_str, delay = self.progress_manager.calculate(pos, getattr(self.media_data, 'media_duration', 0.0))
        if self.is_art_visible:
            if bar_str != self.last_progress_str or self.last_text_payload_hash is None:
                self.last_progress_str = bar_str
                self.request_text_render()
                
        safe_delay = delay if delay is not None else 5.0
        
        gen_id = self.progress_timer_gen_id
        async def _pb_timer(now):
            if self.progress_timer_gen_id == gen_id:
                await self._update_progress_bar_loop()
        self._cleanup_timers(['_progress_timer_unsub'])
        self._progress_timer_unsub = async_call_later(self.hass, safe_delay, _pb_timer)

    def _stop_lyrics_scheduler(self):
        self.lyrics_active_mode = False
        self.scheduler_generation_id += 1
        self.current_lyrics_items = []

    def _stop_clock_scheduler(self):
        self.clock_timer_gen_id += 1
        self._current_clock_pil_img = None
        self._current_clock_song_key = None
        self._cleanup_timers(['_clock_timer_unsub'])

    async def async_handle_notification_service(self, call):
        message = call.data.get("message")
        if not message:
            return
        was_screen_on = True
        try:
            curr_ch = await self.pixoo_device.get_current_channel_index()
            if curr_ch is not None and 0 <= curr_ch <= 3:
                self.last_valid_index = curr_ch
                self.select_index = curr_ch
            was_screen_on = await self.pixoo_device.get_screen_on_state()
        except Exception:
            pass

        media_state = self.hass.states.get(self.media_player)
        if not (media_state and media_state.state in ["playing", "on"]) and getattr(self.config, 'full_control', False) and not self.is_art_visible:
            was_screen_on = False

        self.notification_manager.is_active = True
        self._stop_lyrics_scheduler()
        self._cleanup_timers()
        self._cancel_tasks()

        event_data = {
            "message": message, "type": call.data.get("type", "text"),
            "duration": call.data.get("duration", 5), "color": call.data.get("color"),
            "play_buzzer": call.data.get("play_buzzer", False), "buzzer_active": call.data.get("buzzer_active", 500),
            "buzzer_off": call.data.get("buzzer_off", 500), "buzzer_total": call.data.get("buzzer_total", 3000),
        }
        await self.notification_manager.display(event_data)

        rechecked_state = self.hass.states.get(self.media_player)
        if rechecked_state and rechecked_state.state in ["playing", "on"]:
            self.is_art_visible = False
            self._active_song_key = None
            await self.force_update()
        else:
            if getattr(self.config, 'full_control', False) and not was_screen_on:
                await self.pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ClearHttpText"}, {"Command": "Draw/ResetHttpGifId"}, {"Command": "Channel/OnOffScreen", "OnOff": 0}]})
                self.is_art_visible = False
                self._active_song_key = None
            else:
                target_ret = getattr(self, 'last_valid_index', 0)
                if target_ret == 4 or target_ret < 0:
                    target_ret = 0
                await self.pixoo_device.send_command({"Command": "Draw/CommandList", "CommandList": [{"Command": "Draw/ClearHttpText"}, {"Command": "Draw/ResetHttpGifId"}, {"Command": "Channel/OnOffScreen", "OnOff": 1}, {"Command": "Channel/SetIndex", "SelectIndex": target_ret}]})

    def _schedule_analog_clock_tick(self, processed_data: dict = None):
        self._cleanup_timers(['_clock_timer_unsub'])
        if not getattr(self.config, 'analog_clock', False) or not self.is_art_visible:
            return

        if processed_data is not None:
            self._current_clock_pil_img = processed_data.get('pil_image')
            self._current_clock_song_key = self._active_song_key

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
            
            if self.clock_timer_gen_id != gen_id:
                return
            if not getattr(self.config, 'analog_clock', False) or not self.is_art_visible:
                return

            current_song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
            if not self._current_clock_pil_img or self._current_clock_song_key != current_song_key:
                return

            clock_b64 = await self.hass.async_add_executor_job(
                self.image_processor.generate_analog_clock_frame, self._current_clock_pil_img, self.media_data
            )

            if self.clock_timer_gen_id != gen_id:
                return
            if self._current_clock_song_key != current_song_key:
                return

            if clock_b64:
                filter_mode = getattr(self.config, 'image_filter', 'None')
                clock_pil = AnalogClockRenderer.render(self._current_clock_pil_img.copy())
                clock_pil = self.image_processor.filter_service.apply_post_scale(clock_pil, filter_mode)
                clock_pil = self.image_processor.text_clock_img(clock_pil, {}, self.media_data)
                
                c_key = f"clock_{current_song_key}_{filter_mode}"
                self._current_live_gif_url = await self.image_processor.async_save_live_display_gif([clock_pil], 1000, c_key)
                self.media_data.live_display_url = self._current_live_gif_url

                await self.pixoo_device.send_command({
                    "Command": "Draw/CommandList",
                    "CommandList": [
                        {"Command": "Draw/ResetHttpGifId"},
                        {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 10000, "PicData": clock_b64}
                    ]
                })
                self.request_text_render(force=True)

                if self.sensor:
                    attrs = dict(self.sensor._attr_extra_state_attributes or {})
                    attrs["live_display_url"] = self._current_live_gif_url
                    attrs["pixoo64_channel"] = self.last_valid_index
                    self.sensor.update_state(self.sensor._attr_native_value, attrs)

            self._schedule_analog_clock_tick()

        self._clock_timer_unsub = async_call_later(self.hass, delay, _tick)

    def _is_player_active(self, state) -> bool:
        if not state:
            return False
        if state.state == "playing":
            return True
        if state.state == "on":
            title = state.attributes.get("media_title") or state.attributes.get("title")
            app = str(state.attributes.get("app_name") or "").lower()
            source = str(state.attributes.get("source") or "").lower()
            is_tv = "tv" in source or "tv" in app or "hdmi" in source
            return bool((title and str(title).strip()) or is_tv)
        return False
        
    
