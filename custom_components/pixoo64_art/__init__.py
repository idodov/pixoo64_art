"""The Pixoo64 Media Album Art integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

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
    
    # הפעלה יזומה של ה-Hub מיד כשהאינטגרציה נטענת
    hass.async_create_task(hub.initialize())

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub = hass.data[DOMAIN].get(entry.entry_id)
    if hub:
        await hub.terminate()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
