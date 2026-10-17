"""The Pixoo64 Media Album Art integration."""
import os
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall, CoreState
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN
from .hub import PixooHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.NUMBER,
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
        await hass.http.async_register_static_paths([
            StaticPathConfig(CARD_URL, card_path, cache_headers=False)
        ])
    except Exception as err:
        _LOGGER.debug("Static path registration note: %s", err)

    try:
        mtime = int(os.path.getmtime(card_path))
        versioned_url = f"{CARD_URL}?v={mtime}"
        add_extra_js_url(hass, versioned_url)
        hass.data[CARD_REGISTERED_KEY] = True
        _LOGGER.info("Pixoo Media Card automatically injected into Home Assistant frontend (%s)", versioned_url)
    except Exception as err:
        _LOGGER.error("Failed to inject Pixoo Media Card via add_extra_js_url: %s", err)

    async def _register_lovelace_resource(_event=None):
        try:
            lovelace = hass.data.get("lovelace")
            if not lovelace:
                return
            resources = getattr(lovelace, "resources", None) or (
                lovelace.get("resources") if isinstance(lovelace, dict) else None
            )
            if resources and hasattr(resources, "async_items"):
                if hasattr(resources, "async_load") and not getattr(resources, "loaded", True):
                    await resources.async_load()
                
                existing = [r for r in resources.async_items() if str(r.get("url", "")).startswith(CARD_URL)]
                if not existing and hasattr(resources, "async_create_item"):
                    await resources.async_create_item({"res_type": "module", "url": versioned_url})
                    _LOGGER.info("Added Pixoo Media Card to Lovelace resources.")
        except Exception as err:
            _LOGGER.debug("Optional Lovelace resource registration skipped: %s", err)

    if hass.state == CoreState.running:
        hass.async_create_task(_register_lovelace_resource())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_lovelace_resource)


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

    async def handle_send_notification(call: ServiceCall):
        await hub.async_handle_notification_service(call)

    async def handle_send_command(call: ServiceCall):
        command = call.data.get("command")
        payload = call.data.get("payload", {})
        if command:
            cmd_payload = {"Command": command, **payload}
            await hub.pixoo_device.send_command(cmd_payload)
            if command == "Channel/SetIndex":
                sel_idx = payload.get("SelectIndex")
                if sel_idx is not None:
                    hub.update_channel_sensor_attribute(sel_idx)
            elif command == "Channel/SetBrightness":
                bri = payload.get("Brightness")
                if bri is not None:
                    hub.update_brightness_sensor_attribute(bri)
            elif command == "Channel/OnOffScreen":
                on_off = payload.get("OnOff")
                if on_off is not None:
                    hub.update_power_sensor_attribute(on_off == 1)

    hass.services.async_register(
        DOMAIN,
        "send_notification",
        handle_send_notification
    )

    hass.services.async_register(
        DOMAIN,
        "send_command",
        handle_send_command
    )

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
        hass.data[DOMAIN].pop(entry.entry_id)

    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "send_notification")
        hass.services.async_remove(DOMAIN, "send_command")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass, config_entry):
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating Pixoo64 entry from version %s to 1.4", config_entry.version)

    if config_entry.version < 1.4:
        hass.config_entries.async_update_entry(config_entry, version=1.4)

    return True