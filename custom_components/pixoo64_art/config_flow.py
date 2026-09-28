"""Config flow for Pixoo64 Media Album Art."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import aiohttp

from .const import (
    DOMAIN, CONF_PIXOO_IP, CONF_MEDIA_PLAYER, CONF_POLLINATIONS_KEY,
    CONF_SPOTIFY_CLIENT_ID, CONF_SPOTIFY_CLIENT_SECRET,
    CONF_MUSICBRAINZ_ENABLED, CONF_WLED_IP, CONF_LIGHT_ENTITY
)

class Pixoo64ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pixoo64."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors = {}

        if user_input is not None:
            # Validate Pixoo IP before saving
            ip_address = user_input[CONF_PIXOO_IP]
            test_url = f"http://{ip_address}:80/post"
            try:
                async with aiohttp.ClientSession() as session:
                    # Simple ping to check if the device responds
                    async with session.post(test_url, json={"Command": "Channel/GetIndex"}, timeout=3) as response:
                        if response.status == 200:
                            return self.async_create_entry(title="Pixoo64 Album Art", data=user_input)
                        else:
                            errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

        # The form schema (Required fields only)
        data_schema = vol.Schema({
            vol.Required(CONF_PIXOO_IP): str,
            vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for configuring APIs."""
        return Pixoo64OptionsFlowHandler(config_entry)


class Pixoo64OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for advanced settings."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        # Advanced options schema
        options_schema = vol.Schema({
            vol.Optional(CONF_SPOTIFY_CLIENT_ID, default=options.get(CONF_SPOTIFY_CLIENT_ID, "")): str,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET, default=options.get(CONF_SPOTIFY_CLIENT_SECRET, "")): str,
            vol.Optional(CONF_POLLINATIONS_KEY, default=options.get(CONF_POLLINATIONS_KEY, "")): str,
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=options.get(CONF_MUSICBRAINZ_ENABLED, True)): bool,
            vol.Optional(CONF_LIGHT_ENTITY, default=options.get(CONF_LIGHT_ENTITY, "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light")
            ),
            vol.Optional(CONF_WLED_IP, default=options.get(CONF_WLED_IP, "")): str,
        })

        return self.async_show_form(step_id="init", data_schema=options_schema)