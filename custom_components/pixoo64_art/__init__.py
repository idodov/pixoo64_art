"""The Pixoo64 Media Album Art integration."""

import logging
import os

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, HomeAssistant

from .const import DOMAIN
from .hub import PixooHub
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.NOTIFY,
]

CARD_URL = "/pixoo64_card/pixoo-media-card.js"
CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Register the custom Lovelace card static path and inject it into the HA frontend."""
    if hass.data.get(CARD_REGISTERED_KEY):
        return

    integration_dir = os.path.dirname(__file__)
    card_path = os.path.join(integration_dir, "pixoo-media-card.js")

    if not os.path.isfile(card_path):
        _LOGGER.warning(
            "pixoo-media-card.js not found at %s! Place the JS file inside the integration folder.",
            card_path,
        )
        return

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, card_path, cache_headers=False)]
        )
    except Exception as err:
        _LOGGER.debug("Static path registration note: %s", err)

    try:
        mtime = await hass.async_add_executor_job(os.path.getmtime, card_path)
        versioned_url = f"{CARD_URL}?v={int(mtime)}"
        add_extra_js_url(hass, versioned_url)
        hass.data[CARD_REGISTERED_KEY] = True
    except Exception as err:
        _LOGGER.warning("Could not add extra JS URL: %s", err)
        return

    async def _register_lovelace_resource(_event=None) -> None:
        try:
            lovelace = hass.data.get("lovelace")
            if not lovelace:
                return
            resources = getattr(lovelace, "resources", None) or (
                lovelace.get("resources") if isinstance(lovelace, dict) else None
            )
            if resources and hasattr(resources, "async_items"):
                if hasattr(resources, "async_load") and not getattr(
                    resources, "loaded", True
                ):
                    await resources.async_load()

                existing = []
                for r in resources.async_items():
                    if str(r.get("url", "")).startswith(CARD_URL):
                        existing.append(r)
                        if r.get("url") != versioned_url and hasattr(resources, "async_update_item"):
                            await resources.async_update_item(
                                r.get("id"), {"res_type": "module", "url": versioned_url}
                            )
                if not existing and hasattr(resources, "async_create_item"):
                    await resources.async_create_item(
                        {"res_type": "module", "url": versioned_url}
                    )
                    _LOGGER.info("Added Pixoo Media Card to Lovelace resources.")
        except Exception as err:
            _LOGGER.debug("Optional Lovelace resource registration skipped: %s", err)

    if hass.state == CoreState.running:
        hass.async_create_task(_register_lovelace_resource())
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _register_lovelace_resource
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pixoo64 from a config entry."""
    _LOGGER.info("Setting up Pixoo64 integration entry: %s", entry.entry_id)
    hass.data.setdefault(DOMAIN, {})

    await _async_register_frontend_card(hass)

    try:
        hub = PixooHub(hass, entry)
        hass.data[DOMAIN][entry.entry_id] = hub
    except Exception as e:
        _LOGGER.error("Failed to initialize PixooHub: %s", e)
        return False

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as e:
        _LOGGER.error("Failed to forward entry setups for platforms: %s", e)
        return False

    hass.async_create_task(hub.initialize())
    await async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _LOGGER.info("Pixoo64 integration setup completed successfully.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub = hass.data[DOMAIN].get(entry.entry_id)
    if hub:
        await hub.terminate()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    if not hass.data.get(DOMAIN):
        async_unregister_services(hass)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug(
        "Migrating Pixoo64 entry from version %s to 2.0", config_entry.version
    )
    if config_entry.version < 2.0:
        hass.config_entries.async_update_entry(config_entry, version=2.0)
    return True
