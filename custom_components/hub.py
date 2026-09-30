"""The Core Hub managing UI states and delegating to pixoo_services."""
import asyncio
import logging
import time
import json
from datetime import datetime, timezone
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
        self.current_task = None
        self.debounce_task = None
        
        # Initialize Core Services
        self.websession = async_get_clientsession(hass)
        self.pixoo_device = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.hass, self.config, self.websession)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.media_data = MediaData(self.hass, self.config, self.image_processor, self.websession)
        self.fallback_service = FallbackService(self.config, self.image_processor, self.websession, self.spotify_service, self.pixoo_device)
        self.progress_manager = ProgressBarManager(self.config, self.hass)
        self.notification_manager = NotificationManager(self.config, self.pixoo_device, self.image_processor, self.hass)

        # State Tracking
        self.is_art_visible = False
        self.lyrics_active_mode = False
        self.last_text_payload_hash = None
        self.cached_static_items = []
        self.current_lyrics_items = []
        self.progress_timer_gen_id = 0
        self.scheduler_generation_id = 0
        self.last_progress_str = ""
        self._progress_timer_unsub = None
        self._lyrics_timer_unsub = None
        self._pending_render_unsub = None

    def set_sensor(self, sensor):
        self.sensor = sensor

    async def initialize(self):
        """Set up initial state and listeners."""
        try:
            curr = await self.pixoo_device.get_current_channel_index()
            if curr != 4: 
                self.select_index = self.last_valid_index = curr
            else: 
                self.select_index = getattr(self, 'last_valid_index', 0)
        except Exception:
            self.select_index = 0
            self.last_valid_index = 0

        self._unsub_listeners.append(
            async_track_state_change_event(self.hass, [self.media_player], self.safe_state_change_callback)
        )
        self._apply_logic_matrix()
        
        await asyncio.sleep(2)
        self._apply_logic_matrix()
        await self.force_update()

    async def terminate(self):
        """Clean up resources on shutdown."""
        for unsub in self._unsub_listeners: unsub()
        if self.current_task and not self.current_task.done(): self.current_task.cancel()
        if self.debounce_task and not self.debounce_task.done(): self.debounce_task.cancel()
        self.image_processor.shutdown()

    async def async_ui_update(self, key: str, value):
        """Called by switch/select entities when user changes a setting."""
        self.ui_state[key] = value
        self._apply_logic_matrix()
        
        self.cached_static_items = []
        self.last_text_payload_hash = None
        
        if key in ["crop_mode", "text_background", "text_position", "display_mode", "overlay_position", "overlay_align"]:
            self.image_processor.image_cache.clear()
            
        await self.force_update()

    def _apply_logic_matrix(self):
        """Translate UI states into internal Config variables."""
        # Switches
        self.config.full_control = self.ui_state.get("full_control", False)
        self.config.progress_bar_enabled = self.ui_state.get("progress_bar", True)
        self.config.force_ai = self.ui_state.get("force_ai", False)
        self.config.text_bg = self.ui_state.get("text_background", True)

        # Numbers
        self.config.lyrics_sync = float(self.ui_state.get("lyrics_sync", 0.0))

        # Crop Mode
        crop_mode = self.ui_state.get("crop_mode", "Default")
        self.config.crop_borders = crop_mode in ["Crop", "Extra Crop"]
        self.config.crop_extra = (crop_mode == "Extra Crop")

        # Text and Overlay Position Logic
        text_position = self.ui_state.get("text_position", "Bottom")
        self.config.show_text = (text_position != "Hidden")
        top_text = (text_position == "Top")

        overlay_pos = self.ui_state.get("overlay_position", "Auto (Opposite of Text)")
        
        if overlay_pos == "Top":
            self.config.overlay_top = True
            # Collision Avoidance: If both set to Top, move text to bottom
            if self.config.show_text and top_text:
                top_text = False
        elif overlay_pos == "Bottom":
            self.config.overlay_top = False
            # Collision Avoidance: If both set to Bottom, move text to top
            if self.config.show_text and not top_text:
                top_text = True
        else: # Auto (Opposite of Text)
            if self.config.show_text:
                self.config.overlay_top = not top_text
            else:
                self.config.overlay_top = True # Default when text is hidden

        self.config.top_text = top_text

        # Overlay Info (Content & Alignment)
        overlay_info = self.ui_state.get("overlay_info", "Clock")
        self.config.show_clock = "Clock" in overlay_info
        self.config.temperature = "Temp" in overlay_info
        self.config.overlay_align = self.ui_state.get("overlay_align", "Clock Right, Temp Left")

        # Display Mode
        display_mode = self.ui_state.get("display_mode", "Standard")
        m = display_mode.lower()
        
        self.config.show_lyrics = (m == "lyrics")
        self.config.burned = (m == "burned")
        self.config.special_mode = ("special" in m)
        self.config.spotify_slide = ("slider" in m)

        self.config.special_mode_spotify_slider = bool(
            self.config.spotify_slide and self.config.special_mode and self.config.show_text
        )

        self.cached_static_items = []
        self.last_text_payload_hash = None

    def _fetch_external_temperature(self):
        """Fetch temperature from HA entity if configured."""
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
        if self._pending_render_unsub:
            self._pending_render_unsub()
        self._pending_render_unsub = async_call_later(self.hass, 0.2, self._execute_text_render)

    async def _execute_text_render(self, now=None):
        self._pending_render_unsub = None
        await self._render_and_send_text_layers()

    async def _render_and_send_text_layers(self):
        """Builds and sends the text and overlay layers over the current image."""
        if not self.is_art_visible: return
        items = []
        
        if self.lyrics_active_mode and self.current_lyrics_items:
            items.extend(self.current_lyrics_items)
        else:
            if not self.cached_static_items:
                 self.cached_static_items = await self._build_text_items_list(
                     getattr(self.media_data, 'lyrics_font_color', "#FFFFFF"), 
                     getattr(self.media_data, 'background_color', "#000000"), 
                     scope="static"
                 )
            items.extend(self.cached_static_items)
            
        if getattr(self.media_data, 'show_progress_bar', False):
            pb = await self.progress_manager.get_payload_item(self.media_data)
            if pb: items.extend(pb)
            
        hsh = hash(json.dumps(items, sort_keys=True))
        if hsh != self.last_text_payload_hash:
            await self.pixoo_device.send_command({"Command": "Draw/SendHttpItemList", "ItemList": items})
            self.last_text_payload_hash = hsh

    async def _calculate_and_schedule_next(self):
        """Lyric sync scheduling engine using HA async_call_later."""
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
        
        if self._lyrics_timer_unsub:
            self._lyrics_timer_unsub()
        self._lyrics_timer_unsub = async_call_later(self.hass, safe_delay, _timer)

    async def force_update(self):
        """Force a manual refresh of the display based on current states."""
        self._apply_logic_matrix()
        master_control = self.ui_state.get("master_control", True)
        if not master_control:
            await self._send_off_command()
            return
            
        state = self.hass.states.get(self.media_player)
        if state and state.state in ["playing", "on"]:
            await self.media_data.update()
            self._fetch_external_temperature()
            self.media_data.track_changed = True
            if self.current_task: self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())
        else:
            await self._send_off_command()

    async def safe_state_change_callback(self, event):
        """Debounced callback for media player state changes."""
        if self.debounce_task and not self.debounce_task.done(): 
            self.debounce_task.cancel()
            
        self.debounce_task = asyncio.create_task(self._run_debounced_callback(event))

    async def _run_debounced_callback(self, event):
        try:
            await asyncio.sleep(0.5)
            await self._handle_media_change(event)
        except asyncio.CancelledError: 
            pass

    async def _handle_media_change(self, event):
        master_control = self.ui_state.get("master_control", True)
        if not master_control: return
        
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not new_state: return

        if new_state.state not in ["playing", "on"]:
            await self._send_off_command()
            self._stop_lyrics_scheduler()
            return

        is_new_track = True
        if old_state and old_state.state in ["playing", "on"]:
            old_title = old_state.attributes.get("media_title")
            old_artist = old_state.attributes.get("media_artist")
            new_title = new_state.attributes.get("media_title")
            new_artist = new_state.attributes.get("media_artist")
            
            if old_title == new_title and old_artist == new_artist:
                is_new_track = False

        await self.media_data.update()
        self._fetch_external_temperature()
        
        if is_new_track or self.media_data.track_changed:
            if self.current_task and not self.current_task.done(): 
                self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())
            
        else:
            self.progress_timer_gen_id += 1
            await self._update_progress_bar_loop()
            
            if self.lyrics_active_mode:
                await self._calculate_and_schedule_next()

    async def _process_and_send(self):
        try:
            curr = await self.pixoo_device.get_current_channel_index()
            if curr != 4: 
                self.select_index = self.last_valid_index = curr
            else: 
                self.select_index = getattr(self, 'last_valid_index', 0)

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
            
            took_over = False
            self.media_data.spotify_slide_pass = False 
            
            if getattr(self.config, 'spotify_slide', False) and not getattr(self.media_data, 'radio_logo', False) and not getattr(self.media_data, 'playing_tv', False):
                self.spotify_service.spotify_data = await self.spotify_service.get_spotify_json(self.media_data.artist, self.media_data.title)
                if self.spotify_service.spotify_data:
                    if getattr(self.config, 'special_mode_spotify_slider', False): 
                        await self.spotify_service.spotify_album_art_animation(self.pixoo_device, self.media_data, self.select_index)
                    else: 
                        await self.spotify_service.spotify_albums_slide(self.pixoo_device, self.media_data, self.select_index)
                    
                    if getattr(self.media_data, 'spotify_slide_pass', False):
                        took_over = True

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
            }

            if self.sensor: 
                self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)

            success = True
            if not took_over:
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
                self.last_text_payload_hash = None 
                self.last_progress_str = "" 
                
                self.media_data.lyrics_font_color = font_color
                self.media_data.background_color = bg_color_str
                
                self.lyrics_active_mode = getattr(self.config, 'show_lyrics', False) and len(self.media_data.lyrics) > 0
                
                self.cached_static_items = await self._build_text_items_list(font_color, bg_color_str, scope="static")
                
                self.progress_timer_gen_id += 1
                
                if self.lyrics_active_mode:
                    await self._calculate_and_schedule_next()
                else:
                    self._stop_lyrics_scheduler()
                    if not took_over or getattr(self.config, 'special_mode_spotify_slider', False):
                        self.request_text_render()
                    
                await self._update_progress_bar_loop()
                
        except asyncio.CancelledError: pass
        except Exception as e: _LOGGER.error("Execution error: %s", e)

    async def _update_progress_bar_loop(self):
        """Progress bar scheduling engine."""
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
            
            if self._progress_timer_unsub:
                self._progress_timer_unsub()
            self._progress_timer_unsub = async_call_later(self.hass, delay, _pb_timer)

    def get_opposite_color(self, hex_color):
        """Helper to get contrasting color for Special Mode."""
        try:
            hex_color = hex_color.lstrip('#')
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            inverted_rgb = tuple(255 - value for value in rgb)
            return '#{:02x}{:02x}{:02x}'.format(*inverted_rgb)
        except Exception:
            return "#FFFFFF"

    async def _build_text_items_list(self, font_color, bg_color, scope="all"):
        text_items = []
        
        # Determine text vertical coordinates
        y_text = 0 if getattr(self.config, 'top_text', False) else 48
        
        # Determine overlay (clock/temp) vertical coordinates
        y_info = 3 if getattr(self.config, 'overlay_top', True) else 56
        
        align_mode = getattr(self.config, 'overlay_align', 'Clock Right, Temp Left')
        show_clk = getattr(self.config, 'show_clock', True)
        show_tmp = getattr(self.config, 'temperature', False)
        
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

        txt = f"{self.media_data.artist} - {self.media_data.title}"
        if len(txt) > 14: txt += "        "
        rtl = 1 if has_bidi(txt) else 0
        
        is_burned = getattr(self.config, 'burned', False)
        
        if getattr(self.config, 'special_mode', False):
            text_items.append({"TextId": 1, "type": 14, "x": 3, "y": 1, "dir": 0, "font": 18, "TextWidth": 33, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})
            text_items.append({"TextId": 2, "type": 5, "x": 1, "y": 1, "dir": 0, "font": 18, "TextWidth": 63, "Textheight": 6, "speed": 100, "align": 2, "color": font_color})
            
            t_val = getattr(self.media_data, 'temperature', None)
            t_type = 22 if t_val else 17
            text_items.append({"TextId": 3, "type": t_type, "x": 48, "y": 1, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": str(t_val) if t_val else ""})
            
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
                else:
                    text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 0, "dir": 0, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 2, "TextString": "", "color": "#000000"})
                
                if show_clk:
                    text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
                else:
                    text_items.append({"TextId": 2, "type": 22, "x": 0, "y": 0, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 0, "align": 1, "color": "#000000", "TextString": ""})

                if show_tmp:
                    t_val = getattr(self.media_data, 'temperature', None)
                    t_type = 22 if t_val else 17
                    text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": str(t_val) if t_val else ""})
                else:
                    text_items.append({"TextId": 3, "type": 22, "x": 0, "y": 0, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 0, "align": 1, "color": "#000000", "TextString": ""})
            
        return text_items

    async def _send_off_command(self):
        """Turns off the display or restores channel based on full_control."""
        if self.sensor: 
            self.sensor.update_state("Off", {})
            
        if not self.is_art_visible: 
            return
        
        self.is_art_visible = False
        
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
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},  
                    {"Command": "Draw/ResetHttpGifId"},
                    {"Command": "Channel/OnOffScreen", "OnOff": 1},
                    {"Command": "Channel/SetIndex", "SelectIndex": self.select_index}
                ]
            })

    def _stop_lyrics_scheduler(self):
        self.lyrics_active_mode = False
        self.scheduler_generation_id += 1
        self.current_lyrics_items = []

    async def async_handle_notification_service(self, call):
        """Handle incoming notification service calls with buzzer support and smart restore."""
        message = call.data.get("message")
        if not message:
            return

        previous_channel = 0
        try:
            previous_channel = await self.pixoo_device.get_current_channel_index()
        except Exception as e:
            _LOGGER.debug("Could not get current channel before notify: %s", e)

        self._stop_lyrics_scheduler()
        if self._progress_timer_unsub:
            self._progress_timer_unsub()
            self._progress_timer_unsub = None
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
            self.current_task = None

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

        state = self.hass.states.get(self.media_player)
        if state and state.state in ["playing", "on"]:
            self.is_art_visible = False
            await self.force_update()
        else:
            await self.pixoo_device.send_command({
                "Command": "Draw/CommandList",
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},
                    {"Command": "Draw/ResetHttpGifId"},
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