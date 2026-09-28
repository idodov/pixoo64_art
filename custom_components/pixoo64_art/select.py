"""Select platform for Pixoo64."""
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

SELECTS = [
    ("text_position", "Text Position", ["Top", "Bottom"], "Bottom", "mdi:format-vertical-align-bottom"),
    ("info_position", "Clock & Temp Position", ["Opposite to Text", "Top", "Bottom"], "Opposite to Text", "mdi:swap-vertical"),
    ("info_align", "Clock & Temp Alignment", ["Right", "Left"], "Right", "mdi:format-align-right"),
    ("crop_mode", "Crop Mode", ["Default", "No Crop", "Crop", "Extra Crop"], "Default", "mdi:crop"),
    ("ai_model", "AI Generation Model", ["flux", "z-image-turbo", "gpt-image-1.5"], "flux", "mdi:robot-outline"),
]

async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    entities = [PixooSelect(hub, entry, key, name, options, def_val, icon) for key, name, options, def_val, icon in SELECTS]
    async_add_entities(entities)

class PixooSelect(SelectEntity):
    def __init__(self, hub, entry, key, name, options, default_val, icon):
        self.hub = hub
        self.key = key
        self._attr_name = f"Pixoo64 {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_options = options
        self._attr_icon = icon
        
        self._attr_current_option = self.hub.ui_state.get(key, default_val)
        self.hub.ui_state[key] = self._attr_current_option

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, self.hub.pixoo_ip)})

    async def async_select_option(self, option: str):
        self._attr_current_option = option
        self.async_write_ha_state()
        await self.hub.async_ui_update(self.key, option)
