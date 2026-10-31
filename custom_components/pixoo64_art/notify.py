"""Notify platform for Pixoo64."""
from typing import Any, Dict, Optional
from homeassistant.components.notify import (
    NotifyEntity,
    NotifyEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pixoo64 notify platform."""
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PixooNotificationEntity(hub, entry)])


class PixooNotificationEntity(NotifyEntity):
    """Pixoo64 notify entity allowing automations to send messages to the LED screen."""

    _attr_has_entity_name = True
    _attr_name = "Notification"
    _attr_icon = "mdi:bell-badge-outline"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, hub, entry: ConfigEntry) -> None:
        self.hub = hub
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_notify"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub.pixoo_ip)},
            name="Pixoo64 Media Display",
            manufacturer="Divoom",
            model="Pixoo 64",
        )

    async def async_send_message(
        self,
        message: str,
        title: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a notification message to the Pixoo64 screen."""
        data = dict(data or {})
        payload = {
            "message": message,
            "title": title,
            "type": data.get("type") or data.get("icon", "text"),
            "icon": data.get("icon") or data.get("lametric_icon") or data.get("awtrix_icon") or data.get("icon_id"),
            "model": data.get("model"),
            "burned_text": bool(data.get("burned_text", True)),
            "duration": int(data.get("duration", 5)),
            "anim_speed": data.get("anim_speed") or data.get("speed"),
            "color": data.get("color"),
            "play_buzzer": bool(data.get("play_buzzer", False)),
            "buzzer_active": int(data.get("buzzer_active", 500)),
            "buzzer_off": int(data.get("buzzer_off", 500)),
            "buzzer_total": int(data.get("buzzer_total", 3000)),
        }
        await self.hub.async_send_notification_payload(payload)
