"""Select platform for Pixoo64."""
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SELECTS = [
    ("display_mode", "Display Mode", ["Standard", "Lyrics", "Burned", "Special Mode", "Spotify Slider"], "Standard", "mdi:monitor-dashboard"),
    ("text_position", "Artist & Track Text", ["Hidden", "Top", "Bottom"], "Bottom", "mdi:format-text"),
    ("overlay_info", "Overlay Info", ["None", "Clock", "Temperature", "Clock + Temp"], "Clock", "mdi:information-outline"),
    ("crop_mode", "Crop Mode", ["Default", "No Crop", "Crop", "Extra Crop"], "Default", "mdi:crop"),
]

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Pixoo64 selects."""
    hub = hass.data[DOMAIN][entry.entry_id]
    entities = [
        PixooRestoreSelect(hub, entry, key, name, options, def_val, icon)
        for key, name, options, def_val, icon in SELECTS
    ]
    async_add_entities(entities)

class PixooRestoreSelect(SelectEntity, RestoreEntity):
    """Representation of a restored Pixoo64 select entity."""

    def __init__(self, hub, entry, key, name, options, default_val, icon):
        """Initialize the select."""
        self.hub = hub
        self.key = key
        self._attr_name = f"Pixoo64 {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_options = options
        self._attr_icon = icon
        self._attr_current_option = default_val
        
        # Initialize default in hub
        self.hub.ui_state[self.key] = self._attr_current_option

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub.pixoo_ip)},
            name="Pixoo64 Media Display",
            manufacturer="Divoom",
            model="Pixoo 64",
        )

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        
        if last_state is not None and last_state.state in self._attr_options:
            self._attr_current_option = last_state.state
            
        # Sync with hub upon restoration
        self.hub.ui_state[self.key] = self._attr_current_option

    async def async_select_option(self, option: str):
        """Change the selected option."""
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()
            await self.hub.async_ui_update(self.key, option)
