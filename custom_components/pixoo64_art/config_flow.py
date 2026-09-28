"""Config flow for Pixoo64 Media Album Art."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import aiohttp

from .const import (
    DOMAIN, CONF_PIXOO_IP, CONF_MEDIA_PLAYER, CONF_POLLINATIONS_KEY,
    CONF_SPOTIFY_CLIENT_ID, CONF_SPOTIFY_CLIENT_SECRET,
    CONF_TIDAL_CLIENT_ID, CONF_TIDAL_CLIENT_SECRET,
    CONF_LASTFM_KEY, CONF_DISCOGS_TOKEN,
    CONF_MUSICBRAINZ_ENABLED, CONF_WLED_IP, CONF_LIGHT_ENTITY, CONF_TEMPERATURE_ENTITY
)

class Pixoo64ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        """Initialize the config flow securely."""
        self._user_data = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            ip_address = user_input[CONF_PIXOO_IP]
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"http://{ip_address}:80/post", json={"Command": "Channel/GetIndex"}, timeout=3) as response:
                        if response.status == 200:
                            self._user_data = user_input
                            return await self.async_step_advanced()
                        else:
                            errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema({
            vol.Required(CONF_PIXOO_IP): str,
            vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player")),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_advanced(self, user_input=None):
        if user_input is not None:
            final_data = {**self._user_data, **user_input}
            return self.async_create_entry(title="Pixoo64 Album Art", data=final_data)

        schema = vol.Schema({
            vol.Optional(CONF_SPOTIFY_CLIENT_ID): str,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): str,
            vol.Optional(CONF_TIDAL_CLIENT_ID): str,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): str,
            vol.Optional(CONF_LASTFM_KEY): str,
            vol.Optional(CONF_DISCOGS_TOKEN): str,
            vol.Optional(CONF_POLLINATIONS_KEY): str,
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=True): bool,
            vol.Optional(CONF_TEMPERATURE_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
            vol.Optional(CONF_LIGHT_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP): str,
        })
        return self.async_show_form(step_id="advanced", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Pixoo64OptionsFlowHandler(config_entry)


class Pixoo64OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        data = self._config_entry.data
        
        def get_val(key, default=""):
            return options.get(key, data.get(key, default))

        schema = {}
        schema[vol.Optional(CONF_SPOTIFY_CLIENT_ID, default=get_val(CONF_SPOTIFY_CLIENT_ID))] = str
        schema[vol.Optional(CONF_SPOTIFY_CLIENT_SECRET, default=get_val(CONF_SPOTIFY_CLIENT_SECRET))] = str
        schema[vol.Optional(CONF_TIDAL_CLIENT_ID, default=get_val(CONF_TIDAL_CLIENT_ID))] = str
        schema[vol.Optional(CONF_TIDAL_CLIENT_SECRET, default=get_val(CONF_TIDAL_CLIENT_SECRET))] = str
        schema[vol.Optional(CONF_LASTFM_KEY, default=get_val(CONF_LASTFM_KEY))] = str
        schema[vol.Optional(CONF_DISCOGS_TOKEN, default=get_val(CONF_DISCOGS_TOKEN))] = str
        schema[vol.Optional(CONF_POLLINATIONS_KEY, default=get_val(CONF_POLLINATIONS_KEY))] = str
        schema[vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=get_val(CONF_MUSICBRAINZ_ENABLED, True))] = bool
        
        temp_val = get_val(CONF_TEMPERATURE_ENTITY, None)
        if temp_val: 
            schema[vol.Optional(CONF_TEMPERATURE_ENTITY, default=temp_val)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))
        else: 
            schema[vol.Optional(CONF_TEMPERATURE_ENTITY)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))

        light_val = get_val(CONF_LIGHT_ENTITY, [])
        if light_val: 
            schema[vol.Optional(CONF_LIGHT_ENTITY, default=light_val)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True))
        else: 
            schema[vol.Optional(CONF_LIGHT_ENTITY)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True))
        
        schema[vol.Optional(CONF_WLED_IP, default=get_val(CONF_WLED_IP))] = str

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
