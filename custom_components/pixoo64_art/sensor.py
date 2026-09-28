"""Sensor platform for Pixoo64."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    sensor = PixooMediaSensor(hub, entry)
    hub.set_sensor(sensor)
    async_add_entities([sensor])

class PixooMediaSensor(SensorEntity):
    def __init__(self, hub, entry):
        self.hub = hub
        self._attr_name = "Pixoo64 Media Status"
        self._attr_unique_id = f"{entry.entry_id}_sensor"
        self._attr_icon = "mdi:monitor-dashboard"
        self._state = "Idle"
        self._attributes = {}

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, self.hub.pixoo_ip)})

    def update_state(self, state_str: str, attributes: dict):
        self._state = state_str
        self._attributes = attributes
        self.async_write_ha_state()