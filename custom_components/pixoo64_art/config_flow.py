"""Config flow for Pixoo64 Media Album Art."""
import logging
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

_LOGGER = logging.getLogger(__name__)

AI_MODELS = [
    selector.SelectOptionDict(value="flux", label="Flux (Recommended / High Quality)"),
    selector.SelectOptionDict(value="turbo", label="Turbo (Fastest)"),
    selector.SelectOptionDict(value="openai/gpt-image-1.5", label="OpenAI GPT 1.5"),
    selector.SelectOptionDict(value="google/gemini-3.1-flash-image", label="Google Gemini Flash"),
    selector.SelectOptionDict(value="krea/krea-2-medium", label="Krea 2 Medium"),
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

    # Validate Spotify Pair
    s_id = str(user_input.get(CONF_SPOTIFY_CLIENT_ID) or "").strip()
    s_sec = str(user_input.get(CONF_SPOTIFY_CLIENT_SECRET) or "").strip()
    if s_id and not s_sec:
        errors[CONF_SPOTIFY_CLIENT_SECRET] = "spotify_secret_required"
    elif s_sec and not s_id:
        errors[CONF_SPOTIFY_CLIENT_ID] = "spotify_id_required"

    # Validate Tidal Pair
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
        """Fetch devices from Divoom Cloud LAN API."""
        self._discovered_devices = {}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://app.divoom-gz.com/Device/ReturnSameLANDevice", timeout=5) as response:
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

    # --- STEP 1: DEVICE & MEDIA PLAYER ---
    async def async_step_user(self, user_input=None):
        errors = {}

        if self._discovered_devices is None:
            await self._discover_devices()

        if user_input is not None:
            ip_address = user_input[CONF_PIXOO_IP]

            if ip_address == "manual":
                self._user_data.update(user_input)
                return await self.async_step_manual()

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"http://{ip_address}:80/post", json={"Command": "Channel/GetIndex"}, timeout=4) as response:
                        if response.status == 200:
                            self._user_data.update(user_input)
                            return await self.async_step_lights()
                        else:
                            errors["base"] = "cannot_connect"
            except Exception:
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
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            ip_address = user_input[CONF_PIXOO_IP]
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"http://{ip_address}:80/post", json={"Command": "Channel/GetIndex"}, timeout=4) as response:
                        if response.status == 200:
                            self._user_data[CONF_PIXOO_IP] = ip_address
                            return await self.async_step_lights()
                        else:
                            errors["base"] = "cannot_connect"
            except Exception:
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

        # Fields grouped logically by service
        schema = vol.Schema({
            # 1. AI Generation
            vol.Optional("ai_model", default="flux"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=AI_MODELS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_POLLINATIONS_KEY): PASSWORD_SELECTOR,

            # 2. MusicBrainz (Free open-source)
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=True): selector.BooleanSelector(),

            # 3. Spotify
            vol.Optional(CONF_SPOTIFY_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): PASSWORD_SELECTOR,

            # 4. TIDAL
            vol.Optional(CONF_TIDAL_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): PASSWORD_SELECTOR,

            # 5. Last.fm
            vol.Optional(CONF_LASTFM_KEY): PASSWORD_SELECTOR,

            # 6. Discogs
            vol.Optional(CONF_DISCOGS_TOKEN): PASSWORD_SELECTOR,
        })

        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="apis", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Pixoo64OptionsFlowHandler(config_entry)


class Pixoo64OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            errors = _validate_api_credentials(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        data = self._config_entry.data

        def get_val(key, default=""):
            return options.get(key, data.get(key, default))

        base_schema = {
            # Sensor
            vol.Optional(CONF_TEMPERATURE_ENTITY, description={"suggested_value": get_val(CONF_TEMPERATURE_ENTITY, None)}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),

            # Lights
            vol.Optional(CONF_LIGHT_ENTITY, description={"suggested_value": get_val(CONF_LIGHT_ENTITY, [])}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP, description={"suggested_value": get_val(CONF_WLED_IP, "")}): TEXT_SELECTOR,
            vol.Optional("only_at_night", default=get_val("only_at_night", True)): selector.BooleanSelector(),

            # AI
            vol.Optional("ai_model", default=get_val("ai_model", "flux")):
                selector.SelectSelector(selector.SelectSelectorConfig(options=AI_MODELS, mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_POLLINATIONS_KEY, description={"suggested_value": get_val(CONF_POLLINATIONS_KEY, "")}): PASSWORD_SELECTOR,

            # MusicBrainz
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=get_val(CONF_MUSICBRAINZ_ENABLED, True)): selector.BooleanSelector(),

            # Spotify
            vol.Optional(CONF_SPOTIFY_CLIENT_ID, description={"suggested_value": get_val(CONF_SPOTIFY_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET, description={"suggested_value": get_val(CONF_SPOTIFY_CLIENT_SECRET, "")}): PASSWORD_SELECTOR,

            # TIDAL
            vol.Optional(CONF_TIDAL_CLIENT_ID, description={"suggested_value": get_val(CONF_TIDAL_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET, description={"suggested_value": get_val(CONF_TIDAL_CLIENT_SECRET, "")}): PASSWORD_SELECTOR,

            # Last.fm
            vol.Optional(CONF_LASTFM_KEY, description={"suggested_value": get_val(CONF_LASTFM_KEY, "")}): PASSWORD_SELECTOR,

            # Discogs
            vol.Optional(CONF_DISCOGS_TOKEN, description={"suggested_value": get_val(CONF_DISCOGS_TOKEN, "")}): PASSWORD_SELECTOR,
        }

        schema = vol.Schema(base_schema)
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)