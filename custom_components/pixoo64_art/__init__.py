"""The Pixoo64 Media Album Art integration."""
import asyncio
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hub import PixooHub

PLATFORMS = ["sensor", "switch", "select", "number"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pixoo64 from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hub = PixooHub(hass, entry)
    await hub.initialize()
    
    hass.data[DOMAIN][entry.entry_id] = hub
    
    # --- התיקון החסר: טעינת הישויות (כפתורים, חיישנים וכו') לתוך Home Assistant ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Register the Custom Notification Service
    async def handle_notification(call):
        data = {
            "message": call.data.get("message", ""),
            "type": call.data.get("type", "text"),
            "duration": call.data.get("duration", 5)
        }
        await hub.on_pixoo_notify("pixoo_notify", data, {})

    hass.services.async_register(DOMAIN, "send_notification", handle_notification)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # --- התיקון החסר: פריקה נקייה של הישויות כשהמשתמש מכבה את האינטגרציה ---
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.terminate()
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)