"""The Core Hub managing UI states and delegating to pixoo_services."""
import asyncio
import logging
import time
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
        
        self.websession = async_get_clientsession(hass)
        self.pixoo_device = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.config, self.websession)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.lyrics_provider = LyricsProvider(self.config, self.websession)
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

    def set_sensor(self, sensor):
        self.sensor = sensor

    async def initialize(self):
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
        self.config.force_ai = self.ui_state.get("force_ai", False)
        self.config.show_lyrics = self.ui_state.get("show_lyrics", False)
        
        self.config.top_text = (self.ui_state.get("text_position", "Bottom") == "Top")
        self.config.clock_align = self.ui_state.get("clock_align", "Right")
        self.config.info_position = self.ui_state.get("info_position", "Top")
        if self.config.spotify_slide:
            self.config.burned = False
            self.config.special_mode = True

    def _fetch_external_temperature(self):
        temp_ent = getattr(self.config, 'temperature_sensor', None)
        if temp_ent:
            s = self.hass.states.get(temp_ent)
            if s and s.state not in ("unknown", "unavailable"):
                self.media_data.temperature = f"{s.state}°"

    async def _render_and_send_text_layers(self):
        if not self.is_art_visible: return
        items = []
        
        if self.lyrics_active_mode and self.current_lyrics_items:
            items.extend(self.current_lyrics_items)
        else:
            if not self.cached_static_items:
                 self.cached_static_items = await self._build_text_items_list(getattr(self.media_data, 'lyrics_font_color', "#FFFFFF"))
            items.extend(self.cached_static_items)
            
        if getattr(self.media_data, 'show_progress_bar', False):
            pb = await self.progress_manager.get_payload_item(self.media_data)
            if pb: items.extend(pb)
            
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
            await self.media_data.update()
            self._fetch_external_temperature()
            self.media_data.track_changed = True 
            if self.current_task: self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())
        else:
            await self._send_off_command()

    async def _handle_media_change(self, event):
        if not self.ui_state.get("master", True): return
        new_state = event.data.get("new_state")
        if not new_state: return

        if new_state.state not in ["playing", "on"]:
            await self._send_off_command()
            self._stop_lyrics_scheduler()
            return

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
            processed_data = await self.fallback_service.get_final_url(self.media_data.picture, self.media_data)
            if not processed_data: processed_data = self.fallback_service._get_fallback_black_image_data()
            
            base64_image = processed_data.get('base64_image')
            font_color = processed_data.get('font_color', '#FFFFFF')

            sensor_attrs = {
                "artist": self.media_data.artist,
                "song": self.media_data.title,
                "source": self.media_data.pic_source,
                "lyrics_found": len(self.media_data.lyrics) > 0,
                "active_mode": "Lyrics" if self.config.show_lyrics else "Standard"
            }

            image_cmd = {
                "Command": "Draw/CommandList", 
                "CommandList": [
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
                self.cached_static_items = await self._build_text_items_list(font_color)
                
                await asyncio.sleep(0.3)
                await self._render_and_send_text_layers()

                if self.config.show_lyrics and self.media_data.lyrics:
                    self.lyrics_active_mode = True
                    await self._calculate_and_schedule_next()
                else:
                    self._stop_lyrics_scheduler()
                    
            if self.sensor: self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", sensor_attrs)

        except asyncio.CancelledError: pass
        except Exception as e: _LOGGER.error("Execution error: %s", e)

    async def _build_text_items_list(self, font_color):
        text_items = []
        y_text = 0 if getattr(self.config, 'top_text', False) else 48
        y_info = 56 if getattr(self.config, 'info_position', 'Top') == "Bottom" else 3
        
        txt = f"{self.media_data.artist} - {self.media_data.title}"
        if len(txt) > 14: txt += "        "
        rtl = 1 if has_bidi(txt) else 0
        
        if getattr(self.config, 'show_text', True) and not getattr(self.media_data, 'playing_tv', False):
            text_items.append({"TextId": 4, "type": 22, "x": 0, "y": y_text, "dir": rtl, "font": 2, "TextWidth": 64, "Textheight": 16, "speed": 100, "align": 2, "TextString": get_bidi(txt) if rtl else txt, "color": font_color})
        
        if getattr(self.config, 'show_clock', True):
            x_c = 44 if getattr(self.config, 'clock_align', 'Right') == "Right" else 3
            text_items.append({"TextId": 2, "type": 5, "x": x_c, "y": y_info, "dir": 0, "font": 18, "TextWidth": 32, "Textheight": 16, "speed": 100, "align": 1, "color": font_color})

        if getattr(self.config, 'temperature', False) and getattr(self.media_data, 'temperature', None):
            x_t = 3 if getattr(self.config, 'clock_align', 'Right') == "Right" else 40
            text_items.append({"TextId": 3, "type": 22, "x": x_t, "y": y_info, "dir": 0, "font": 18, "TextWidth": 20, "Textheight": 6, "speed": 100, "align": 1, "color": font_color, "TextString": str(self.media_data.temperature)})
            
        return text_items

    async def _send_off_command(self):
        if self.sensor: self.sensor.update_state("Off", {})
        self.is_art_visible = False
        await self.pixoo_device.send_command({
            "Command": "Draw/CommandList", 
            "CommandList": [
                {"Command": "Draw/ClearHttpText"},  
                {"Command": "Draw/ResetHttpGifId"},
                {"Command": "Channel/SetIndex", "SelectIndex": 0}
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
            pos += (datetime.now(timezone.utc) - self.media_data.media_position_updated_at).total_seconds()
        
        layout, delay = self.lyrics_provider.get_refresh_plan(pos)

        self.current_lyrics_items = []
        if layout is not None:
            for i in range(6):
                if i < len(layout):
                    it = layout[i]
                    h = min(it['h'], 64 - it['y'])
                    self.current_lyrics_items.append({"TextId": i+10, "type": 22, "x": 0, "y": it['y'], "dir": it['dir'], "font": 190, "TextWidth": 64, "Textheight": h, "speed": 0, "align": 2, "TextString": it['text'], "color": getattr(self.media_data, 'lyrics_font_color', "#FFFFFF")})
                else:
                    self.current_lyrics_items.append({"TextId": i+10, "type": 22, "x": 0, "y": 0, "dir": 0, "font": 190, "TextWidth": 64, "Textheight": 12, "speed": 0, "align": 2, "TextString": "", "color": "#000000"})
            
        await self._render_and_send_text_layers()
        
        if delay is not None:
            async def _timer(now):
                if self.scheduler_generation_id == gen_id: await self._calculate_and_schedule_next()
            self._unsub_listeners.append(async_call_later(self.hass, delay, _timer))

    async def _update_progress_bar_loop(self):
        if self.notification_manager.is_active or not getattr(self.config, 'progress_bar_enabled', False): return
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
                if self.progress_timer_gen_id == gen_id: await self._update_progress_bar_loop()
            self._unsub_listeners.append(async_call_later(self.hass, delay, _pb_timer))

    async def on_pixoo_notify(self, event_name, data, kwargs):
        await self.notification_manager.display(data)
