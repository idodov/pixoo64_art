"""The Core Hub managing UI states and delegating to pixoo_services."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from PIL import Image
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
        self.config.args = {**entry.data, **entry.options}
        self.sensor = None
        
        self._unsub_listeners = []
        self.current_task = None
        
        self.websession = async_get_clientsession(hass)
        self.pixoo_device = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.config, self.websession)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.lyrics_provider = LyricsProvider(self.config, self.websession)
        self.media_data = MediaData(self.hass, self.config, self.image_processor, self.websession)
        self.fallback_service = FallbackService(self.config, self.image_processor, self.websession, self.spotify_service, self.pixoo_device)
        self.progress_manager = ProgressBarManager(self.config, self.hass)
        self.notification_manager = NotificationManager(self.config, self.pixoo_device, self.image_processor, self.hass)

        self.select_index = 0
        self.last_text_payload_hash = None
        self.last_progress_str = ""
        self.cached_static_items = []
        self.current_lyrics_items = []
        self.is_art_visible = False
        self.lyrics_active_mode = False
        self.scheduler_generation_id = 0
        self.progress_timer_gen_id = 0

    def set_sensor(self, sensor):
        self.sensor = sensor

    async def initialize(self):
        try:
            initial_index = await self.pixoo_device.get_current_channel_index()
            self.select_index = 0 if initial_index == 4 else initial_index
        except Exception:
            self.select_index = 0

        self._unsub_listeners.append(
            async_track_state_change_event(self.hass, [self.media_player], self._handle_media_change)
        )
        self._apply_logic_matrix()
        await self.force_update()

    async def terminate(self):
        for unsub in self._unsub_listeners: unsub()
        if self.current_task and not self.current_task.done(): self.current_task.cancel()
        self.image_processor.shutdown()

    async def async_ui_update(self, key: str, value):
        self.ui_state[key] = value
        self._apply_logic_matrix()
        await self.force_update()

    def _apply_logic_matrix(self):
        self.config.show_clock = self.ui_state.get("show_clock", True)
        self.config.temperature = self.ui_state.get("show_temperature", False)
        self.config.show_text = self.ui_state.get("show_text", True)
        self.config.text_bg = self.ui_state.get("text_background", True)
        self.config.burned = self.ui_state.get("burned_effect", False)
        self.config.progress_bar_enabled = self.ui_state.get("progress_bar", True)
        self.config.spotify_slide = self.ui_state.get("spotify_slider", False)
        
        self.config.text_position = self.ui_state.get("text_position", "Bottom")
        self.config.top_text = (self.config.text_position == "Top")
        
        info_pos = self.ui_state.get("info_position", "Opposite to Text")
        if info_pos == "Opposite to Text":
            self.config.info_position = "Bottom" if self.config.top_text else "Top"
        else:
            self.config.info_position = info_pos
            
        self.config.clock_align = self.ui_state.get("info_align", "Right")
        
        crop = self.ui_state.get("crop_mode", "Default")
        self.config.crop_borders = crop in ["Crop", "Extra Crop"]
        self.config.crop_extra = crop == "Extra Crop"
        
        self.config.ai_fallback = self.ui_state.get("ai_model", "flux")
        self.config.lyrics_sync = self.ui_state.get("lyrics_sync", 0.0)

        if self.config.spotify_slide:
            self.config.burned = False
            self.config.special_mode = True

    def _fetch_external_temperature(self):
        temp_ent = self.config.args.get("temperature_entity")
        if temp_ent:
            s = self.hass.states.get(temp_ent)
            if s and s.state not in ("unknown", "unavailable"):
                self.media_data.temperature = f"{s.state}°"

    async def _render_and_send_text_layers(self):
        """Centralized text renderer to prevent overlapping commands."""
        if not self.is_art_visible: return
        items = []
        
        # 1. Lyrics OR Static text (Clock, Temp, Artist)
        if self.lyrics_active_mode and self.current_lyrics_items:
            items.extend(self.current_lyrics_items)
        else:
            if not self.cached_static_items:
                 self.cached_static_items = await self._build_text_items_list(getattr(self.media_data, 'lyrics_font_color', "#FFFFFF"), getattr(self.media_data, 'background_color', "#000000"), scope="static")
            items.extend(self.cached_static_items)
            
        # 2. Progress Bar
        if self.config.progress_bar_enabled:
            pb = await self.progress_manager.get_payload_item(self.media_data)
            if pb: items.extend(pb)
            
        # 3. Send if layout changed
        hsh = hash(str(items))
        if hsh != self.last_text_payload_hash:
            await self.pixoo_device.send_command({"Command": "Draw/SendHttpItemList", "ItemList": items})
            self.last_text_payload_hash = hsh

    async def force_update(self):
        if not self.ui_state.get("master", True):
            await self._send_off_command()
            return

        state = self.hass.states.get(self.media_player)
        if state and state.state in ["playing", "on"]:
            self.config.show_lyrics = self.ui_state.get("show_lyrics", False)
            await self.media_data.update()
            self._fetch_external_temperature()
            
            wants_lyrics = self.ui_state.get("show_lyrics", False)
            has_lyrics = len(self.media_data.lyrics) > 0
            self.config.show_lyrics = wants_lyrics and has_lyrics
            
            self.media_data.track_changed = True 
            if self.current_task: self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())

    async def _handle_media_change(self, event):
        if not self.ui_state.get("master", True): return
        new_state = event.data.get("new_state")
        if not new_state: return

        if new_state.state not in ["playing", "on"]:
            await self._send_off_command()
            self._stop_lyrics_scheduler()
            return

        self.config.show_lyrics = self.ui_state.get("show_lyrics", False)
        await self.media_data.update()
        self._fetch_external_temperature()
        
        wants_lyrics = self.ui_state.get("show_lyrics", False)
        has_lyrics = len(self.media_data.lyrics) > 0
        self.config.show_lyrics = wants_lyrics and has_lyrics

        if self.media_data.track_changed:
            if self.current_task: self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())
            
        self.progress_timer_gen_id += 1
        await self._update_progress_bar_loop()

    async def _process_and_send(self):
        try:
            start_time = time.perf_counter()
            processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data) or self.fallback_service._get_fallback_black_image_data()
            
            self.media_data.spotify_frames = 0
            base64_image = processed_data.get('base64_image')
            font_color = processed_data.get('font_color', '#FFFFFF')
            bg_color_str = processed_data.get('background_color', '#000000')

            if self.config.light and not self.media_data.playing_tv:
                rgb = processed_data.get('background_color_rgb', (0,0,0))
                await self._control_light('on', rgb, self.media_data.is_night)
            if self.config.wled and not self.media_data.playing_tv:
                c1 = processed_data.get('color1')
                c2 = processed_data.get('color2')
                c3 = processed_data.get('color3')
                await self._control_wled_light('on', c1, c2, c3, self.media_data.is_night)

            sensor_attrs = {
                "artist": self.media_data.artist,
                "song": self.media_data.title,
                "source": self.media_data.pic_source,
                "lyrics_found": len(self.media_data.lyrics) > 0,
                "active_mode": "Lyrics" if self.config.show_lyrics else "Standard",
                "font_color": font_color
            }

            image_cmd = {
                "Command": "Draw/CommandList", 
                "CommandList": [
                    {"Command": "Channel/OnOffScreen", "OnOff": 1}, 
                    {"Command": "Draw/ResetHttpGifId"}, 
                    {"Command": "Draw/SendHttpGif", "PicNum": 1, "PicWidth": 64, "PicOffset": 0, "PicID": 0, "PicSpeed": 10000, "PicData": base64_image}
                ]
            }
            
            took_over = False
            spotify_animation_took_over = False

            if self.config.spotify_slide and not self.media_data.radio_logo and not self.media_data.playing_tv:
                self.spotify_service.spotify_data = await self.spotify_service.get_spotify_json(self.media_data.artist, self.media_data.title)
                if self.spotify_service.spotify_data:
                    t0 = time.perf_counter()
                    if self.config.special_mode and getattr(self.config, 'special_mode_spotify_slider', False):
                        await self.spotify_service.spotify_album_art_animation(self.pixoo_device, self.media_data, self.select_index)
                    else:
                        await self.spotify_service.spotify_albums_slide(self.pixoo_device, self.media_data, self.select_index)
                    
                    if getattr(self.media_data, 'spotify_slide_pass', False):
                        took_over = True
                        spotify_animation_took_over = True
                        self.is_art_visible = True
                        sensor_attrs["process_duration"] = f"{time.perf_counter() - t0:.2f} s (Spotify)"
                    else:
                        await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": self.select_index})

            self.media_data.lyrics_font_color = self.config.force_font_color or font_color
            self.cached_static_items = await self._build_text_items_list(self.media_data.lyrics_font_color, bg_color_str, scope="static")
            
            if not took_over:
                await self.pixoo_device.send_command(image_cmd)
                self.is_art_visible = True
                self.last_text_payload_hash = None 
                self.last_progress_str = "" 
                
                await asyncio.sleep(0.3)
                await self._render_and_send_text_layers()

            elif spotify_animation_took_over and self.config.special_mode:
                await self._render_and_send_text_layers()

            if not spotify_animation_took_over:
                sensor_attrs["process_duration"] = f"{time.perf_counter() - start_time:.2f} s"
            
            if self.sensor:
                self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)

            # Start Lyrics logic ONLY after image and initial text is sent!
            if self.config.show_lyrics and self.media_data.lyrics:
                self.lyrics_active_mode = True
                await self._calculate_and_schedule_next()
            else:
                self._stop_lyrics_scheduler()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Execution error in _process_and_send: %s", e, exc_info=True)

    async def _build_text_items_list(self, font_color, bg_color, scope="all"):
        text_items = []
        if scope in ["all", "static"]:
            if self.config.special_mode:
                text_items.append({"TextId": 1, "type": 14, "x": 3, "y": 1, "dir": 0, "font": 18, "TextWidth": 33, "Textheight": 6, "speed": 100, "align": 1, "color": font_color})
                text_items.append({"TextId": 2, "type": 5, "x": 1, "y": 1, "dir": 0, "font": 18, "TextWidth": 63, "Textheight": 6, "speed": 100, "align": 2, "color": font_color})
                t_type = 22 if getattr(self.media_data, 'temperature', None) else 17
                text_items.append({"TextId": 3, "type": t_type, "x": 48, "y": 1, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": getattr(self.media_data, 'temperature', "") or ""})
                
                if (self.config.show_text and not self.media_data.playing_tv) or getattr(self.media_data, 'spotify_slide_pass', False):
                    a_rtl = 1 if has_bidi(self.media_data.artist) else 0
                    text_items.append({"TextId": 4, "type": 22, "x": 0, "y": 42, "dir": a_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(self.media_data.artist) if a_rtl else self.media_data.artist, "color": font_color})
                    t_rtl = 1 if has_bidi(self.media_data.title) else 0
                    text_items.append({"TextId": 5, "type": 22, "x": 0, "y": 52, "dir": t_rtl, "font": 190, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(self.media_data.title) if t_rtl else self.media_data.title, "color": font_color})

            elif (self.config.show_text or self.config.show_clock or self.config.temperature) and not self.config.show_lyrics:
                y_text = 0 if getattr(self.config, 'top_text', False) else 48
                y_info = 56 if getattr(self.config, 'info_position', 'Top') == "Bottom" else 3
                
                txt = f"{self.media_data.artist} - {self.media_data.title}"
                if len(txt) > 14: txt += "        "
                rtl = 1 if has_bidi(txt) else 0
                
                if self.config.show_text and not self.media_data.radio_logo and not self.media_data.playing_tv:
                    text_items.append({"TextId": 4, "type": 22, "x": 0, "y": y_text, "dir": rtl, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(txt) if rtl else txt, "color": font_color})
                
                if self.config.show_clock:
                    x_c = 44 if getattr(self.config, 'clock_align', 'Right') == "Right" else 3
                    text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})
                if self.config.temperature:
                    x_t = 3 if getattr(self.config, 'clock_align', 'Right') == "Right" else 40
                    t_type = 22 if getattr(self.media_data, 'temperature', None) else 17
                    text_items.append({"TextId": 3, "type": t_type, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": getattr(self.media_data, 'temperature', "") or ""})
        
        return text_items

    async def _control_light(self, action, rgb, is_night):
        if not getattr(self.config, 'light', None) or (not is_night and getattr(self.config, 'only_at_night', False)): return
        try:
            data = {"entity_id": self.config.light}
            if action == 'on': data.update({"rgb_color": rgb, "transition": 1})
            await self.hass.services.async_call("light", f"turn_{action}", data)
        except Exception as e: _LOGGER.error("Light error: %s", e)

    async def _control_wled_light(self, action, c1, c2, c3, is_night):
        if not getattr(self.config, 'wled', None) or (not is_night and getattr(self.config, 'only_at_night', False)): return
        try:
            cols = [c.lstrip('#') for c in filter(None, [c1, c2, c3])]
            seg = {"fx": getattr(self.config, 'effect', 38)}
            if cols: seg["col"] = [cols[0]] if seg["fx"] == 0 else cols
            payload = {"on": action == "on", "bri": getattr(self.config, 'brightness', 255), "seg": [seg]}
            async with self.websession.post(f"http://{self.config.wled}/json/state", json=payload, timeout=5) as r:
                r.raise_for_status()
        except Exception: pass

    async def _send_off_command(self):
        if self.sensor: self.sensor.update_state("Off", {})
        self.is_art_visible = False
        await self.pixoo_device.send_command({
            "Command": "Draw/CommandList", 
            "CommandList": [
                {"Command": "Draw/ClearHttpText"},  
                {"Command": "Draw/ResetHttpGifId"},
                {"Command": "Channel/SetIndex", "SelectIndex": self.select_index}
            ]
        })

    def _stop_lyrics_scheduler(self):
        self.lyrics_active_mode = False
        self.scheduler_generation_id += 1
        self.current_lyrics_items = []

    async def _calculate_and_schedule_next(self):
        if self.notification_manager.is_active or not self.lyrics_active_mode: return
        self.scheduler_generation_id += 1
        gen_id = self.scheduler_generation_id
        
        pos = self.media_data.media_position
        if self.media_data.media_position_updated_at:
            elapsed = (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
            pos += elapsed - float(self.config.lyrics_sync)
        
        try:
            if hasattr(self.lyrics_provider, 'lyrics'):
                self.lyrics_provider.lyrics = self.media_data.lyrics
            layout, delay = self.lyrics_provider.get_refresh_plan(pos)
        except TypeError:
            layout, delay = self.lyrics_provider.get_refresh_plan(self.media_data.lyrics, pos)
        except Exception as e:
            _LOGGER.error("Lyrics error: %s", e)
            layout, delay = None, None

        self.current_lyrics_items = []
        if layout is not None:
            for i in range(6):
                if i < len(layout):
                    it = layout[i]
                    h = min(it['h'], 64 - it['y'])
                    self.current_lyrics_items.append({"TextId": i+10, "type": 22, "x": 0, "y": it['y'], "dir": it['dir'], "font": getattr(self.config, 'lyrics_font', 190), "TextWidth": 64, "Textheight": h, "speed": 0, "align": 2, "TextString": it['text'], "color": getattr(self.media_data, 'lyrics_font_color', "#FFFFFF")})
                else:
                    self.current_lyrics_items.append({"TextId": i+10, "type": 22, "x": 0, "y": 0, "dir": 0, "font": getattr(self.config, 'lyrics_font', 190), "TextWidth": 64, "Textheight": 12, "speed": 0, "align": 2, "TextString": "", "color": "#000000"})
            
        await self._render_and_send_text_layers()
        
        if delay is not None:
            async def _timer(now):
                if self.scheduler_generation_id == gen_id:
                    await self._calculate_and_schedule_next()
            self._unsub_listeners.append(async_call_later(self.hass, delay, _timer))

    async def _update_progress_bar_loop(self):
        if self.notification_manager.is_active or not self.config.progress_bar_enabled: return
        state = self.hass.states.get(self.media_player)
        if not state or state.state not in ["playing", "on"]: return
        
        pos = self.media_data.media_position
        if self.media_data.media_position_updated_at:
            pos += (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
        
        bar_str, delay = self.progress_manager.calculate(pos, self.media_data.media_duration)
        if self.is_art_visible and bar_str != self.last_progress_str:
            self.last_progress_str = bar_str
            await self._render_and_send_text_layers()
        
        if delay is not None:
            gen_id = self.progress_timer_gen_id
            async def _pb_timer(now):
                if self.progress_timer_gen_id == gen_id:
                    await self._update_progress_bar_loop()
            self._unsub_listeners.append(async_call_later(self.hass, delay, _pb_timer))

    async def on_pixoo_notify(self, event_name, data, kwargs):
        if self.current_task: self.current_task.cancel()
        await self.notification_manager.display(data)
        
        st = self.hass.states.get(self.media_player)
        if st and st.state in ["playing", "on"]:
            await self.force_update()
        else:
            await self._send_off_command()
