"""Config flow for Pixoo64 Media Album Art."""
import logging
import voluptuous as vol
import aiohttp
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN, CONF_PIXOO_IP, CONF_MEDIA_PLAYER, CONF_TV_MODE, CONF_POLLINATIONS_KEY,
    CONF_SPOTIFY_CLIENT_ID, CONF_SPOTIFY_CLIENT_SECRET,
    CONF_TIDAL_CLIENT_ID, CONF_TIDAL_CLIENT_SECRET,
    CONF_LASTFM_KEY, CONF_DISCOGS_TOKEN,
    CONF_MUSICBRAINZ_ENABLED, CONF_WLED_IP, CONF_LIGHT_ENTITY, CONF_TEMPERATURE_ENTITY
)

_LOGGER = logging.getLogger(__name__)

AI_MODELS = [
    selector.SelectOptionDict(value="black-forest-labs/flux.1-schnell", label="Flux Schnell (Fast & Balanced)"),
    selector.SelectOptionDict(value="recraft/recraft-v4.1-vector", label="Recraft Vector (Best for 64x64 LED)"),
    selector.SelectOptionDict(value="inferenceport-ai/lightning-image-turbo", label="Lightning Turbo (Fastest)"),
    selector.SelectOptionDict(value="openai/gpt-image-1-mini", label="OpenAI GPT Image Mini"),
    selector.SelectOptionDict(value="google/gemini-3.1-flash-image", label="Google Gemini Flash"),
]

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
TEXT_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
)

def _validate_api_credentials(user_input: dict) -> dict:
    """Validate that ID and Secret pairs are provided together."""
    errors = {}
    s_id = str(user_input.get(CONF_SPOTIFY_CLIENT_ID) or "").strip()
    s_sec = str(user_input.get(CONF_SPOTIFY_CLIENT_SECRET) or "").strip()
    if s_id and not s_sec:
        errors[CONF_SPOTIFY_CLIENT_SECRET] = "spotify_secret_required"
    elif s_sec and not s_id:
        errors[CONF_SPOTIFY_CLIENT_ID] = "spotify_id_required"

    t_id = str(user_input.get(CONF_TIDAL_CLIENT_ID) or "").strip()
    t_sec = str(user_input.get(CONF_TIDAL_CLIENT_SECRET) or "").strip()
    if t_id and not t_sec:
        errors[CONF_TIDAL_CLIENT_SECRET] = "tidal_secret_required"
    elif t_sec and not t_id:
        errors[CONF_TIDAL_CLIENT_ID] = "tidal_id_required"

    return errors


class Pixoo64ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._user_data = {}
        self._discovered_devices = None

    async def _discover_devices(self):
        """Fetch devices from Divoom Cloud LAN API using HA shared session."""
        self._discovered_devices = {}
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                "https://app.divoom-gz.com/Device/ReturnSameLANDevice",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ReturnCode") == 0:
                        for dev in data.get("DeviceList", []):
                            ip = dev.get("DevicePrivateIP")
                            name = dev.get("DeviceName", "Pixoo 64")
                            if ip:
                                self._discovered_devices[ip] = f"{name} ({ip})"
        except Exception as e:
            _LOGGER.debug("Pixoo auto-discovery failed: %s", e)

    async def _test_connection(self, ip_address: str) -> bool:
        """Test HTTP connection to Pixoo device."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"http://{ip_address}:80/post",
                json={"Command": "Channel/GetIndex"},
                timeout=aiohttp.ClientTimeout(total=4)
            ) as response:
                return response.status == 200
        except Exception:
            return False

    # --- STEP 1: DEVICE, MEDIA PLAYER & TV MODE ---
    async def async_step_user(self, user_input=None):
        errors = {}

        if self._discovered_devices is None:
            await self._discover_devices()

        if user_input is not None:
            ip_address = user_input[CONF_PIXOO_IP]

            if ip_address == "manual":
                self._user_data.update(user_input)
                return await self.async_step_manual()

            await self.async_set_unique_id(ip_address)
            self._abort_if_unique_id_configured()

            if await self._test_connection(ip_address):
                self._user_data.update(user_input)
                return await self.async_step_lights()
            else:
                errors["base"] = "cannot_connect"

        if self._discovered_devices:
            options = self._discovered_devices.copy()
            options["manual"] = "Manual Entry (IP Address)"
            ip_schema = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=k, label=v) for k, v in options.items()],
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        else:
            ip_schema = TEXT_SELECTOR

        data_schema = vol.Schema({
            vol.Required(CONF_PIXOO_IP): ip_schema,
            vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player")),
            vol.Optional(CONF_TEMPERATURE_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
            vol.Optional(CONF_TV_MODE, default=False): selector.BooleanSelector(),
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            ip_address = user_input[CONF_PIXOO_IP].strip()

            await self.async_set_unique_id(ip_address)
            self._abort_if_unique_id_configured()

            if await self._test_connection(ip_address):
                self._user_data[CONF_PIXOO_IP] = ip_address
                return await self.async_step_lights()
            else:
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema({
            vol.Required(CONF_PIXOO_IP): TEXT_SELECTOR,
        })
        return self.async_show_form(step_id="manual", data_schema=data_schema, errors=errors)

    # --- STEP 2: LIGHTING SYNC ---
    async def async_step_lights(self, user_input=None):
        if user_input is not None:
            self._user_data.update(user_input)
            return await self.async_step_apis()

        schema = vol.Schema({
            vol.Optional(CONF_LIGHT_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP): TEXT_SELECTOR,
            vol.Optional("only_at_night", default=True): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="lights", data_schema=schema)

    # --- STEP 3: APIS & CREDENTIALS ---
    async def async_step_apis(self, user_input=None):
        errors = {}

        if user_input is not None:
            errors = _validate_api_credentials(user_input)
            if not errors:
                self._user_data.update(user_input)
                return self.async_create_entry(
                    title=f"Pixoo64 ({self._user_data.get(CONF_PIXOO_IP)})",
                    data=self._user_data
                )

        schema = vol.Schema({
            vol.Optional("ai_model", default="flux"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=AI_MODELS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_POLLINATIONS_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=True): selector.BooleanSelector(),
            vol.Optional(CONF_SPOTIFY_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_LASTFM_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_DISCOGS_TOKEN): PASSWORD_SELECTOR,
        })

        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="apis", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Pixoo64OptionsFlowHandler()


class Pixoo64OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow with protection against password wiping."""

    async def async_step_init(self, user_input=None):
        errors = {}
        entry = self.config_entry
        options = entry.options
        data = entry.data

        def get_val(key, default=""):
            return options.get(key, data.get(key, default))

        if user_input is not None:
            cleaned_input = dict(user_input)

            secret_keys = [
                CONF_POLLINATIONS_KEY,
                CONF_SPOTIFY_CLIENT_SECRET,
                CONF_TIDAL_CLIENT_SECRET,
                CONF_LASTFM_KEY,
                CONF_DISCOGS_TOKEN,
            ]
            for s_key in secret_keys:
                val = str(cleaned_input.get(s_key) or "").strip()
                if not val:
                    existing_val = get_val(s_key, "")
                    if existing_val:
                        cleaned_input[s_key] = existing_val

            errors = _validate_api_credentials(cleaned_input)
            if not errors:
                return self.async_create_entry(title="", data=cleaned_input)

        base_schema = {
            # Media Player Selection
            vol.Optional(CONF_MEDIA_PLAYER, description={"suggested_value": get_val(CONF_MEDIA_PLAYER)}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player")),

            # Sensor
            vol.Optional(CONF_TEMPERATURE_ENTITY, description={"suggested_value": get_val(CONF_TEMPERATURE_ENTITY, None)}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),

            # TV Watching Mode (Toggle)
            vol.Optional(CONF_TV_MODE, default=get_val(CONF_TV_MODE, False)): selector.BooleanSelector(),

            # Lights
            vol.Optional(CONF_LIGHT_ENTITY, description={"suggested_value": get_val(CONF_LIGHT_ENTITY, [])}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP, description={"suggested_value": get_val(CONF_WLED_IP, "")}): TEXT_SELECTOR,
            vol.Optional("only_at_night", default=get_val("only_at_night", True)): selector.BooleanSelector(),

            # AI
            vol.Optional("ai_model", default=get_val("ai_model", "flux")):
                selector.SelectSelector(selector.SelectSelectorConfig(options=AI_MODELS, mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_POLLINATIONS_KEY): PASSWORD_SELECTOR,

            # MusicBrainz
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=get_val(CONF_MUSICBRAINZ_ENABLED, True)): selector.BooleanSelector(),

            # Spotify
            vol.Optional(CONF_SPOTIFY_CLIENT_ID, description={"suggested_value": get_val(CONF_SPOTIFY_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): PASSWORD_SELECTOR,

            # TIDAL
            vol.Optional(CONF_TIDAL_CLIENT_ID, description={"suggested_value": get_val(CONF_TIDAL_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): PASSWORD_SELECTOR,

            # Last.fm
            vol.Optional(CONF_LASTFM_KEY): PASSWORD_SELECTOR,

            # Discogs
            vol.Optional(CONF_DISCOGS_TOKEN): PASSWORD_SELECTOR,
        }

        schema = vol.Schema(base_schema)
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)