"""The Pixoo64 Media Album Art integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .hub import PixooHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.NUMBER,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pixoo64 from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    hub = PixooHub(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    hass.async_create_task(hub.initialize())

    async def handle_send_notification(call: ServiceCall):
        await hub.async_handle_notification_service(call)

    hass.services.async_register(
        DOMAIN,
        "send_notification",
        handle_send_notification
    )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub = hass.data[DOMAIN].get(entry.entry_id)
    if hub:
        await hub.terminate()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "send_notification")

    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_migrate_entry(hass, config_entry):
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating Pixoo64 entry from version %s to 1.2", config_entry.version)

    if config_entry.version < 1.2:
        hass.config_entries.async_update_entry(config_entry, version=1.2)

    return True