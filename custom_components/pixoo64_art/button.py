"""Button platform for Pixoo64 Media Album Art."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import PixooHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pixoo64 button entities."""
    hub: PixooHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PixooClearCacheButton(hub, entry),
    ])


class PixooBaseButton(ButtonEntity):
    """Base button entity for Pixoo64."""

    def __init__(self, hub: PixooHub, entry: ConfigEntry) -> None:
        self.hub = hub
        self.entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub.pixoo_ip)},
            name="Pixoo64 Media Display",
            manufacturer="Divoom",
            model="Pixoo 64",
        )


class PixooClearCacheButton(PixooBaseButton):
    """Button entity to manually purge persistent and in-memory Pixoo caches."""

    _attr_icon = "mdi:broom"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: PixooHub, entry: ConfigEntry) -> None:
        super().__init__(hub, entry)
        self._attr_name = "Clear Pixoo Cache"
        self._attr_unique_id = f"{entry.entry_id}_clear_cache"

    async def async_press(self) -> None:
        """Handle the button press to purge cached artwork and slider frames."""
        await self.hub.async_clear_cache(scope="all")
