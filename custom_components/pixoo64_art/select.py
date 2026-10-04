"""Select platform for Pixoo64."""
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Pixoo64 selects."""
    hub = hass.data[DOMAIN][entry.entry_id]

    selects_config = [
        ("display_mode", "Display Mode", ["Standard", "Vinyl", "Cassette", "Lyrics", "Burned", "Special Mode", "Artist Slide"], "Standard", "mdi:monitor-dashboard"),
        ("image_filter", "Image Filter", ["None", "Vibrant", "Retro Arcade", "Crisp & Sharp", "Noir B&W", "Cyberpunk Neon"], "None", "mdi:image-filter-hdr"),
        ("text_position", "Artist & Track Text", ["Hidden", "Top", "Bottom"], "Bottom", "mdi:format-text"),
        ("overlay_info", "Overlay Info", ["None", "Clock", "Temperature", "Clock + Temp"], "Clock", "mdi:information-outline"),
        ("overlay_position", "Overlay Vertical Position", ["Auto (Opposite of Text)", "Top", "Bottom"], "Auto (Opposite of Text)", "mdi:arrow-up-down"),
        ("overlay_align", "Overlay Alignment", ["Clock Right, Temp Left", "Clock Left, Temp Right", "Centered"], "Clock Right, Temp Left", "mdi:format-horizontal-align-center"),
        ("crop_mode", "Crop Mode", ["No Crop", "Crop", "Extra Crop"], "No Crop", "mdi:crop"),
    ]

    entities = [
        PixooRestoreSelect(hub, entry, key, name, base_options, def_val, icon)
        for key, name, base_options, def_val, icon in selects_config
    ]
    async_add_entities(entities)

class PixooRestoreSelect(SelectEntity, RestoreEntity):
    """Representation of a restored Pixoo64 select entity with dynamic options."""

    def __init__(self, hub, entry, key, name, options, default_val, icon):
        self.hub = hub
        self.entry = entry
        self.key = key
        self._attr_name = f"Pixoo64 {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._base_options = options
        self._attr_icon = icon
        self._attr_current_option = default_val
        self.hub.ui_state[self.key] = self._attr_current_option

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub.pixoo_ip)},
            name="Pixoo64 Media Display",
            manufacturer="Divoom",
            model="Pixoo 64",
        )

    @property
    def options(self) -> list[str]:
        if self.key == "display_mode":
            modes = ["Standard", "Vinyl", "Cassette", "Lyrics", "Burned", "Special Mode", "Artist Slide"]
            if self.hub.is_spotify_available:
                modes.append("Spotify Slider")
            if self.hub.is_ai_available:
                modes.append("Force AI")
            return modes
        return self._base_options

    @property
    def current_option(self) -> str:
        if self.key == "display_mode":
            if self._attr_current_option == "Spotify Slider" and not self.hub.is_spotify_available:
                return "Standard"
            if self._attr_current_option == "Force AI" and not self.hub.is_ai_available:
                return "Standard"
        return self._attr_current_option

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self._attr_current_option = last_state.state
        else:
            self._attr_current_option = self.options[0]
        self.hub.ui_state[self.key] = self._attr_current_option

    async def async_select_option(self, option: str):
        if option in self.options:
            self._attr_current_option = option
            self.async_write_ha_state()
            await self.hub.async_ui_update(self.key, option)