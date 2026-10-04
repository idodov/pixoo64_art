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
    CONF_MUSICBRAINZ_ENABLED, CONF_INTERNET_ARCHIVE, CONF_WLED_IP, CONF_LIGHT_ENTITY, CONF_TEMPERATURE_ENTITY,
    CONF_PLAYLIST_PREFETCH
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
TEXT_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
)

def _validate_api_credentials(user_input: dict) -> dict:
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

async def async_get_pollinations_models(hass) -> list:
    fallback_models = [
        selector.SelectOptionDict(value="black-forest-labs/flux.1-schnell", label="FLUX.1 Schnell (Black Forest Labs)"),
    ]
    try:
        session = async_get_clientsession(hass)
        async with session.get("https://gen.pollinations.ai/models", timeout=4) as response:
            if response.status == 200:
                data = await response.json()
                parsed_models = []
                for model in data:
                    if model.get("category") == "image" or "image" in model.get("output_modalities", []):
                        model_id = model.get("name")
                        if not model_id: continue
                        title = model.get("title", model_id)
                        publisher = model.get("publisher", "Unknown")
                        pricing = model.get("pricing", {})
                        try: cost = float(pricing.get("completionImageTokens", 0))
                        except (ValueError, TypeError): cost = 0.0
                        cost_display = "Free" if cost == 0 else f"{cost:.8f}".rstrip('0').rstrip('.')
                        parsed_models.append({"id": model_id, "label": f"{title} ({publisher}) | 💰 {cost_display}", "cost": cost})
                parsed_models.sort(key=lambda x: x["cost"])
                models = [selector.SelectOptionDict(value=m["id"], label=m["label"]) for m in parsed_models]
                return models if models else fallback_models
    except Exception as e:
        _LOGGER.warning("Failed to fetch dynamic AI models, using fallback: %s", e)
    return fallback_models

class Pixoo64ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._user_data = {}
        self._discovered_devices = None

    async def _discover_devices(self):
        self._discovered_devices = {}
        session = async_get_clientsession(self.hass)
        try:
            async with session.post("https://app.divoom-gz.com/Device/ReturnSameLANDevice", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ReturnCode") == 0:
                        for dev in data.get("DeviceList", []):
                            ip = dev.get("DevicePrivateIP")
                            name = dev.get("DeviceName", "Pixoo 64")
                            if ip: self._discovered_devices[ip] = f"{name} ({ip})"
        except Exception as e:
            _LOGGER.debug("Pixoo auto-discovery failed: %s", e)

    async def _test_connection(self, ip_address: str) -> bool:
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(f"http://{ip_address}:80/post", json={"Command": "Channel/GetIndex"}, timeout=aiohttp.ClientTimeout(total=4)) as response:
                return response.status == 200
        except Exception:
            return False

    async def async_step_user(self, user_input=None):
        errors = {}
        if self._discovered_devices is None: await self._discover_devices()

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

        options = self._discovered_devices.copy() if self._discovered_devices else {}
        options["manual"] = "Manual Entry (IP Address)"
        ip_schema = selector.SelectSelector(selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=k, label=v) for k, v in options.items()],
            mode=selector.SelectSelectorMode.DROPDOWN
        ))

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

        data_schema = vol.Schema({vol.Required(CONF_PIXOO_IP): TEXT_SELECTOR})
        return self.async_show_form(step_id="manual", data_schema=data_schema, errors=errors)

    async def async_step_lights(self, user_input=None):
        if user_input is not None:
            self._user_data.update(user_input)
            return await self.async_step_apis()

        schema = vol.Schema({
            vol.Optional("osd_overlay", default="Disabled"): selector.SelectSelector(selector.SelectSelectorConfig(options=["Enabled", "Disabled"], mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional("pause_timeout", default="15s"): selector.SelectSelector(selector.SelectSelectorConfig(options=["5s", "15s", "30s", "60s", "Never"], mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional("volume_osd_duration", default="2s"): selector.SelectSelector(selector.SelectSelectorConfig(options=["1s", "2s", "3s", "5s"], mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_LIGHT_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP): TEXT_SELECTOR,
            vol.Optional("only_at_night", default=True): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="lights", data_schema=schema)

    async def async_step_apis(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = _validate_api_credentials(user_input)
            if not errors:
                self._user_data.update(user_input)
                return self.async_create_entry(title=f"Pixoo64 ({self._user_data.get(CONF_PIXOO_IP)})", data=self._user_data)

        dynamic_ai_models = await async_get_pollinations_models(self.hass)
        schema = vol.Schema({
            vol.Optional("ai_model", default="black-forest-labs/flux.1-schnell"): selector.SelectSelector(selector.SelectSelectorConfig(options=dynamic_ai_models, mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_POLLINATIONS_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=True): selector.BooleanSelector(),
            vol.Optional(CONF_INTERNET_ARCHIVE, default=True): selector.BooleanSelector(),
            vol.Optional(CONF_SPOTIFY_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_LASTFM_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_DISCOGS_TOKEN): PASSWORD_SELECTOR,
            vol.Optional(CONF_PLAYLIST_PREFETCH, default="Disabled"): selector.SelectSelector(selector.SelectSelectorConfig(options=["Disabled", "±5 Songs", "±10 Songs"], mode=selector.SelectSelectorMode.DROPDOWN)),
        })
        return self.async_show_form(step_id="apis", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Pixoo64OptionsFlowHandler()


class Pixoo64OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        entry = self.config_entry
        options = entry.options
        data = entry.data

        def get_val(key, default=""):
            return options.get(key, data.get(key, default))

        if user_input is not None:
            cleaned_input = dict(user_input)

            # 1. Spotify Pair Logic: Client ID is the master anchor
            s_id = str(cleaned_input.get(CONF_SPOTIFY_CLIENT_ID) or "").strip()
            s_sec = str(cleaned_input.get(CONF_SPOTIFY_CLIENT_SECRET) or "").strip()
            if not s_id:
                cleaned_input[CONF_SPOTIFY_CLIENT_ID] = ""
                cleaned_input[CONF_SPOTIFY_CLIENT_SECRET] = ""
            else:
                if not s_sec:
                    cleaned_input[CONF_SPOTIFY_CLIENT_SECRET] = get_val(CONF_SPOTIFY_CLIENT_SECRET, "")

            # 2. TIDAL Pair Logic: Client ID is the master anchor
            t_id = str(cleaned_input.get(CONF_TIDAL_CLIENT_ID) or "").strip()
            t_sec = str(cleaned_input.get(CONF_TIDAL_CLIENT_SECRET) or "").strip()
            if not t_id:
                cleaned_input[CONF_TIDAL_CLIENT_ID] = ""
                cleaned_input[CONF_TIDAL_CLIENT_SECRET] = ""
            else:
                if not t_sec:
                    cleaned_input[CONF_TIDAL_CLIENT_SECRET] = get_val(CONF_TIDAL_CLIENT_SECRET, "")

            # 3. Single Key Logic (Pollinations, Last.fm, Discogs)
            single_secret_keys = [
                CONF_POLLINATIONS_KEY,
                CONF_LASTFM_KEY,
                CONF_DISCOGS_TOKEN,
            ]
            for s_key in single_secret_keys:
                if s_key in cleaned_input:
                    val = str(cleaned_input.get(s_key) or "").strip()
                    if val.lower() in ["delete", "remove", "clear", "none", "-"]:
                        cleaned_input[s_key] = ""
                    elif not val:
                        cleaned_input[s_key] = get_val(s_key, "")

            errors = _validate_api_credentials(cleaned_input)
            if not errors:
                return self.async_create_entry(title="", data=cleaned_input)

        dynamic_ai_models = await async_get_pollinations_models(self.hass)

        has_streaming_keys = bool(
            str(get_val(CONF_SPOTIFY_CLIENT_ID, "")).strip() or 
            str(get_val(CONF_TIDAL_CLIENT_ID, "")).strip() or 
            str(get_val(CONF_DISCOGS_TOKEN, "")).strip()
        )

        base_schema = {
            vol.Optional(CONF_MEDIA_PLAYER, description={"suggested_value": get_val(CONF_MEDIA_PLAYER)}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player")),
            vol.Optional(CONF_TEMPERATURE_ENTITY, description={"suggested_value": get_val(CONF_TEMPERATURE_ENTITY, None)}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
            vol.Optional(CONF_TV_MODE, default=get_val(CONF_TV_MODE, False)): selector.BooleanSelector(),
            vol.Optional("osd_overlay", default=get_val("osd_overlay", "Disabled")):
                selector.SelectSelector(selector.SelectSelectorConfig(options=["Enabled", "Disabled"], mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional("pause_timeout", default=get_val("pause_timeout", "15s")):
                selector.SelectSelector(selector.SelectSelectorConfig(options=["5s", "15s", "30s", "60s", "Never"], mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional("volume_osd_duration", default=get_val("volume_osd_duration", "2s")):
                selector.SelectSelector(selector.SelectSelectorConfig(options=["1s", "2s", "3s", "5s"], mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_LIGHT_ENTITY, description={"suggested_value": get_val(CONF_LIGHT_ENTITY, [])}):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP, description={"suggested_value": get_val(CONF_WLED_IP, "")}): TEXT_SELECTOR,
            vol.Optional("only_at_night", default=get_val("only_at_night", True)): selector.BooleanSelector(),
            vol.Optional("ai_model", default=get_val("ai_model", "black-forest-labs/flux.1-schnell")):
                selector.SelectSelector(selector.SelectSelectorConfig(options=dynamic_ai_models, mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_POLLINATIONS_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=get_val(CONF_MUSICBRAINZ_ENABLED, True)): selector.BooleanSelector(),
            vol.Optional(CONF_INTERNET_ARCHIVE, default=get_val(CONF_INTERNET_ARCHIVE, True)): selector.BooleanSelector(),
            vol.Optional(CONF_SPOTIFY_CLIENT_ID, description={"suggested_value": get_val(CONF_SPOTIFY_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_ID, description={"suggested_value": get_val(CONF_TIDAL_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_LASTFM_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_DISCOGS_TOKEN): PASSWORD_SELECTOR,
        }

        if has_streaming_keys:
            base_schema[vol.Optional(CONF_PLAYLIST_PREFETCH, default=get_val(CONF_PLAYLIST_PREFETCH, "Disabled"))] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=["Disabled", "±5 Songs", "±10 Songs"], mode=selector.SelectSelectorMode.DROPDOWN)
            )

        schema = vol.Schema(base_schema)
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)