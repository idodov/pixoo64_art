"""Switch platform for Pixoo64."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import STATE_ON
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SWITCHES = [
    ("master_control", "Master Control", True, "mdi:power"),
    ("force_ai", "Force AI Generation", False, "mdi:robot-outline"),
    ("progress_bar", "Progress Bar", True, "mdi:progress-clock"),
    ("text_background", "Show Text Background", True, "mdi:page-layout-header-footer"),
]

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Pixoo64 switches."""
    hub = hass.data[DOMAIN][entry.entry_id]
    entities = [
        PixooRestoreSwitch(hub, entry, key, name, default_state, icon)
        for key, name, default_state, icon in SWITCHES
    ]
    async_add_entities(entities)

class PixooRestoreSwitch(SwitchEntity, RestoreEntity):
    """Representation of a restored Pixoo64 switch."""

    def __init__(self, hub, entry, key, name, default_state, icon):
        """Initialize the switch."""
        self.hub = hub
        self.key = key
        self._attr_name = f"Pixoo64 {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_is_on = default_state
        
        # Initialize default in hub
        self.hub.ui_state[self.key] = self._attr_is_on

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
        
        if last_state is not None:
            self._attr_is_on = last_state.state == STATE_ON
        
        # Sync with hub upon restoration
        self.hub.ui_state[self.key] = self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()
        await self.hub.async_ui_update(self.key, True)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()
        await self.hub.async_ui_update(self.key, False)
