"""Home Assistant service registrations for Pixoo64 Media Album Art."""

from typing import Any
import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)

from .const import CHART_DIRECTIONS, CHART_TIMEFRAMES, CHART_TYPES, DOMAIN
from .hub import PixooHub

SERVICE_CLEAR_CACHE_SCHEMA = vol.Schema(
    {
        vol.Optional("scope", default="all"): vol.In(
            ["all", "masters", "artists", "analytics", "icons"]
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_LEADERBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional("chart_type", default="Top Tracks"): vol.In(CHART_TYPES),
        vol.Optional("timeframe", default="Weekly"): vol.In(CHART_TIMEFRAMES),
        vol.Optional("period", default="Current"): str,
        vol.Optional("limit", default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=50)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_CREATE_CHART_SCHEMA = vol.Schema(
    {
        vol.Optional("chart_type"): vol.In(CHART_TYPES),
        vol.Optional("timeframe"): vol.In(CHART_TIMEFRAMES),
        vol.Optional("period"): str,
        vol.Optional("direction"): vol.In(CHART_DIRECTIONS),
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=3, max=20)),
        vol.Optional("slide_duration"): vol.All(
            vol.Coerce(int), vol.Range(min=2, max=10)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


def _iter_hubs(hass: HomeAssistant) -> list[PixooHub]:
    """Return all active PixooHub instances registered in hass.data."""
    domain_data = hass.data.get(DOMAIN, {})
    return [v for v in domain_data.values() if isinstance(v, PixooHub)]


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all Pixoo64 domain services if not already registered."""

    async def handle_send_notification(call: ServiceCall) -> None:
        for hub in _iter_hubs(hass):
            await hub.async_handle_notification_service(call)

    async def handle_send_command(call: ServiceCall) -> None:
        command = call.data.get("command")
        payload = call.data.get("payload", {})
        if not command:
            return
        cmd_payload = {"Command": command, **payload}
        for hub in _iter_hubs(hass):
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
                    if on_off == 0 and getattr(hub, "chart_active", False):
                        await hub.async_cancel_chart(restore_view=False)
                    elif on_off == 1 and not hub.is_art_visible:
                        target_ch = 0 if getattr(hub, "last_valid_index", 0) in (4, -1) or getattr(hub, "last_valid_index", 0) < 0 else hub.last_valid_index
                        await hub.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": target_ch})
                        hub.update_channel_sensor_attribute(target_ch)
                    hub.update_power_sensor_attribute(on_off == 1)

    async def handle_clear_cache(call: ServiceCall) -> None:
        scope = call.data.get("scope", "all")
        for hub in _iter_hubs(hass):
            await hub.async_clear_cache(scope=scope)

    async def handle_create_chart(call: ServiceCall) -> ServiceResponse:
        items: list[dict[str, Any]] = []
        for hub in _iter_hubs(hass):
            items = await hub.async_create_chart(dict(call.data))
        return {"items": items}

    async def handle_cancel_chart(call: ServiceCall) -> None:
        for hub in _iter_hubs(hass):
            await hub.async_cancel_chart()

    async def handle_get_leaderboard(call: ServiceCall) -> ServiceResponse:
        chart_type = str(call.data.get("chart_type", "Top Tracks"))
        timeframe = str(call.data.get("timeframe", "Weekly"))
        period = str(call.data.get("period", "Current"))
        limit = int(call.data.get("limit", 10))
        hubs = _iter_hubs(hass)
        if not hubs:
            return {"chart_type": chart_type, "timeframe": timeframe, "period": period, "items": [], "tracks": []}

        hub = hubs[0]
        if period.lower() in ("day", "week", "month", "all", "all_time") and "timeframe" not in call.data:
            tracks = await hub.storage_manager.async_get_top_tracks(period=period, limit=limit)
            return {"period": period, "tracks": tracks, "items": tracks}

        first_dow = getattr(hub.config, "first_day_of_week", "Sunday")
        items = await hub.storage_manager.async_get_leaderboard(
            chart_type=chart_type,
            timeframe=timeframe,
            period_label=period,
            limit=limit,
            first_day_of_week=first_dow,
        )
        return {
            "chart_type": chart_type,
            "timeframe": timeframe,
            "period": period,
            "items": items,
            "tracks": items,
        }

    async def handle_get_analytics(call: ServiceCall) -> ServiceResponse:
        hubs = _iter_hubs(hass)
        if not hubs:
            return {}
        return await hubs[0].storage_manager.async_get_analytics_summary()

    if not hass.services.has_service(DOMAIN, "send_notification"):
        hass.services.async_register(
            DOMAIN, "send_notification", handle_send_notification
        )

    if not hass.services.has_service(DOMAIN, "send_command"):
        hass.services.async_register(DOMAIN, "send_command", handle_send_command)

    if not hass.services.has_service(DOMAIN, "clear_cache"):
        hass.services.async_register(
            DOMAIN,
            "clear_cache",
            handle_clear_cache,
            schema=SERVICE_CLEAR_CACHE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, "create_chart"):
        hass.services.async_register(
            DOMAIN,
            "create_chart",
            handle_create_chart,
            schema=SERVICE_CREATE_CHART_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, "cancel_chart"):
        hass.services.async_register(DOMAIN, "cancel_chart", handle_cancel_chart)

    if not hass.services.has_service(DOMAIN, "get_leaderboard"):
        hass.services.async_register(
            DOMAIN,
            "get_leaderboard",
            handle_get_leaderboard,
            schema=SERVICE_LEADERBOARD_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, "get_analytics"):
        hass.services.async_register(
            DOMAIN,
            "get_analytics",
            handle_get_analytics,
            supports_response=SupportsResponse.ONLY,
        )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all Pixoo64 domain services when the last entry is unloaded."""
    for svc in (
        "send_notification",
        "send_command",
        "clear_cache",
        "create_chart",
        "cancel_chart",
        "get_leaderboard",
        "get_analytics",
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
