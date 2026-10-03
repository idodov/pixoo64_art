"""The Core Hub managing UI states and delegating to pixoo_services."""
import asyncio
import logging
import time
import json
from datetime import datetime, timezone
from typing import Optional, Tuple
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_call_later

from .const import CONF_PIXOO_IP, CONF_MEDIA_PLAYER
from .pixoo_services import (
    Config, PixooDevice, ImageProcessor, SpotifyService, FallbackService,
    LyricsProvider, MediaData, ProgressBarManager, NotificationManager,
    has_bidi, get_bidi
)

_LOGGER = logging.getLogger(__name__)

class PixooHub:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.pixoo_ip = entry.data[CONF_PIXOO_IP]
        self.media_player = entry.data[CONF_MEDIA_PLAYER]
        
        self.ui_state = {}
        self.config = Config(entry)
        self.sensor = None
        self._unsub_listeners = []
        self._image_lock = asyncio.Lock()
        self._active_song_key = None 
        
        self.websession = async_get_clientsession(hass)
        self.pixoo_device = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.hass, self.config, self.websession)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.media_data = MediaData(self.hass, self.config, self.image_processor, self.websession)
        self.fallback_service = FallbackService(self.config, self.image_processor, self.websession, self.spotify_service, self.pixoo_device)
        self.progress_manager = ProgressBarManager(self.config, self.hass)
        self.notification_manager = NotificationManager(self.config, self.pixoo_device, self.image_processor, self.hass)

        self.is_art_visible = False
        self.lyrics_active_mode = False
        self.last_text_payload_hash = None
        self.cached_static_items = []
        self.current_lyrics_items = []
        self.progress_timer_gen_id = 0
        self.scheduler_generation_id = 0
        self.last_progress_str = ""
        
        # OSD Variables
        self.osd_mode = None
        self.last_volume_level = 0.0
        
        # Async Tasks and Timers State
        self.current_task = None
        self.debounce_task = None
        self._prefetch_task = None
        self._progress_timer_unsub = None
        self._lyrics_timer_unsub = None
        self._pending_render_unsub = None
        self._prefetch_timer_unsub = None
        self._early_send_timer_unsub = None
        self._pause_timeout_unsub = None
        self._volume_osd_timer_unsub = None
        
        self._early_slider_sent_for = None
        self.prefetch_status = "Idle"
        self.prefetch_next_artist = None
        self.prefetch_next_title = None

    def _cleanup_timers(self, timers=None):
        """Safely unsubscribe specified timers or all known timers."""
        default_timers = [
            '_progress_timer_unsub', '_lyrics_timer_unsub', 
            '_pending_render_unsub', '_prefetch_timer_unsub', 
            '_early_send_timer_unsub', '_pause_timeout_unsub',
            '_volume_osd_timer_unsub'
        ]
        for attr in (timers or default_timers):
            unsub = getattr(self, attr, None)
            if unsub:
                unsub()
                setattr(self, attr, None)

    def _cancel_tasks(self, tasks=None):
        """Safely cancel specified tasks or all known tasks."""
        default_tasks = ['current_task', 'debounce_task', '_prefetch_task']
        for attr in (tasks or default_tasks):
            task = getattr(self, attr, None)
            if task and not task.done():
                task.cancel()
            setattr(self, attr, None)

    def set_sensor(self, sensor):
        self.sensor = sensor

    def _update_prefetch_sensor_state(self):
        if not self.sensor: return
        attrs = dict(self.sensor._attr_extra_state_attributes) if self.sensor._attr_extra_state_attributes else {}
        attrs["prefetch_status"] = self.prefetch_status
        attrs["prefetch_next_artist"] = self.prefetch_next_artist
        attrs["prefetch_next_title"] = self.prefetch_next_title
        
        state_val = getattr(self.sensor, '_attr_native_value', "Initializing")
        self.sensor.update_state(state_val, attrs)

    async def initialize(self):
        try:
            curr = await self.pixoo_device.get_current_channel_index()
            if curr != 4: 
                self.select_index = self.last_valid_index = curr
            else: 
                self.select_index = getattr(self, 'last_valid_index', 0)
        except Exception:
            self.select_index = 0
            self.last_valid_index = 0

        self._apply_logic_matrix()

        self._unsub_listeners.append(
            async_track_state_change_event(self.hass, [self.media_player], self.safe_state_change_callback)
        )
        
        state = self.hass.states.get(self.media_player)
        if state and state.state in ["playing", "on"]:
            await self.force_update()

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
        self._active_song_key = None 
        
        if key in ["force_ai", "crop_mode", "text_background", "text_position", "display_mode", "overlay_position", "overlay_align"]:
            self.image_processor.image_cache.clear()
            if hasattr(self.fallback_service, "_artwork_cache"):
                self.fallback_service._artwork_cache.clear()
            
        await self.force_update()

    async def _send_off_command(self):
        if self.sensor: 
            self.sensor.update_state("Off", {})
            
        self.is_art_visible = False
        self._active_song_key = None
        self.osd_mode = None
        
        self.prefetch_status = "Idle"
        self.prefetch_next_artist = None
        self.prefetch_next_title = None
        self._early_slider_sent_for = None
        
        self._cleanup_timers(['_prefetch_timer_unsub', '_early_send_timer_unsub', '_pause_timeout_unsub', '_volume_osd_timer_unsub'])
        self._cancel_tasks(['_prefetch_task'])
        
        await self.control_light('off')
        await self.control_wled_light('off')
        
        if getattr(self.config, 'full_control', False):
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},  
                    {"Command": "Draw/ResetHttpGifId"},
                    {"Command": "Channel/OnOffScreen", "OnOff": 0}
                ]
            })
        else:
            target_channel = getattr(self, 'select_index', 0)
            if target_channel == 4:
                target_channel = getattr(self, 'last_valid_index', 0)
            if target_channel == 4:
                target_channel = 0

            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},  
                    {"Command": "Draw/ResetHttpGifId"},
                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                    {"Command": "Channel/SetIndex", "SelectIndex": target_channel}
                ]
            })

    @property
    def is_ai_available(self) -> bool:
        options = self.entry.options
        data = self.entry.data
        key = (
            options.get("pollinations_key")
            or data.get("pollinations_key")
            or getattr(self.config, "pollinations", "")
        )
        return bool(key and isinstance(key, str) and len(str(key).strip()) > 5)

    @property
    def is_spotify_available(self) -> bool:
        options = self.entry.options
        data = self.entry.data
        cid = (
            options.get("spotify_client_id")
            or data.get("spotify_client_id")
            or getattr(self.config, "spotify_client_id", "")
        )
        csec = (
            options.get("spotify_client_secret")
            or data.get("spotify_client_secret")
            or getattr(self.config, "spotify_client_secret", "")
        )
        return bool(
            str(cid).strip() and str(csec).strip()
            and len(str(cid).strip()) > 5 and len(str(csec).strip()) > 5
        )

    def _apply_logic_matrix(self):
        options = self.entry.options
        data = self.entry.data

        # --- FIX: ENSURING ALL API KEYS ARE MAPPED TO CONFIG ---
        self.config.pollinations = options.get("pollinations_key", data.get("pollinations_key", ""))
        self.config.spotify_client_id = options.get("spotify_client_id", data.get("spotify_client_id", ""))
        self.config.spotify_client_secret = options.get("spotify_client_secret", data.get("spotify_client_secret", ""))
        
        # New Fallback Services API Keys mapping
        self.config.musicbrainz = options.get("musicbrainz_enabled", data.get("musicbrainz_enabled", True))
        self.config.tidal_client_id = options.get("tidal_client_id", data.get("tidal_client_id", ""))
        self.config.tidal_client_secret = options.get("tidal_client_secret", data.get("tidal_client_secret", ""))
        self.config.lastfm = options.get("lastfm_key", data.get("lastfm_key", ""))
        self.config.discogs = options.get("discogs_token", data.get("discogs_token", ""))

        # Base Configuration settings
        self.config.tv_mode = options.get("tv_mode", data.get("tv_mode", False))
        self.config.temperature_sensor = options.get("temperature_entity", data.get("temperature_entity"))
        
        # OSD Configuration (read from config flow instead of UI entities)
        self.config.osd_overlay = options.get("osd_overlay", data.get("osd_overlay", "Enabled"))
        self.config.pause_timeout = options.get("pause_timeout", data.get("pause_timeout", "15s"))
        self.config.volume_osd_duration = options.get("volume_osd_duration", data.get("volume_osd_duration", "2s"))
        
        # UI Entities state mapping
        self.config.full_control = self.ui_state.get("full_control", False)
        self.config.progress_bar_enabled = self.ui_state.get("progress_bar", True)
        self.config.force_ai = bool(self.ui_state.get("force_ai", False) and self.is_ai_available)
        self.config.text_bg = self.ui_state.get("text_background", True)

        self.config.lyrics_sync = float(self.ui_state.get("lyrics_sync", 0.0))

        crop_mode = self.ui_state.get("crop_mode", "No Crop")
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

        m = display_mode.lower()
        self.config.show_lyrics = (m == "lyrics")
        self.config.burned = (m == "burned")
        self.config.special_mode = ("special" in m)
        self.config.spotify_slide = ("slider" in m) and self.is_spotify_available

        self.config.special_mode_spotify_slider = bool(
            self.config.spotify_slide and self.config.special_mode and self.config.show_text
        )

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

    def request_text_render(self):
        if self.notification_manager.is_active: return
        self._cleanup_timers(['_pending_render_unsub'])
        self._pending_render_unsub = async_call_later(self.hass, 0.2, self._execute_text_render)

    async def _execute_text_render(self, now=None):
        self._pending_render_unsub = None
        if self.notification_manager.is_active: return
        await self._render_and_send_text_layers()

    async def _render_and_send_text_layers(self):
        if not self.is_art_visible or self.notification_manager.is_active: return
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
            
        # Hide progress bar if OSD is active to keep it clean
        if getattr(self.media_data, 'show_progress_bar', False) and not self.osd_mode:
            pb = await self.progress_manager.get_payload_item(self.media_data)
            if pb: items.extend(pb)
            
        # CLEAR UNUSED IDS: Ensure any text IDs from previous renders (like Volume Bar) are wiped from Pixoo memory
        used_ids = {item.get("TextId") for item in items if "TextId" in item}
        for i in range(1, 22):
            if i not in used_ids:
                items.append({
                    "TextId": i, "type": 22, "x": 0, "y": 64, "dir": 0, "font": 2, 
                    "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 1, 
                    "TextString": "", "color": "#000000"
                })

        hsh = hash(json.dumps(items, sort_keys=True))
        if hsh != self.last_text_payload_hash:
            await self.pixoo_device.send_command({"Command": "Draw/SendHttpItemList", "ItemList": items})
            self.last_text_payload_hash = hsh

    async def _calculate_and_schedule_next(self):
        if self.notification_manager.is_active or not self.lyrics_active_mode: return
        self.scheduler_generation_id += 1
        gen_id = self.scheduler_generation_id
        
        pos = self.media_data.media_position
        if self.media_data.media_position_updated_at:
            pos += (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
        
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
                
        if not layout:
            if not self.cached_static_items:
                 self.cached_static_items = await self._build_text_items_list(
                     getattr(self.media_data, 'lyrics_font_color', "#FFFFFF"), 
                     getattr(self.media_data, 'background_color', "#000000"), 
                     scope="static"
                 )
            self.current_lyrics_items.extend(self.cached_static_items)
        else:
            for i in range(1, 6):
                self.current_lyrics_items.append({
                    "TextId": i, "type": 22, "x": 0, "y": 0, 
                    "dir": 0, "font": 2, "TextWidth": 64, 
                    "Textheight": 12, "speed": 0, "align": 2, 
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

        pos = self.media_data.media_position
        if self.media_data.media_position_updated_at:
            pos += (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
            
        dur = self.media_data.media_duration
        is_slider = getattr(self.config, 'spotify_slide', False)
        prefetch_offset = 30.0 if is_slider else 20.0
        
        delay = (dur - pos) - prefetch_offset

        if delay > 0:
            self._prefetch_timer_unsub = async_call_later(self.hass, delay, self._execute_prefetch)
        elif delay > -prefetch_offset:
            self.hass.async_create_task(self._execute_prefetch_task())

    async def _execute_prefetch(self, now=None):
        self._prefetch_timer_unsub = None
        await self._execute_prefetch_task()

    async def _execute_prefetch_task(self):
        self.prefetch_status = "Querying Next Song..."
        self._update_prefetch_sensor_state()
        
        next_info = await self._get_next_song_info()
        if next_info:
            artist, title, album, url = next_info
            if artist and title:
                self.prefetch_next_artist = artist
                self.prefetch_next_title = title
                self.prefetch_status = "Downloading Art..."
                self._update_prefetch_sensor_state()
                
                dummy_media = MediaData(self.hass, self.config, self.image_processor, self.websession)
                dummy_media.artist = artist
                dummy_media.title = title
                dummy_media.album = album
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
            self._update_prefetch_sensor_state()

    async def _run_prefetch_and_update_status(self, url: str, dummy_media: MediaData):
        try:
            await self.fallback_service.prefetch_next_track(url, dummy_media)
            self.prefetch_status = "Ready in RAM"
            self._update_prefetch_sensor_state()
            
            if getattr(self.config, 'spotify_slide', False) and not getattr(dummy_media, 'radio_logo', False):
                pos = self.media_data.media_position
                if self.media_data.media_position_updated_at:
                    pos += (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
                dur = self.media_data.media_duration
                
                frames = getattr(dummy_media, 'slider_frames', 0)
                early_offset = max(2.0, float(frames)) if frames > 0 else 5.0
                
                time_to_early_send = (dur - pos) - early_offset
                
                if time_to_early_send > 0:
                    self._cleanup_timers(['_early_send_timer_unsub'])
                        
                    async def _early_send_cb(now):
                        self._early_send_timer_unsub = None
                        await self._do_early_slider_send(dummy_media)
                        
                    self._early_send_timer_unsub = async_call_later(self.hass, time_to_early_send, _early_send_cb)
                elif time_to_early_send > -early_offset:
                    self.hass.async_create_task(self._do_early_slider_send(dummy_media))
                    
        except asyncio.CancelledError:
            self.prefetch_status = "Cancelled"
            self._update_prefetch_sensor_state()
        except Exception as e:
            self.prefetch_status = f"Failed: {e}"
            self._update_prefetch_sensor_state()

    async def _do_early_slider_send(self, dummy_media: MediaData):
        if not dummy_media: return
        self.prefetch_status = "Sending Slider Early..."
        self._update_prefetch_sensor_state()
        
        try:
            if getattr(self.config, 'special_mode_spotify_slider', False): 
                await self.spotify_service.spotify_album_art_animation(self.pixoo_device, dummy_media, self.select_index)
            else: 
                await self.spotify_service.spotify_albums_slide(self.pixoo_device, dummy_media, self.select_index)
                
            if getattr(dummy_media, 'spotify_slide_pass', False):
                self._early_slider_sent_for = f"{dummy_media.artist}_{dummy_media.title}".strip().lower()
                self.prefetch_status = "Slider Sent Early"
            else:
                self.prefetch_status = "Early Slider Failed"
        except Exception as e:
            self.prefetch_status = f"Early Slider Error: {e}"
            
        self._update_prefetch_sensor_state()

    async def _get_next_song_info(self) -> Optional[Tuple[str, str, str, str]]:
        state = self.hass.states.get(self.media_player)
        if not state: return None
        
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
                _LOGGER.debug(f"Failed to fetch Sonos queue: {e}")

        if isinstance(queue, list) and isinstance(queue_pos, int):
            next_pos = queue_pos 
            
            if 0 <= next_pos < len(queue):
                next_item = queue[next_pos]
                if isinstance(next_item, dict):
                    artist = next_item.get('artist') or next_item.get('media_artist')
                    title = next_item.get('title') or next_item.get('name') or next_item.get('media_title')
                    album = next_item.get('album') or next_item.get('media_album_name') or ""
                    url = next_item.get('image') or next_item.get('entity_picture')
                    
                    if artist and title:
                        cleaned_title = self.media_data.clean_title(title) if self.config.clean_title else title
                        return str(artist), str(cleaned_title), str(album), url
        return None

    async def force_update(self):
        self._apply_logic_matrix()
        master_control = self.ui_state.get("master_control", True)
        if not master_control:
            await self._send_off_command()
            return
            
        state = self.hass.states.get(self.media_player)
        if state and state.state in ["playing", "on"]:
            await self.media_data.update()
            self._fetch_external_temperature()
            
            song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
            if song_key and song_key == self._active_song_key and self.is_art_visible:
                return

            self.media_data.track_changed = True
            self._cleanup_timers(['_prefetch_timer_unsub', '_early_send_timer_unsub'])
            self._cancel_tasks(['current_task'])
            self.current_task = self.hass.async_create_task(self._process_and_send())
        else:
            await self._send_off_command()

    async def safe_state_change_callback(self, event):
        self._cancel_tasks(['debounce_task'])
        self.debounce_task = asyncio.create_task(self._run_debounced_callback(event))

    async def _run_debounced_callback(self, event):
        try:
            await asyncio.sleep(0.5)
            await self._handle_media_change(event)
        except asyncio.CancelledError: 
            pass

    async def _execute_pause_timeout(self, now=None):
        self._pause_timeout_unsub = None
        if self.osd_mode == "Pause":
            await self._send_off_command()

    async def _handle_media_change(self, event):
        if self.notification_manager.is_active: return
        master_control = self.ui_state.get("master_control", True)
        if not master_control: return
        
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not new_state: return
        
        osd_enabled = getattr(self.config, 'osd_overlay', "Enabled") == "Enabled"

        # Handle Pause State with OSD overlay
        if new_state.state == "paused":
            if osd_enabled:
                self._stop_lyrics_scheduler()
                self.osd_mode = "Pause"
                self.request_text_render()
                
                pause_timeout_str = getattr(self.config, 'pause_timeout', "15s")
                self._cleanup_timers(['_pause_timeout_unsub', '_volume_osd_timer_unsub'])
                
                if pause_timeout_str != "Never":
                    timeout_val = int(pause_timeout_str.replace("s", ""))
                    self._pause_timeout_unsub = async_call_later(self.hass, timeout_val, self._execute_pause_timeout)
                return
            else:
                await self._send_off_command()
                self._stop_lyrics_scheduler()
                return

        # Restore from Pause
        if old_state and old_state.state == "paused" and new_state.state in ["playing", "on"]:
            self._cleanup_timers(['_pause_timeout_unsub'])
            self.osd_mode = None
            self.request_text_render()

        if new_state.state not in ["playing", "on"]:
            await self._send_off_command()
            self._stop_lyrics_scheduler()
            return

        # Handle Volume OSD while playing
        is_volume_change = False
        if old_state and old_state.state in ["playing", "on"]:
            new_vol = new_state.attributes.get("volume_level")
            old_vol = old_state.attributes.get("volume_level")
            if new_vol is not None and old_vol is not None and new_vol != old_vol:
                is_volume_change = True
                self.last_volume_level = new_vol

        if is_volume_change and osd_enabled:
            self.osd_mode = "Volume"
            self.request_text_render()
            
            vol_duration_str = getattr(self.config, 'volume_osd_duration', "2s")
            vol_duration = int(vol_duration_str.replace("s", "")) if "s" in vol_duration_str else 2
            
            self._cleanup_timers(['_volume_osd_timer_unsub'])
            
            def _clear_vol_osd(now):
                if self.osd_mode == "Volume":
                    self.osd_mode = None
                    self.request_text_render()
                    
            self._volume_osd_timer_unsub = async_call_later(self.hass, vol_duration, _clear_vol_osd)
            
            old_title = old_state.attributes.get("media_title")
            new_title = new_state.attributes.get("media_title")
            if old_title == new_title:
                self.progress_timer_gen_id += 1
                await self._update_progress_bar_loop()
                return 

        # Standard Track Update processing
        await self.media_data.update()
        self._fetch_external_temperature()

        current_song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
        if current_song_key and current_song_key == self._active_song_key and self.is_art_visible:
            self.progress_timer_gen_id += 1
            await self._update_progress_bar_loop()
            if self.lyrics_active_mode:
                await self._calculate_and_schedule_next()
            self._schedule_prefetch()
            return

        is_new_track = True
        if old_state and old_state.state in ["playing", "on"]:
            old_title = old_state.attributes.get("media_title")
            old_artist = old_state.attributes.get("media_artist")
            new_title = new_state.attributes.get("media_title")
            new_artist = new_state.attributes.get("media_artist")
            
            if old_title == new_title and old_artist == new_artist:
                is_new_track = False

        if is_new_track or self.media_data.track_changed:
            self.prefetch_status = "Idle"
            self.prefetch_next_artist = None
            self.prefetch_next_title = None
            
            self._cleanup_timers(['_prefetch_timer_unsub', '_early_send_timer_unsub'])
            self._cancel_tasks(['_prefetch_task', 'current_task'])
            
            self.current_task = self.hass.async_create_task(self._process_and_send())
        else:
            self.progress_timer_gen_id += 1
            await self._update_progress_bar_loop()
            if self.lyrics_active_mode:
                await self._calculate_and_schedule_next()
            self._schedule_prefetch()

    async def _process_and_send(self):
        async with self._image_lock:
            try:
                curr = await self.pixoo_device.get_current_channel_index()
                if curr != 4: 
                    self.select_index = self.last_valid_index = curr
                else: 
                    self.select_index = getattr(self, 'last_valid_index', 0)

                current_song_key = f"{self.media_data.artist}_{self.media_data.title}".strip().lower()
                if current_song_key and current_song_key == self._active_song_key and self.is_art_visible:
                    _LOGGER.debug("Artwork already active on screen for '%s', skipping", current_song_key)
                    return

                if getattr(self.media_data, 'playing_tv', False):
                    await self.control_light('off')
                    await self.control_wled_light('off')

                    if not getattr(self.config, 'tv_mode', False) or self.media_data.picture == "TV_IS_ON":
                        target_channel = self.select_index if self.select_index != 4 else 0
                        
                        if getattr(self.config, 'full_control', False):
                            await self.pixoo_device.send_command({
                                "Command": "Draw/CommandList",
                                "CommandList": [
                                    {"Command": "Draw/ClearHttpText"},
                                    {"Command": "Draw/ResetHttpGifId"},
                                    {"Command": "Channel/OnOffScreen", "OnOff": 0}
                                ]
                            })
                        else:
                            await self.pixoo_device.send_command({
                                "Command": "Draw/CommandList",
                                "CommandList": [
                                    {"Command": "Draw/ClearHttpText"},
                                    {"Command": "Draw/ResetHttpGifId"},
                                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                                    {"Command": "Channel/SetIndex", "SelectIndex": target_channel}
                                ]
                            })

                        self.is_art_visible = False
                        self._active_song_key = None
                        if self.sensor:
                            self.sensor.update_state("TV", {
                                "artist": "TV",
                                "media_title": "TV",
                                "active_mode": "TV",
                                "image_source": "Internal",
                                "pixoo64_channel": target_channel if not getattr(self.config, 'full_control', False) else "Off"
                            })
                        return

                start_time = time.perf_counter()
                processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
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
                is_night = sun_state and sun_state.state == "below_horizon"

                if not getattr(self.media_data, 'playing_tv', False):
                    await self.control_light('on', bg_color_rgb, is_night)
                    await self.control_wled_light('on', [color1, color2, color3], is_night)
                
                early_slider_match = False
                if getattr(self.config, 'spotify_slide', False) and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False):
                    if self._early_slider_sent_for == current_song_key:
                        early_slider_match = True
                        self.media_data.spotify_slide_pass = True
                        _LOGGER.debug("Slider was already sent early for %s", current_song_key)

                self._early_slider_sent_for = None
                duration = time.perf_counter() - start_time
                
                sensor_attrs = {
                    "artist": self.media_data.artist,
                    "media_title": self.media_data.title,
                    "image_source": self.media_data.pic_source,
                    "image_url": self.media_data.pic_url,
                    "active_mode": self.ui_state.get("display_mode", "Standard"),
                    "font_color": font_color,
                    "background_color": bg_color_str,
                    "background_color_rgb": processed_data.get('background_color_rgb'),
                    "brightness_lower_part": processed_data.get('brightness_lower_part'),
                    "images_in_cache": len(self.image_processor.image_cache),
                    "process_duration": f"{duration:.2f}s",
                    "progress_bar_active": getattr(self.media_data, 'show_progress_bar', False),
                    "lyrics_found": len(self.media_data.lyrics) > 0,
                    "lyrics_sync_offset": getattr(self.config, 'lyrics_sync', 0.0),
                    "lyrics_count": len(self.media_data.lyrics),
                    "pixoo64_channel": self.select_index,
                    "prefetch_status": self.prefetch_status,
                    "prefetch_next_artist": self.prefetch_next_artist,
                    "prefetch_next_title": self.prefetch_next_title,
                }

                if self.sensor: 
                    self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)

                success = True
                if not early_slider_match:
                    image_cmd = {
                        "Command": "Draw/CommandList", 
                        "CommandList": [
                            {"Command": "Channel/SetIndex", "SelectIndex": 4},
                            {"Command": "Channel/OnOffScreen", "OnOff": 1}, 
                            {"Command": "Draw/ResetHttpGifId"}, 
                            {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 10000, "PicData": base64_image}
                        ]
                    }
                    success = await self.pixoo_device.send_command(image_cmd)
                
                if success:
                    self.is_art_visible = True
                    self._active_song_key = current_song_key 
                    self.last_text_payload_hash = None 
                    self.last_progress_str = "" 
                    
                    self.media_data.lyrics_font_color = font_color
                    self.media_data.background_color = bg_color_str
                    
                    self.lyrics_active_mode = getattr(self.config, 'show_lyrics', False) and len(self.media_data.lyrics) > 0 and not getattr(self.media_data, 'playing_tv', False)
                    
                    self.cached_static_items = await self._build_text_items_list(font_color, bg_color_str, scope="static")
                    
                    self.progress_timer_gen_id += 1
                    
                    if self.lyrics_active_mode:
                        await self._calculate_and_schedule_next()
                    else:
                        self._stop_lyrics_scheduler()
                        self.request_text_render()
                        
                    await self._update_progress_bar_loop()
                    self._schedule_prefetch()

                    if getattr(self.config, 'spotify_slide', False) and not early_slider_match and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False):
                        self.spotify_service.spotify_data = await self.spotify_service.get_spotify_json(self.media_data.artist, self.media_data.title)
                        if self.spotify_service.spotify_data:
                            if getattr(self.config, 'special_mode_spotify_slider', False): 
                                await self.spotify_service.spotify_album_art_animation(self.pixoo_device, self.media_data, self.select_index)
                            else: 
                                await self.spotify_service.spotify_albums_slide(self.pixoo_device, self.media_data, self.select_index)
                            
                            if getattr(self.media_data, 'spotify_slide_pass', False):
                                self.request_text_render()

            except asyncio.CancelledError: 
                pass
            except Exception as e: 
                _LOGGER.error("Execution error: %s", e)

    async def _update_progress_bar_loop(self):
        if self.notification_manager.is_active: return
        
        state = self.hass.states.get(self.media_player)
        if not state or state.state not in ["playing", "on"]: return
        
        if not getattr(self.config, 'progress_bar_enabled', False): 
            self.request_text_render()
            return
            
        pos = self.media_data.media_position
        if self.media_data.media_position_updated_at:
            pos += (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
        
        bar_str, delay = self.progress_manager.calculate(pos, self.media_data.media_duration)
        
        if self.is_art_visible:
            if bar_str != self.last_progress_str or self.last_text_payload_hash is None:
                self.last_progress_str = bar_str
                self.request_text_render()
        
        if delay is not None:
            gen_id = self.progress_timer_gen_id
            async def _pb_timer(now):
                if self.progress_timer_gen_id == gen_id: await self._update_progress_bar_loop()
            
            self._cleanup_timers(['_progress_timer_unsub'])
            self._progress_timer_unsub = async_call_later(self.hass, delay, _pb_timer)

    def get_opposite_color(self, hex_color):
        try:
            hex_color = hex_color.lstrip('#')
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            inverted_rgb = tuple(255 - value for value in rgb)
            return '#{:02x}{:02x}{:02x}'.format(*inverted_rgb)
        except Exception:
            return "#FFFFFF"

    async def _build_text_items_list(self, font_color, bg_color, scope="all"):
        text_items = []
        
        y_info = 3 if getattr(self.config, 'overlay_top', True) else 56
        align_mode = getattr(self.config, 'overlay_align', 'Clock Right, Temp Left')
        show_clk = getattr(self.config, 'show_clock', True)
        show_tmp = getattr(self.config, 'temperature', False)
        
        if align_mode == "Clock Left, Temp Right":
            x_c, x_t = 3, 47
        elif align_mode == "Centered":
            if show_clk and not show_tmp: x_c, x_t = 22, 3
            elif show_tmp and not show_clk: x_c, x_t = 44, 24
            else: x_c, x_t = 36, 3
        else: 
            x_c, x_t = 44, 3

        # Render OSD items instead of track/lyrics text if an OSD mode is active
        if self.osd_mode:
            if self.osd_mode == "Pause":
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 24, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": "PAUSED", "color": font_color})
            elif self.osd_mode == "Volume":
                pct = int((self.last_volume_level or 0) * 100)
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 20, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": f"VOL {pct}%", "color": font_color})
                
                bars = int((pct / 100) * 10)
                bar_str = "=" * bars + "-" * (10 - bars)
                text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 32, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": bar_str, "color": font_color})
                
            # Keep clock & temp visible during OSD
            if show_clk:
                text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
            if show_tmp:
                t_val = getattr(self.media_data, 'temperature', None)
                t_type = 22 if t_val else 17
                t_str = str(t_val) if t_type == 22 else ""
                text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": t_str})
                
            return text_items

        y_text = 0 if getattr(self.config, 'top_text', False) else 48
        txt = f"{self.media_data.artist} - {self.media_data.title}"
        if len(txt) > 14: txt += "        "
        rtl = 1 if has_bidi(txt) else 0
        is_burned = getattr(self.config, 'burned', False)
        
        if getattr(self.config, 'special_mode', False):
            text_items.append({"TextId": 1, "type": 14, "x": 3, "y": 1, "dir": 0, "font": 18, "TextWidth": 33, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})
            text_items.append({"TextId": 2, "type": 5, "x": 1, "y": 1, "dir": 0, "font": 18, "TextWidth": 63, "Textheight": 6, "speed": 100, "align": 2, "color": font_color})
            
            t_val = getattr(self.media_data, 'temperature', None)
            t_type = 22 if t_val else 17
            if t_type == 22:
                text_items.append({"TextId": 3, "type": t_type, "x": 48, "y": 1, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": str(t_val)})
            else:
                text_items.append({"TextId": 3, "type": t_type, "x": 48, "y": 1, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})

            show_http_text = getattr(self.config, 'show_text', True) and not getattr(self.media_data, 'playing_tv', False) and not is_burned
            
            if show_http_text or (getattr(self.media_data, 'spotify_slide_pass', False) and getattr(self.config, 'spotify_slide', False)):
                a_rtl = 1 if has_bidi(self.media_data.artist) else 0
                text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 42, "dir": a_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(self.media_data.artist) if a_rtl else self.media_data.artist, "color": font_color})
                t_rtl = 1 if has_bidi(self.media_data.title) else 0
                text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 52, "dir": t_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(self.media_data.title) if t_rtl else self.media_data.title, "color": font_color})

        else:
            if not getattr(self, 'lyrics_active_mode', False):
                if getattr(self.config, 'show_text', True) and not getattr(self.media_data, 'playing_tv', False) and not is_burned and not getattr(self.config, 'spotify_slide', False):
                    text_items.append({"TextId": 4, "type": 22, "x": 0, "y": y_text, "dir": rtl, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(txt) if rtl else txt, "color": font_color})
                                
                if show_clk:
                    text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
                
                if show_tmp:
                    t_val = getattr(self.media_data, 'temperature', None)
                    t_type = 22 if t_val else 17
                    if t_type == 22:
                        text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": str(t_val)})
                    else:
                        text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})
                            
        return text_items

    def _stop_lyrics_scheduler(self):
        self.lyrics_active_mode = False
        self.scheduler_generation_id += 1
        self.current_lyrics_items = []

    async def async_handle_notification_service(self, call):
        message = call.data.get("message")
        if not message:
            return

        previous_channel = 0
        was_screen_on = True
        try:
            previous_channel = await self.pixoo_device.get_current_channel_index()
            was_screen_on = await self.pixoo_device.get_screen_on_state()
        except Exception as e:
            _LOGGER.debug("Could not get channel/screen state before notification: %s", e)

        media_state = self.hass.states.get(self.media_player)
        is_media_playing = media_state and media_state.state in ["playing", "on"]
        if not is_media_playing and getattr(self.config, 'full_control', False) and not self.is_art_visible:
            was_screen_on = False

        self.notification_manager.is_active = True
        self._stop_lyrics_scheduler()
        
        self._cleanup_timers()
        self._cancel_tasks()

        event_data = {
            "message": message,
            "type": call.data.get("type", "text"),
            "duration": call.data.get("duration", 5),
            "color": call.data.get("color"),
            "play_buzzer": call.data.get("play_buzzer", False),
            "buzzer_active": call.data.get("buzzer_active", 500),
            "buzzer_off": call.data.get("buzzer_off", 500),
            "buzzer_total": call.data.get("buzzer_total", 3000),
        }

        await self.notification_manager.display(event_data)

        rechecked_state = self.hass.states.get(self.media_player)
        if rechecked_state and rechecked_state.state in ["playing", "on"]:
            self.is_art_visible = False
            self._active_song_key = None
            await self.force_update()
        else:
            if getattr(self.config, 'full_control', False) and not was_screen_on:
                await self.pixoo_device.send_command({
                    "Command": "Draw/CommandList",
                    "CommandList": [
                        {"Command": "Draw/ClearHttpText"},
                        {"Command": "Draw/ResetHttpGifId"},
                        {"Command": "Channel/OnOffScreen", "OnOff": 0}
                    ]
                })
                self.is_art_visible = False
                self._active_song_key = None
            else:
                await self.pixoo_device.send_command({
                    "Command": "Draw/CommandList",
                    "CommandList": [
                        {"Command": "Draw/ClearHttpText"},
                        {"Command": "Draw/ResetHttpGifId"},
                        {"Command": "Channel/OnOffScreen", "OnOff": 1},
                        {"Command": "Channel/SetIndex", "SelectIndex": previous_channel}
                    ]
                })

    async def control_light(self, action: str, rgb_color: tuple = None, is_night: bool = True):
        if not is_night and getattr(self.config, 'only_at_night', False): return
            
        light_entities = getattr(self.config, 'light_entity', [])
        if not light_entities:
            return
            
        entities = light_entities if isinstance(light_entities, list) else [light_entities]
        
        for entity_id in entities:
            service_data = {"entity_id": entity_id}
            if action == 'on' and rgb_color:
                service_data["rgb_color"] = rgb_color
                service_data["transition"] = 1
                
            try:
                await self.hass.services.async_call("light", f"turn_{action}", service_data, blocking=False)
            except Exception as e:
                _LOGGER.error(f"Failed to control light {entity_id}: {e}")

    async def control_wled_light(self, action: str, colors: list = None, is_night: bool = True):
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
                _LOGGER.debug(f"Failed to control WLED at {wled_ip}: {e}")