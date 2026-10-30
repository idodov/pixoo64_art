"""Sensor platform for Pixoo64."""
from typing import Any, Dict
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    status_sensor = PixooStatusSensor(hub, entry)
    analytics_sensor = PixooAnalyticsSensor(hub, entry)
    hub.set_sensors(status_sensor, analytics_sensor)
    async_add_entities([status_sensor, analytics_sensor])


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
            "current_track_plays": 0,
            "current_track_rank": None,
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
        if self.hass:
            self.async_write_ha_state()


class PixooAnalyticsSensor(SensorEntity):
    """Dedicated analytics and database metrics sensor for Hit Parade and scrobbles."""

    def __init__(self, hub, entry):
        self.hub = hub
        self._attr_name = "Pixoo64 Analytics"
        self._attr_unique_id = f"{entry.entry_id}_analytics"
        self._attr_icon = "mdi:chart-box-outline"
        self._attr_native_value = 0
        self._attr_native_unit_of_measurement = "plays"
        self._attr_extra_state_attributes: Dict[str, Any] = {
            "db_total_songs": 0,
            "db_total_artists": 0,
            "db_total_play_events": 0,
            "db_cached_artwork_masters": 0,
            "db_size": "0 KB",
            "plays_last_24h": 0,
            "plays_last_7d": 0,
            "plays_last_30d": 0,
            "radio_plays": 0,
            "completed_albums": 0,
            "completed_eps": 0,
            "all_time_top_track": None,
            "all_time_top_artist": None,
            "last_scrobble": None,
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
        if self.hass:
            self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Fetch latest statistics upon addition to HA."""
        await super().async_added_to_hass()
        if hasattr(self.hub, "async_update_analytics_sensor"):
            await self.hub.async_update_analytics_sensor()
