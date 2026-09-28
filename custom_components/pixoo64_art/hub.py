"""The Core Hub managing UI states and delegating to pixoo_services."""
import asyncio
import logging
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_call_later

from .const import CONF_PIXOO_IP, CONF_MEDIA_PLAYER
from .pixoo_services import (
    Config, PixooDevice, ImageProcessor, SpotifyService, FallbackService,
    LyricsProvider, MediaData, ProgressBarManager, NotificationManager
)

_LOGGER = logging.getLogger(__name__)

class PixooHub:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.pixoo_ip = entry.data[CONF_PIXOO_IP]
        self.media_player = entry.data[CONF_MEDIA_PLAYER]
        
        self.ui_state = {}  # Stores values from switches, selects, numbers
        self.config = Config(entry)
        self.sensor = None
        
        self._unsub_listeners = []
        self.current_task = None
        
        # Initialize Core Services
        self.websession = async_get_clientsession(hass)
        self.pixoo_device = PixooDevice(self.config, self.websession)
        self.image_processor = ImageProcessor(self.config, self.websession)
        self.spotify_service = SpotifyService(self.config, self.websession, self.image_processor)
        self.lyrics_provider = LyricsProvider(self.config, self.websession)
        self.media_data = MediaData(self.hass, self.config, self.image_processor, self.websession)
        self.fallback_service = FallbackService(self.config, self.image_processor, self.websession, self.spotify_service, self.pixoo_device)
        self.progress_manager = ProgressBarManager(self.config, self.hass)
        self.notification_manager = NotificationManager(self.config, self.pixoo_device, self.image_processor, self.hass)

    def set_sensor(self, sensor):
        self.sensor = sensor

    async def initialize(self):
        """Register listeners."""
        self._unsub_listeners.append(
            async_track_state_change_event(self.hass, [self.media_player], self._handle_media_change)
        )
        self._apply_logic_matrix()

    async def terminate(self):
        """Cleanup on integration removal."""
        for unsub in self._unsub_listeners:
            unsub()
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.image_processor.shutdown()

    async def async_ui_update(self, key: str, value):
        """Called when a user clicks a switch/select in the dashboard."""
        self.ui_state[key] = value
        self._apply_logic_matrix()
        await self.force_update()

    def _apply_logic_matrix(self):
        """Translates UI buttons into actual config rules (Traffic Control)."""
        # Base mapping
        self.config.show_clock = self.ui_state.get("show_clock", True)
        self.config.temperature = self.ui_state.get("show_temperature", False)
        self.config.show_text = self.ui_state.get("show_text", True)
        self.config.text_bg = self.ui_state.get("text_background", True)
        self.config.burned = self.ui_state.get("burned_effect", False)
        self.config.progress_bar_enabled = self.ui_state.get("progress_bar", True)
        self.config.spotify_slide = self.ui_state.get("spotify_slider", False)
        
        self.config.top_text = (self.ui_state.get("text_position", "Bottom") == "Top")
        self.config.clock_align = self.ui_state.get("clock_align", "Right")
        
        crop = self.ui_state.get("crop_mode", "Default")
        self.config.crop_borders = crop in ["Crop", "Extra Crop"]
        self.config.crop_extra = crop == "Extra Crop"
        
        self.config.ai_fallback = self.ui_state.get("ai_model", "flux")
        self.config.lyrics_sync = self.ui_state.get("lyrics_sync", 0.0)

        # OVERRIDE RULES (The Logic Matrix)
        if self.config.spotify_slide:
            self.config.burned = False  # Burned effect conflicts with Spotify animation
            self.config.special_mode = True

        # Lyrics Fallback logic is handled inside _handle_media_change dynamically

    async def force_update(self):
        """Force a re-render when UI changes."""
        if not self.ui_state.get("master", True):
            await self._send_off_command()
            return

        state = self.hass.states.get(self.media_player)
        if state and state.state in ["playing", "on"]:
            self.media_data.track_changed = True # Force rebuild
            if self.current_task: self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())

    async def _handle_media_change(self, event):
        if not self.ui_state.get("master", True): return
        new_state = event.data.get("new_state")
        if not new_state: return

        if new_state.state not in ["playing", "on"]:
            await self._send_off_command()
            return

        await self.media_data.update()
        
        # SMART FALLBACK FOR LYRICS
        wants_lyrics = self.ui_state.get("show_lyrics", False)
        has_lyrics = len(self.media_data.lyrics) > 0
        
        # If user wants lyrics, but none found -> Fallback to normal layout seamlessly
        self.config.show_lyrics = wants_lyrics and has_lyrics

        if self.media_data.track_changed:
            if self.current_task: self.current_task.cancel()
            self.current_task = self.hass.async_create_task(self._process_and_send())

    async def _process_and_send(self):
        """Passes execution to pixoo_services and updates the sensor."""
        try:
            # Note: pixoo_services handles the entire PIL executor pool internally
            await self.media_data.pixoo_run(self.hass.states.get(self.media_player).state, self.media_data)
            
            if self.sensor:
                # Build neat attributes for the sensor
                attrs = {
                    "artist": self.media_data.artist,
                    "song": self.media_data.title,
                    "source": self.media_data.pic_source,
                    "lyrics_found": len(self.media_data.lyrics) > 0,
                    "active_mode": "Lyrics" if self.config.show_lyrics else "Standard"
                }
                self.sensor.update_state(f"{self.media_data.artist} - {self.media_data.title}", attrs)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Execution error: %s", e)

    async def _send_off_command(self):
        if self.sensor: self.sensor.update_state("Off", {})
        await self.pixoo_device.send_command({
            "Command": "Draw/CommandList", 
            "CommandList": [
                {"Command": "Draw/ClearHttpText"},  
                {"Command": "Draw/ResetHttpGifId"},
                {"Command": "Channel/SetIndex", "SelectIndex": 0}
            ]
        })

    async def on_pixoo_notify(self, event_name, data, kwargs):
        """Bridge for notification service."""
        await self.notification_manager.display(data)