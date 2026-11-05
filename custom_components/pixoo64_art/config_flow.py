"""Config flow and Options flow (with cache controls) for Pixoo64 Media Album Art."""
import logging
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AI_TIER_FREE,
    AI_TIER_MODELS,
    CONF_AI_TIER,
    CONF_AUDIODB_ENABLED,
    CONF_CHART_SIZE_LIMIT,
    CONF_CHART_SLIDE_DURATION,
    CONF_CLEAR_CACHE_TRIGGER,
    CONF_DISCOGS_TOKEN,
    CONF_FIRST_DAY_OF_WEEK,
    CONF_INTERNET_ARCHIVE,
    CONF_LASTFM_KEY,
    CONF_LIGHT_ENTITY,
    CONF_MAX_CACHED_ALBUMS,
    CONF_MEDIA_PLAYER,
    CONF_MUSICBRAINZ_ENABLED,
    CONF_PERSISTENT_CACHE_ENABLED,
    CONF_PIXOO_IP,
    CONF_PLAYLIST_PREFETCH,
    CONF_POLLINATIONS_KEY,
    CONF_PREFETCH_ENABLED,
    CONF_SPOTIFY_CLIENT_ID,
    CONF_SPOTIFY_CLIENT_SECRET,
    CONF_TEMPERATURE_ENTITY,
    CONF_TIDAL_CLIENT_ID,
    CONF_TIDAL_CLIENT_SECRET,
    CONF_TV_MODE,
    CONF_WLED_IP,
    DEFAULT_CHART_SIZE_LIMIT,
    DEFAULT_CHART_SLIDE_DURATION,
    DEFAULT_FIRST_DAY_OF_WEEK,
    DEFAULT_MAX_CACHED_ALBUMS,
    DEFAULT_PERSISTENT_CACHE_ENABLED,
    DOMAIN,
    FIRST_DAY_OF_WEEK_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
TEXT_SELECTOR = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT))


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

    p_key = str(user_input.get(CONF_POLLINATIONS_KEY) or "").strip()
    if p_key and p_key.startswith("pk_"):
        errors[CONF_POLLINATIONS_KEY] = "pollinations_publishable_key"

    return errors


async def async_get_pollinations_models(hass, api_key: str = None, is_login: bool = False) -> list:
    """Fetch available AI models dynamically from Pollinations with optional API key."""
    from .providers.ai import async_fetch_pollinations_models
    session = async_get_clientsession(hass)
    raw_models = await async_fetch_pollinations_models(session, api_key, is_login=is_login)
    return [selector.SelectOptionDict(value=m["id"], label=m["label"]) for m in raw_models]


class Pixoo64ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2.0

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Pixoo64OptionsFlowHandler()

    def __init__(self):
        self._user_data = {}
        self._discovered_devices = None
        self._device_auth = None

    async def _discover_devices(self):
        self._discovered_devices = {}
        session = async_get_clientsession(self.hass)
        try:
            async with session.post("https://app.divoom-gz.com/Device/ReturnSameLANDevice", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ReturnCode") == 0:
                        for dev in data.get("DeviceList", []):
                            ip = dev.get("DevicePrivateIP")
                            if ip:
                                self._discovered_devices[ip] = f"{dev.get('DeviceName', 'Pixoo 64')} ({ip})"
        except Exception as e:
            _LOGGER.debug("Pixoo auto-discovery failed: %s", e)

    async def _test_connection(self, ip_address: str) -> bool:
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(f"http://{ip_address}:80/post", json={"Command": "Channel/GetIndex"}, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                return resp.status == 200
        except Exception:
            return False

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
            errors["base"] = "cannot_connect"

        options = self._discovered_devices.copy() if self._discovered_devices else {}
        options["manual"] = "Manual Entry (IP Address)"
        ip_schema = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[selector.SelectOptionDict(value=k, label=v) for k, v in options.items()],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
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
            errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="manual", data_schema=vol.Schema({vol.Required(CONF_PIXOO_IP): TEXT_SELECTOR}), errors=errors)

    async def async_step_lights(self, user_input=None):
        if user_input is not None:
            self._user_data.update(user_input)
            return await self.async_step_free_databases()
        schema = vol.Schema({
            vol.Optional(CONF_LIGHT_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(CONF_WLED_IP): TEXT_SELECTOR,
            vol.Optional("only_at_night", default=True): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="lights", data_schema=schema)

    async def async_step_free_databases(self, user_input=None):
        if user_input is not None:
            self._user_data.update(user_input)
            return await self.async_step_apis()
        schema = vol.Schema({
            vol.Optional(CONF_AUDIODB_ENABLED, default=True): selector.BooleanSelector(),
            vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=True): selector.BooleanSelector(),
            vol.Optional(CONF_INTERNET_ARCHIVE, default=True): selector.BooleanSelector(),
            vol.Optional(CONF_PREFETCH_ENABLED, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_PERSISTENT_CACHE_ENABLED, default=DEFAULT_PERSISTENT_CACHE_ENABLED): selector.BooleanSelector(),
            vol.Optional(CONF_MAX_CACHED_ALBUMS, default=DEFAULT_MAX_CACHED_ALBUMS): selector.NumberSelector(
                selector.NumberSelectorConfig(min=50, max=2000, step=50, mode=selector.NumberSelectorMode.BOX)
            ),
        })
        return self.async_show_form(step_id="free_databases", data_schema=schema)

    async def async_step_apis(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = _validate_api_credentials(user_input)
            if not errors:
                want_login = bool(user_input.get("login_pollinations", False))
                p_key = str(user_input.get(CONF_POLLINATIONS_KEY) or "").strip()

                if want_login:
                    self._device_auth = None
                    self._user_data.update(user_input)
                    return await self.async_step_pollinations_auth()
                elif p_key.startswith("sk_"):
                    user_input[CONF_AI_TIER] = AI_TIER_MODELS
                    user_input["pollinations_auth_method"] = "key"
                    user_input.pop("login_pollinations", None)
                    self._user_data.update(user_input)
                    return self.async_create_entry(title=f"Pixoo64 ({self._user_data.get(CONF_PIXOO_IP)})", data=self._user_data)
                else:
                    if user_input.get(CONF_AI_TIER) == AI_TIER_FREE:
                        user_input[CONF_POLLINATIONS_KEY] = ""
                    user_input.pop("login_pollinations", None)
                    self._user_data.update(user_input)
                    return self.async_create_entry(title=f"Pixoo64 ({self._user_data.get(CONF_PIXOO_IP)})", data=self._user_data)

        dynamic_ai_models = await async_get_pollinations_models(self.hass)
        schema = vol.Schema({
            vol.Optional(CONF_SPOTIFY_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_ID): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET): PASSWORD_SELECTOR,
            vol.Optional(CONF_LASTFM_KEY): PASSWORD_SELECTOR,
            vol.Optional(CONF_DISCOGS_TOKEN): PASSWORD_SELECTOR,
            vol.Optional("artwork_race_mode", default=False): selector.BooleanSelector(),
            vol.Optional(CONF_PLAYLIST_PREFETCH, default="Disabled"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["Disabled", "±5 Songs", "±10 Songs"], mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_AI_TIER, default=AI_TIER_FREE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=AI_TIER_FREE, label="Free Tier (No Key or Login Needed)"),
                        selector.SelectOptionDict(value=AI_TIER_MODELS, label="Model Services (Faster, Custom Models)"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_POLLINATIONS_KEY): PASSWORD_SELECTOR,
            vol.Optional("login_pollinations", default=False): selector.BooleanSelector(),
            vol.Optional("ai_model", default="black-forest-labs/flux.1-schnell"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=dynamic_ai_models, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })
        return self.async_show_form(step_id="apis", data_schema=schema, errors=errors)

    async def async_step_pollinations_auth(self, user_input=None):
        """Handle Pollinations OAuth device flow authorization."""
        errors = {}
        session = async_get_clientsession(self.hass)

        if not self._device_auth:
            from .providers.ai import async_request_device_code
            data = await async_request_device_code(session)
            if not data:
                errors["base"] = "pollinations_connect_error"
                return await self.async_step_apis()
            self._device_auth = data

        if user_input is not None:
            if user_input.get("cancel_login"):
                self._device_auth = None
                self._user_data[CONF_AI_TIER] = AI_TIER_FREE
                self._user_data[CONF_POLLINATIONS_KEY] = ""
                self._user_data.pop("login_pollinations", None)
                return self.async_create_entry(title=f"Pixoo64 ({self._user_data.get(CONF_PIXOO_IP)})", data=self._user_data)

            from .providers.ai import async_exchange_device_token
            token, err = await async_exchange_device_token(session, self._device_auth.get("device_code", ""))
            if token and token.startswith("sk_"):
                self._user_data[CONF_POLLINATIONS_KEY] = token
                self._user_data[CONF_AI_TIER] = AI_TIER_MODELS
                self._user_data["pollinations_auth_method"] = "login"
                self._user_data.pop("login_pollinations", None)
                self._device_auth = None
                return self.async_create_entry(title=f"Pixoo64 ({self._user_data.get(CONF_PIXOO_IP)})", data=self._user_data)
            elif err == "authorization_pending":
                errors["base"] = "pollinations_auth_pending"
            elif err == "expired_token":
                errors["base"] = "pollinations_auth_expired"
                self._device_auth = None
            else:
                errors["base"] = "pollinations_auth_failed"

        url = self._device_auth.get("verification_uri_complete") or "https://enter.pollinations.ai/device"
        code = self._device_auth.get("user_code", "")

        schema = vol.Schema({
            vol.Optional("cancel_login", default=False): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="pollinations_auth",
            data_schema=schema,
            description_placeholders={
                "url": url,
                "code": code,
            },
            errors=errors,
        )


class Pixoo64OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self):
        self._ai_models_cache = []
        self._device_auth = None
        self._saved_options = {}

    async def async_step_init(self, user_input=None):
        errors = {}
        entry = self.config_entry
        options, data = entry.options, entry.data

        def get_val(key, default=""):
            return options.get(key, data.get(key, default))

        cleaned_input = {}
        if user_input is not None:
            for k, v in user_input.items():
                if isinstance(v, dict):
                    cleaned_input.update(v)
                else:
                    cleaned_input[k] = v

            s_id = str(cleaned_input.get(CONF_SPOTIFY_CLIENT_ID) or "").strip()
            s_sec = str(cleaned_input.get(CONF_SPOTIFY_CLIENT_SECRET) or "").strip()
            if not s_id:
                cleaned_input[CONF_SPOTIFY_CLIENT_ID] = ""
                cleaned_input[CONF_SPOTIFY_CLIENT_SECRET] = ""
            elif not s_sec:
                cleaned_input[CONF_SPOTIFY_CLIENT_SECRET] = get_val(CONF_SPOTIFY_CLIENT_SECRET, "")

            t_id = str(cleaned_input.get(CONF_TIDAL_CLIENT_ID) or "").strip()
            t_sec = str(cleaned_input.get(CONF_TIDAL_CLIENT_SECRET) or "").strip()
            if not t_id:
                cleaned_input[CONF_TIDAL_CLIENT_ID] = ""
                cleaned_input[CONF_TIDAL_CLIENT_SECRET] = ""
            elif not t_sec:
                cleaned_input[CONF_TIDAL_CLIENT_SECRET] = get_val(CONF_TIDAL_CLIENT_SECRET, "")

            for s_key in (CONF_POLLINATIONS_KEY, CONF_LASTFM_KEY, CONF_DISCOGS_TOKEN):
                val = str(cleaned_input.get(s_key) or "").strip()
                if val.lower() in ("delete", "remove", "clear", "none", "-"):
                    cleaned_input[s_key] = ""
                elif not val:
                    cleaned_input[s_key] = get_val(s_key, "")

            if CONF_PLAYLIST_PREFETCH not in cleaned_input:
                cleaned_input[CONF_PLAYLIST_PREFETCH] = get_val(CONF_PLAYLIST_PREFETCH, "Disabled")
            cleaned_input[CONF_PREFETCH_ENABLED] = cleaned_input[CONF_PLAYLIST_PREFETCH] != "Disabled"
            if "artwork_race_mode" not in cleaned_input:
                cleaned_input["artwork_race_mode"] = get_val("artwork_race_mode", False)

            if cleaned_input.get(CONF_CLEAR_CACHE_TRIGGER, False):
                hub = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if hub and hasattr(hub, "async_clear_cache"):
                    await hub.async_clear_cache(scope="all")
            cleaned_input.pop(CONF_CLEAR_CACHE_TRIGGER, None)

            errors = _validate_api_credentials(cleaned_input)

            want_login = bool(cleaned_input.get("login_pollinations", False))
            raw_key_input = str(user_input.get("ai_section", {}).get(CONF_POLLINATIONS_KEY) or "").strip()

            if want_login and not errors:
                self._device_auth = None
                self._saved_options = cleaned_input
                return await self.async_step_pollinations_auth()
            elif raw_key_input.startswith("sk_"):
                cleaned_input[CONF_POLLINATIONS_KEY] = raw_key_input
                cleaned_input[CONF_AI_TIER] = AI_TIER_MODELS
                cleaned_input["pollinations_auth_method"] = "key"
                cleaned_input.pop("login_pollinations", None)
            else:
                cleaned_input.pop("login_pollinations", None)

            if cleaned_input.get("reload_ai_models", False):
                api_key = cleaned_input.get(CONF_POLLINATIONS_KEY) or get_val(CONF_POLLINATIONS_KEY, "")
                is_login = (cleaned_input.get("pollinations_auth_method") or get_val("pollinations_auth_method", "key")) == "login"
                self._ai_models_cache = await async_get_pollinations_models(self.hass, api_key=api_key, is_login=is_login)
                cleaned_input["reload_ai_models"] = False
                return await self._show_options_form(cleaned_input, errors)

            if not errors:
                cleaned_input.pop("reload_ai_models", None)
                return self.async_create_entry(title="", data=cleaned_input)

        return await self._show_options_form(cleaned_input if user_input else None, errors)

    async def async_step_pollinations_auth(self, user_input=None):
        """Handle Pollinations OAuth device flow authorization in options."""
        errors = {}
        session = async_get_clientsession(self.hass)

        if not self._device_auth:
            from .providers.ai import async_request_device_code
            data = await async_request_device_code(session)
            if not data:
                errors["base"] = "pollinations_connect_error"
                return await self._show_options_form(self._saved_options, errors)
            self._device_auth = data

        if user_input is not None:
            if user_input.get("cancel_login"):
                self._device_auth = None
                self._saved_options[CONF_AI_TIER] = AI_TIER_FREE
                self._saved_options.pop("login_pollinations", None)
                return self.async_create_entry(title="", data=self._saved_options)

            from .providers.ai import async_exchange_device_token
            token, err = await async_exchange_device_token(session, self._device_auth.get("device_code", ""))
            if token and token.startswith("sk_"):
                self._saved_options[CONF_POLLINATIONS_KEY] = token
                self._saved_options[CONF_AI_TIER] = AI_TIER_MODELS
                self._saved_options["pollinations_auth_method"] = "login"
                self._saved_options.pop("login_pollinations", None)
                self._device_auth = None
                return self.async_create_entry(title="", data=self._saved_options)
            elif err == "authorization_pending":
                errors["base"] = "pollinations_auth_pending"
            elif err == "expired_token":
                errors["base"] = "pollinations_auth_expired"
                self._device_auth = None
            else:
                errors["base"] = "pollinations_auth_failed"

        url = self._device_auth.get("verification_uri_complete") or "https://enter.pollinations.ai/device"
        code = self._device_auth.get("user_code", "")

        schema = vol.Schema({
            vol.Optional("cancel_login", default=False): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="pollinations_auth",
            data_schema=schema,
            description_placeholders={
                "url": url,
                "code": code,
            },
            errors=errors,
        )

    async def _show_options_form(self, current_values: dict = None, errors: dict = None):
        entry = self.config_entry
        options, data = entry.options, entry.data

        def get_current(key, default=""):
            if current_values and key in current_values and current_values[key] is not None:
                return current_values[key]
            return options.get(key, data.get(key, default))

        cur_auth_method = get_current("pollinations_auth_method", "key")
        is_login = (cur_auth_method == "login")
        if not self._ai_models_cache:
            self._ai_models_cache = await async_get_pollinations_models(
                self.hass,
                api_key=get_current(CONF_POLLINATIONS_KEY, ""),
                is_login=is_login,
            )

        cur_ai_model = get_current("ai_model", "black-forest-labs/flux.1-schnell")
        avail_model_values = [
            (opt.value if hasattr(opt, "value") else opt.get("value", ""))
            for opt in self._ai_models_cache
        ]
        if cur_ai_model and cur_ai_model not in avail_model_values:
            self._ai_models_cache.insert(
                0,
                selector.SelectOptionDict(
                    value=cur_ai_model,
                    label=f"{cur_ai_model.split('/')[-1].capitalize()} (Saved)",
                ),
            )

        cur_key = get_current(CONF_POLLINATIONS_KEY, "")
        cur_tier = get_current(CONF_AI_TIER, AI_TIER_MODELS if str(cur_key).startswith("sk_") else AI_TIER_FREE)

        streaming_schema = {
            vol.Optional(CONF_SPOTIFY_CLIENT_ID, description={"suggested_value": get_current(CONF_SPOTIFY_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_SPOTIFY_CLIENT_SECRET, description={"suggested_value": get_current(CONF_SPOTIFY_CLIENT_SECRET, "")}): PASSWORD_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_ID, description={"suggested_value": get_current(CONF_TIDAL_CLIENT_ID, "")}): TEXT_SELECTOR,
            vol.Optional(CONF_TIDAL_CLIENT_SECRET, description={"suggested_value": get_current(CONF_TIDAL_CLIENT_SECRET, "")}): PASSWORD_SELECTOR,
            vol.Optional(CONF_LASTFM_KEY, description={"suggested_value": get_current(CONF_LASTFM_KEY, "")}): PASSWORD_SELECTOR,
            vol.Optional(CONF_DISCOGS_TOKEN, description={"suggested_value": get_current(CONF_DISCOGS_TOKEN, "")}): PASSWORD_SELECTOR,
            vol.Optional("artwork_race_mode", default=get_current("artwork_race_mode", False)): selector.BooleanSelector(),
            vol.Optional(CONF_PLAYLIST_PREFETCH, default=get_current(CONF_PLAYLIST_PREFETCH, "Disabled")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["Disabled", "±5 Songs", "±10 Songs"], mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        }

        schema = vol.Schema({
            vol.Required("media_section"): section(vol.Schema({
                vol.Optional(CONF_MEDIA_PLAYER, description={"suggested_value": get_current(CONF_MEDIA_PLAYER, None)}): selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player")),
                vol.Optional(CONF_TEMPERATURE_ENTITY, description={"suggested_value": get_current(CONF_TEMPERATURE_ENTITY, None)}): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
                vol.Optional(CONF_TV_MODE, default=get_current(CONF_TV_MODE, False)): selector.BooleanSelector(),
                vol.Optional(CONF_PREFETCH_ENABLED, default=get_current(CONF_PREFETCH_ENABLED, False)): selector.BooleanSelector(),
            }), {"collapsed": False}),
            vol.Required("storage_section"): section(vol.Schema({
                vol.Optional(CONF_PERSISTENT_CACHE_ENABLED, default=get_current(CONF_PERSISTENT_CACHE_ENABLED, DEFAULT_PERSISTENT_CACHE_ENABLED)): selector.BooleanSelector(),
                vol.Optional(CONF_MAX_CACHED_ALBUMS, default=get_current(CONF_MAX_CACHED_ALBUMS, DEFAULT_MAX_CACHED_ALBUMS)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=50, max=2000, step=50, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_FIRST_DAY_OF_WEEK, default=get_current(CONF_FIRST_DAY_OF_WEEK, DEFAULT_FIRST_DAY_OF_WEEK)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=FIRST_DAY_OF_WEEK_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_CHART_SLIDE_DURATION, default=get_current(CONF_CHART_SLIDE_DURATION, DEFAULT_CHART_SLIDE_DURATION)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=2, max=10, step=1, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(CONF_CHART_SIZE_LIMIT, default=get_current(CONF_CHART_SIZE_LIMIT, DEFAULT_CHART_SIZE_LIMIT)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=3, max=20, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_CLEAR_CACHE_TRIGGER, default=False): selector.BooleanSelector(),
            }), {"collapsed": False}),
            vol.Required("ambient_section"): section(vol.Schema({
                vol.Optional(CONF_LIGHT_ENTITY, description={"suggested_value": get_current(CONF_LIGHT_ENTITY, [])}): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Optional(CONF_WLED_IP, description={"suggested_value": get_current(CONF_WLED_IP, "")}): TEXT_SELECTOR,
                vol.Optional("only_at_night", default=get_current("only_at_night", True)): selector.BooleanSelector(),
            }), {"collapsed": False}),
            vol.Required("free_databases_section"): section(vol.Schema({
                vol.Optional(CONF_AUDIODB_ENABLED, default=get_current(CONF_AUDIODB_ENABLED, True)): selector.BooleanSelector(),
                vol.Optional(CONF_MUSICBRAINZ_ENABLED, default=get_current(CONF_MUSICBRAINZ_ENABLED, True)): selector.BooleanSelector(),
                vol.Optional(CONF_INTERNET_ARCHIVE, default=get_current(CONF_INTERNET_ARCHIVE, True)): selector.BooleanSelector(),
            }), {"collapsed": False}),
            vol.Required("streaming_api_section"): section(vol.Schema(streaming_schema), {"collapsed": False}),
            vol.Required("ai_section"): section(vol.Schema({
                vol.Optional(CONF_AI_TIER, default=cur_tier): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=AI_TIER_FREE, label="Free Tier (No Key or Login Needed)"),
                            selector.SelectOptionDict(value=AI_TIER_MODELS, label="Model Services (Faster, Custom Models)"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_POLLINATIONS_KEY, description={"suggested_value": cur_key}): PASSWORD_SELECTOR,
                vol.Optional("login_pollinations", default=False): selector.BooleanSelector(),
                vol.Optional("ai_model", default=get_current("ai_model", "black-forest-labs/flux.1-schnell")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._ai_models_cache, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional("reload_ai_models", default=False): selector.BooleanSelector(),
            }), {"collapsed": False}),
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors or {})
