"""The Pixoo64 Media Album Art integration."""

import logging
import os
import shutil

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
HACS_CARD_URL = f"/hacsfiles/{DOMAIN}/pixoo-media-card.js"
LOCAL_CARD_URL = f"/local/{DOMAIN}/pixoo-media-card.js"
CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"


def _sync_card_files(card_path: str, config_dir: str) -> str:
    """Copy card JS to www/community (for /hacsfiles/) and www/ (for /local/) and return active URL base."""
    active_url = CARD_URL
    try:
        www_dir = os.path.join(config_dir, "www")
        community_dir = os.path.join(www_dir, "community")
        if os.path.isdir(community_dir):
            target_dir = os.path.join(community_dir, DOMAIN)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(card_path, os.path.join(target_dir, "pixoo-media-card.js"))
            active_url = HACS_CARD_URL
        elif os.path.isdir(www_dir):
            target_dir = os.path.join(www_dir, DOMAIN)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(card_path, os.path.join(target_dir, "pixoo-media-card.js"))
            active_url = LOCAL_CARD_URL
    except Exception as err:
        _LOGGER.debug("Could not copy card file to www folder: %s", err)
    return active_url


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Register the custom Lovelace card static path and inject it into the HA frontend."""
    integration_dir = os.path.dirname(__file__)
    card_path = os.path.join(integration_dir, "pixoo-media-card.js")

    if not os.path.isfile(card_path):
        _LOGGER.warning(
            "pixoo-media-card.js not found at %s! Place the JS file inside the integration folder.",
            card_path,
        )
        return

    active_base_url = await hass.async_add_executor_job(
        _sync_card_files, card_path, hass.config.path()
    )

    if not hass.data.get(CARD_REGISTERED_KEY):
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, card_path, cache_headers=False)]
            )
        except Exception as err:
            _LOGGER.debug("Static path registration note: %s", err)

    try:
        mtime = await hass.async_add_executor_job(os.path.getmtime, card_path)
        versioned_url = f"{active_base_url}?v={int(mtime)}"
        if not hass.data.get(CARD_REGISTERED_KEY):
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

                matched_prefixes = (CARD_URL, HACS_CARD_URL, LOCAL_CARD_URL)
                existing = []
                for r in resources.async_items():
                    r_url = str(r.get("url", ""))
                    if any(r_url.startswith(p) for p in matched_prefixes) or "pixoo-media-card.js" in r_url:
                        existing.append(r)
                        if r_url != versioned_url and hasattr(resources, "async_update_item"):
                            await resources.async_update_item(
                                r.get("id"), {"res_type": "module", "url": versioned_url}
                            )
                if not existing and hasattr(resources, "async_create_item"):
                    await resources.async_create_item(
                        {"res_type": "module", "url": versioned_url}
                    )
                    _LOGGER.info("Added Pixoo Media Card to Lovelace resources: %s", versioned_url)
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
    """Reload config entry when options change without turning off the display."""
    hub = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if hub:
        new_ip = entry.options.get(CONF_PIXOO_IP, entry.data.get(CONF_PIXOO_IP))
        if new_ip and new_ip != hub.pixoo_ip:
            _LOGGER.info("Pixoo64 IP changed; performing full reload...")
            await hass.config_entries.async_reload(entry.entry_id)
            return

        _LOGGER.info("Updating Pixoo64 configuration in-place...")
        hub.entry = entry
        hub._apply_logic_matrix()
        hass.async_create_task(hub.async_refresh_pollen_balance())
        st = hass.states.get(hub.media_player)
        if st and (hub._is_player_active(st) or st.state == "paused"):
            hub._active_song_key = None
            await hub.force_update()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug(
        "Migrating Pixoo64 entry from version %s to 2.0", config_entry.version
    )
    if config_entry.version < 2.0:
        hass.config_entries.async_update_entry(config_entry, version=2.0)
    return True
