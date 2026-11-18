"""Actions (services) for Rival Aqua: read and save the daily schedule."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import (
    FAN_CHANNEL,
    MAX_SCHEDULE_POINTS,
    SCHEDULE_CHANNELS,
    schedule_from_chart,
    validate_schedule,
)
from .const import DOMAIN
from .coordinator import RivalConfigEntry, RivalCoordinator

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_POINTS = "points"
ATTR_TIME = "time"
ATTR_LEVELS = "levels"
ATTR_FAN = "fan"

SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SET_HOTSPOT = "set_hotspot"
SERVICE_SCAN_WIFI = "scan_wifi"
SERVICE_CONNECT_WIFI = "connect_wifi"
SERVICE_FORGET_WIFI = "forget_wifi"
SERVICE_FACTORY_RESET = "factory_reset"

ATTR_NAME = "name"
ATTR_PASSWORD = "password"
ATTR_SSID = "ssid"

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")

POINT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TIME): cv.string,
        # Either a list (channel order) or a mapping {channel name: level}.
        vol.Required(ATTR_LEVELS): vol.Any(
            [vol.Coerce(int)], {cv.string: vol.Coerce(int)}
        ),
        vol.Optional(ATTR_FAN): vol.Coerce(int),
    }
)

# The controller is optional when only one is configured (the dashboard card relies on this).
ENTRY_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})
SET_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_POINTS): vol.All(cv.ensure_list, [POINT_SCHEMA]),
    }
)
HOTSPOT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_PASSWORD): cv.string,
    }
)
CONNECT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SSID): cv.string,
        vol.Required(ATTR_PASSWORD): cv.string,
    }
)


def _fmt(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_time(value: str) -> int:
    match = _TIME_RE.match(value.strip())
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ServiceValidationError(f"Invalid time '{value}', use HH:MM")
    return int(match.group(1)) * 60 + int(match.group(2))


def _coordinator(hass: HomeAssistant, entry_id: str | None) -> RivalCoordinator:
    if entry_id is None:
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]
        if len(entries) != 1:
            raise ServiceValidationError(
                "Several Rival Aqua controllers are set up, specify config_entry_id"
                if entries
                else "No Rival Aqua controller is loaded"
            )
        return entries[0].runtime_data.coordinator
    entry: RivalConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"No Rival Aqua controller with entry id {entry_id}")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"{entry.title} is not loaded")
    return entry.runtime_data.coordinator


def _points_to_arrays(
    coordinator: RivalCoordinator, points: list[dict[str, Any]]
) -> tuple[list[int], list[list[int]]]:
    info = coordinator.info
    names = [n.strip().lower() for n in info.channel_names[: info.channel_count]]
    points = sorted(points, key=lambda p: _parse_time(p[ATTR_TIME]))
    times = [_parse_time(p[ATTR_TIME]) for p in points]
    levels = [[0] * len(points) for _ in range(SCHEDULE_CHANNELS)]

    for i, point in enumerate(points):
        given = point[ATTR_LEVELS]
        if isinstance(given, dict):
            for name, level in given.items():
                key = name.strip().lower()
                if key not in names:
                    raise ServiceValidationError(
                        f"Unknown channel '{name}'. Channels: {', '.join(info.channel_names[: info.channel_count])}"
                    )
                levels[names.index(key)][i] = level
        else:
            if len(given) != info.channel_count:
                raise ServiceValidationError(
                    f"Point {point[ATTR_TIME]}: expected {info.channel_count} levels "
                    f"({', '.join(info.channel_names[: info.channel_count])}), got {len(given)}"
                )
            for ch, level in enumerate(given):
                levels[ch][i] = level
        if ATTR_FAN in point:
            levels[FAN_CHANNEL][i] = point[ATTR_FAN]

    try:
        validate_schedule(times, levels)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    return times, levels


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (once, not per entry)."""

    async def get_schedule(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        await coordinator.async_refresh_schedule()
        info = coordinator.info
        times, levels = schedule_from_chart(coordinator.data.schedule)
        points = []
        for i, minute in enumerate(times):
            point: dict[str, Any] = {
                ATTR_TIME: _fmt(minute),
                ATTR_LEVELS: [levels[ch][i] for ch in range(info.channel_count)],
            }
            if info.fan_enabled:
                point[ATTR_FAN] = levels[FAN_CHANNEL][i]
            points.append(point)
        colors = info.channel_colors + [""] * (SCHEDULE_CHANNELS - len(info.channel_colors))
        return {
            "channels": [n.strip() for n in info.channel_names[: info.channel_count]],
            "colors": colors[: info.channel_count],
            "fan": (
                {"name": info.channel_names[FAN_CHANNEL].strip(), "color": colors[FAN_CHANNEL]}
                if info.fan_enabled
                else None
            ),
            "max_points": MAX_SCHEDULE_POINTS,
            ATTR_POINTS: points,
        }

    async def set_schedule(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        times, levels = _points_to_arrays(coordinator, call.data[ATTR_POINTS])
        await coordinator.async_set_schedule(times, levels)

    async def set_hotspot(call: ServiceCall) -> None:
        if ATTR_NAME not in call.data and ATTR_PASSWORD not in call.data:
            raise ServiceValidationError("Give a new hotspot name, password, or both")
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        await coordinator.async_set_hotspot(call.data.get(ATTR_NAME), call.data.get(ATTR_PASSWORD))

    async def scan_wifi(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        return {"networks": await coordinator.async_scan_wifi()}

    async def connect_wifi(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        if not await coordinator.async_connect_wifi(call.data[ATTR_SSID], call.data[ATTR_PASSWORD]):
            raise HomeAssistantError(
                f"The controller could not join '{call.data[ATTR_SSID]}'. Check the password."
            )

    async def forget_wifi(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        await coordinator.async_forget_wifi()

    async def factory_reset(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        await coordinator.async_factory_reset()

    hass.services.async_register(DOMAIN, SERVICE_SET_HOTSPOT, set_hotspot, schema=HOTSPOT_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_WIFI,
        scan_wifi,
        schema=ENTRY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CONNECT_WIFI, connect_wifi, schema=CONNECT_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_FORGET_WIFI, forget_wifi, schema=ENTRY_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_FACTORY_RESET, factory_reset, schema=ENTRY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        get_schedule,
        schema=ENTRY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_SCHEDULE, set_schedule, schema=SET_SCHEMA
    )
