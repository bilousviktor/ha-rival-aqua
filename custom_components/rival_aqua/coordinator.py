"""Data update coordinator for Rival Aqua."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Concatenate

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FAN_CHANNEL, RivalAquaClient, RivalError, RivalInfo, RivalState
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MANUFACTURER, TIME_SYNC_INTERVAL

_LOGGER = logging.getLogger(__name__)

type RivalConfigEntry = ConfigEntry[RivalRuntimeData]


def _raise_ha_error[**P, R](
    func: Callable[Concatenate[RivalCoordinator, P], Awaitable[R]],
) -> Callable[Concatenate[RivalCoordinator, P], Coroutine[Any, Any, R]]:
    """Turn controller errors during service calls into HomeAssistantError."""

    @functools.wraps(func)
    async def wrapper(self: RivalCoordinator, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(self, *args, **kwargs)
        except RivalError as err:
            raise HomeAssistantError(f"Rival controller error: {err}") from err

    return wrapper


@dataclass
class RivalRuntimeData:
    client: RivalAquaClient
    coordinator: RivalCoordinator


class RivalCoordinator(DataUpdateCoordinator[RivalState]):
    """Polls the controller and owns write helpers that refresh afterwards."""

    config_entry: RivalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: RivalConfigEntry,
        client: RivalAquaClient,
        info: RivalInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.base_url}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.info = info
        self._polls = 0
        self._last_time_sync: datetime | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.unique_id or self.config_entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=f"Rival WiFi controller ({self.info.channel_count} ch)",
            name=self.config_entry.title,
            sw_version=self.info.version,
            configuration_url=self.client.base_url,
        )

    async def _async_update_data(self) -> RivalState:
        # Re-read the schedule on the first poll and then roughly every 5 minutes.
        include_schedule = self._polls % 30 == 0 or self.data is None
        self._polls += 1
        try:
            state = await self.client.async_get_state(include_schedule=include_schedule)
            await self._async_maybe_sync_time()
        except RivalError as err:
            raise UpdateFailed(str(err)) from err
        if not include_schedule and self.data is not None:
            state.schedule = self.data.schedule
        return state

    async def _async_maybe_sync_time(self) -> None:
        now = dt_util.now()
        if self._last_time_sync and now - self._last_time_sync < TIME_SYNC_INTERVAL:
            return
        await self.client.async_sync_time(now)
        self._last_time_sync = now
        _LOGGER.debug("Synced controller clock to %s", now.strftime("%H:%M:%S"))

    @_raise_ha_error
    async def async_sync_time(self) -> None:
        self._last_time_sync = None
        await self._async_maybe_sync_time()

    @_raise_ha_error
    async def async_set_night_indicator(self, enabled: bool) -> None:
        await self.client.async_set_night_indicator(enabled)
        await self.async_request_refresh()

    # ------------------------------------------------------------ writes

    async def async_ensure_manual(self) -> None:
        """Switch to manual mode, keeping the current output levels."""
        if self.data is not None and self.data.manual:
            return
        levels = list(self.data.levels) if self.data else None
        await self.client.async_set_manual(True, levels)
        if self.data is not None:
            self.data.hand_mode = True
            self.data.manual_unlocked = True

    @_raise_ha_error
    async def async_set_levels(self, levels: list[int]) -> None:
        """Apply levels for all channels (enters manual mode first)."""
        await self.async_ensure_manual()
        fan = self.data.fan_level if self.data else None
        await self.client.async_set_all(levels, fan)
        await self._apply_local(levels=levels)

    @_raise_ha_error
    async def async_set_channel(self, channel: int, level: int) -> None:
        await self.async_ensure_manual()
        await self.client.async_set_channel(channel, level)
        if self.data is not None and channel < len(self.data.levels):
            levels = list(self.data.levels)
            levels[channel] = level
            await self._apply_local(levels=levels)
        else:
            await self.async_request_refresh()

    @_raise_ha_error
    async def async_set_fan(self, level: int) -> None:
        await self.async_ensure_manual()
        await self.client.async_set_channel(FAN_CHANNEL, level)
        if self.data is not None:
            self.data.fan_level = level
            self.async_set_updated_data(self.data)

    @_raise_ha_error
    async def async_set_manual(self, enabled: bool) -> None:
        if enabled:
            await self.async_ensure_manual()
        else:
            await self.client.async_set_manual(False)
        # Mode changes alter every level at once: poll right away, not debounced.
        await self.async_refresh()

    @_raise_ha_error
    async def async_refresh_schedule(self) -> None:
        """Re-read the stored schedule now (it may have been edited in the web UI)."""
        schedule = await self.client.async_get_schedule()
        if self.data is not None:
            self.data.schedule = schedule
            self.async_set_updated_data(self.data)

    @_raise_ha_error
    async def async_set_schedule(
        self, times: list[int], channel_levels: list[list[int]]
    ) -> None:
        """Write and save the daily schedule, then resume it."""
        await self.client.async_set_schedule(times, channel_levels)
        await self.client.async_set_manual(False)
        self._polls = 0  # re-read chartdata.js on this refresh
        await self.async_refresh()

    async def _apply_local(self, levels: list[int]) -> None:
        """Optimistically publish new levels, then confirm with a poll."""
        if self.data is not None:
            self.data.levels = levels
            self.async_set_updated_data(self.data)
        await self.async_request_refresh()
