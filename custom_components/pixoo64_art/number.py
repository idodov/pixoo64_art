"""Number platform for Pixoo64."""
from homeassistant.components.number import RestoreNumber
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PixooLyricsSyncNumber(hub, entry)])

class PixooLyricsSyncNumber(RestoreNumber):
    def __init__(self, hub, entry):
        self.hub = hub
        self.key = "lyrics_sync"
        self._attr_name = "Pixoo64 Lyrics Sync Offset"
        self._attr_unique_id = f"{entry.entry_id}_{self.key}"
        self._attr_icon = "mdi:timer-sync"
        self._attr_native_min_value = -5.0
        self._attr_native_max_value = 5.0
        self._attr_native_step = 0.5
        
        self._attr_native_value = float(self.hub.ui_state.get(self.key, 0.0))
        self.hub.ui_state[self.key] = self._attr_native_value

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub.pixoo_ip)},
            name="Pixoo64 Media Display",
            manufacturer="Divoom",
            model="Pixoo 64",
        )

    async def async_added_to_hass(self):
        """Restore previous native value on startup."""
        await super().async_added_to_hass()
        last_data = await self.async_get_last_number_data()
        if last_data is not None and last_data.native_value is not None:
            self._attr_native_value = float(last_data.native_value)
            self.hub.ui_state[self.key] = self._attr_native_value
            self.hub._apply_logic_matrix()

    async def async_set_native_value(self, value: float):
        self._attr_native_value = float(value)
        self.async_write_ha_state()
        await self.hub.async_ui_update(self.key, float(value))