"""Sensor platform for Pixoo64."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    sensor = PixooStatusSensor(hub, entry)
    hub.set_sensor(sensor)
    async_add_entities([sensor])

class PixooStatusSensor(SensorEntity):
    def __init__(self, hub, entry):
        self.hub = hub
        self._attr_name = "Pixoo64 Status"
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_icon = "mdi:television-ambient-light"
        self._attr_native_value = "Initializing"
        self._attr_extra_state_attributes = {
            "prefetch_status": "Idle",
            "prefetch_next_artist": None,
            "prefetch_next_title": None,
            "spotify_slider_status": "Idle",
            "spotify_slider_frames": 0,
            "spotify_slider_artist": None,
            "spotify_slider_last_error": None,
        }

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub.pixoo_ip)},
            name="Pixoo64 Media Display",
            manufacturer="Divoom",
            model="Pixoo 64",
        )

    def update_state(self, state_val, attrs):
        self._attr_native_value = state_val
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()