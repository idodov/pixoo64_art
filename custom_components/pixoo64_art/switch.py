"""Switch platform for Pixoo64."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

SWITCHES = [
    ("master", "Master Control", "mdi:power", True),
    ("show_lyrics", "Show Lyrics", "mdi:music-note-text", False),
    ("show_clock", "Show Clock", "mdi:clock", True),
    ("show_temperature", "Show Temperature", "mdi:thermometer", False),
    ("show_text", "Show Text", "mdi:text", True),
    ("text_background", "Text Background", "mdi:format-color-fill", True),
    ("burned_effect", "Burned Effect", "mdi:fire", False),
    ("progress_bar", "Progress Bar", "mdi:progress-clock", True),
    ("spotify_slider", "Spotify Slider Mode", "mdi:spotify", False),
    ("force_ai", "Force AI Generation", "mdi:robot-excited", False),
]

async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    entities = [PixooSwitch(hub, entry, key, name, icon, def_val) for key, name, icon, def_val in SWITCHES]
    async_add_entities(entities)

class PixooSwitch(SwitchEntity):
    def __init__(self, hub, entry, key, name, icon, default_val):
        self.hub = hub
        self.key = key
        self._attr_name = f"Pixoo64 {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_is_on = self.hub.ui_state.get(key, default_val)
        self.hub.ui_state[key] = self._attr_is_on

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, self.hub.pixoo_ip)})

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()
        await self.hub.async_ui_update(self.key, True)

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()
        await self.hub.async_ui_update(self.key, False)
