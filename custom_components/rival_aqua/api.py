"""Async client for the Rival Aqua WiFi LED controller.

The controller (ESP-based, firmware web UI "RivalAqua") exposes a plain
HTTP GET API on port 80 with text/plain responses and no authentication.
Everything here was derived from the controller's own web UI scripts
(index.html, chanfancheck.js, uscript.js, config.html).

The device is small and handles one request at a time, so all calls are
serialised through a lock.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

FAN_CHANNEL = 8
# /pointch is always sent for channels 0-8 (8 = cooler), like the web UI.
SCHEDULE_CHANNELS = 9
# The web UI allows 18 chart points including the fixed 00:00 and 24:00 ends.
MAX_SCHEDULE_POINTS = 16
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)


class RivalError(Exception):
    """Base error for the Rival Aqua client."""


class RivalConnectionError(RivalError):
    """The controller could not be reached or returned an error."""


@dataclass
class RivalInfo:
    """Static-ish controller configuration."""

    channel_count: int
    fan_enabled: bool
    night_indicator: bool
    channel_names: list[str]
    channel_colors: list[str]
    version: str | None = None


@dataclass
class SchedulePoint:
    """One point of the daily light curve (minutes since midnight, percent)."""

    minute: int
    level: int


@dataclass
class RivalState:
    """Live state polled from the controller."""

    levels: list[int]
    fan_level: int | None
    hand_mode: bool
    manual_unlocked: bool
    night_indicator: bool
    schedule: list[list[SchedulePoint]] = field(default_factory=list)

    @property
    def manual(self) -> bool:
        """True when the controller is in manual mode (schedule paused)."""
        return self.hand_mode or self.manual_unlocked


def _parse_js_string_array(js: str) -> list[str]:
    """Parse `var X=['a','b',...];` into a list of strings."""
    match = re.search(r"\[(.*)\]", js, re.S)
    if not match:
        return []
    return [
        (single or double).strip()
        for single, double in re.findall(r"'([^']*)'|\"([^\"]*)\"", match.group(1))
    ]


def _parse_schedule(js: str) -> list[list[SchedulePoint]]:
    """Parse chartdata.js into per-channel lists of schedule points."""
    channels: list[list[SchedulePoint]] = []
    for block in re.findall(r"data:\s*\[(.*?)\]", js, re.S):
        points: list[SchedulePoint] = []
        for hh, mm, level in re.findall(
            r'x:\s*"(\d{1,2}):(\d{2})"\s*,\s*y:\s*(-?\d+)', block
        ):
            points.append(SchedulePoint(int(hh) * 60 + int(mm), int(level)))
        channels.append(points)
    return channels


def _clamp_level(level: int) -> int:
    return max(0, min(100, int(round(level))))


def schedule_from_chart(
    chart: list[list[SchedulePoint]],
) -> tuple[list[int], list[list[int]]]:
    """Convert chartdata.js points to (times, channel_levels) as the Save button sends.

    Drops the implicit first (00:00) and last (24:00) points, like savepoint().
    """
    if not chart or len(chart[0]) < 3:
        return [], [[] for _ in range(SCHEDULE_CHANNELS)]
    times = [p.minute for p in chart[0][1:-1]]
    levels = [
        [p.level for p in (chart[ch][1:-1] if ch < len(chart) else [])]
        for ch in range(SCHEDULE_CHANNELS)
    ]
    return times, levels


def validate_schedule(times: list[int], channel_levels: list[list[int]]) -> None:
    """Raise ValueError if the schedule can't be stored by the controller."""
    if not 1 <= len(times) <= MAX_SCHEDULE_POINTS:
        raise ValueError(
            f"A schedule needs 1-{MAX_SCHEDULE_POINTS} points, got {len(times)}"
        )
    for minute in times:
        if not 0 <= minute < 24 * 60:
            raise ValueError(f"Point time {minute} min is outside 00:00-23:59")
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise ValueError("Point times must be strictly increasing")
    if len(channel_levels) > SCHEDULE_CHANNELS:
        raise ValueError(f"At most {SCHEDULE_CHANNELS} channels (8 = cooler)")
    for ch, levels in enumerate(channel_levels):
        if levels and len(levels) != len(times):
            raise ValueError(
                f"Channel {ch} has {len(levels)} levels for {len(times)} points"
            )
        for level in levels:
            if not 0 <= level <= 100:
                raise ValueError(f"Level {level} on channel {ch} is outside 0-100")


class RivalAquaClient:
    """Minimal async client for one controller."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._base = f"http://{host.strip().rstrip('/')}"
        if host.startswith(("http://", "https://")):
            self._base = host.strip().rstrip("/")
        self._session = session
        self._lock = asyncio.Lock()
        self.info: RivalInfo | None = None

    @property
    def base_url(self) -> str:
        return self._base

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self._base}{path}"
        async with self._lock:
            try:
                async with self._session.get(
                    url, params=params, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        raise RivalConnectionError(f"{path} returned HTTP {resp.status}")
                    raw = await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise RivalConnectionError(f"{path}: {err}") from err
        return raw.decode("utf-8", errors="replace").strip()

    async def _get_flag(self, path: str) -> bool:
        text = await self._get(path)
        try:
            return int(text) != 0
        except ValueError:
            return text.lower() == "true"

    # ------------------------------------------------------------------ read

    async def async_get_info(self) -> RivalInfo:
        """Read channel count, fan/indicator flags, names, colours, version."""
        chnumb = await self._get("/chnumb")
        parts = [p.strip() for p in chnumb.split(",")]
        try:
            count = int(parts[0])
            fan = len(parts) > 1 and int(parts[1]) == 1
            stat = len(parts) > 2 and int(parts[2]) == 1
        except (ValueError, IndexError) as err:
            raise RivalError(f"Unexpected /chnumb response: {chnumb!r}") from err

        names = _parse_js_string_array(await self._get("/namechannellist.js"))
        try:
            colors = _parse_js_string_array(await self._get("/color.js"))
        except RivalConnectionError:
            colors = []
        try:
            version = await self._get("/curver") or None
        except RivalConnectionError:
            version = None

        names = names + [f"Channel {i + 1}" for i in range(len(names), 9)]
        self.info = RivalInfo(
            channel_count=count,
            fan_enabled=fan,
            night_indicator=stat,
            channel_names=names,
            channel_colors=colors,
            version=version,
        )
        return self.info

    async def async_get_levels(self) -> tuple[list[int], int | None]:
        """Current output levels in percent (and fan level if enabled)."""
        info = self.info or await self.async_get_info()
        text = await self._get("/curlevelrange")
        values = [int(v) for v in text.split(";") if v.strip().lstrip("-").isdigit()]
        levels = (values + [0] * info.channel_count)[: info.channel_count]
        fan = None
        if info.fan_enabled and len(values) > info.channel_count:
            fan = values[info.channel_count]
        return levels, fan

    async def async_get_schedule(self) -> list[list[SchedulePoint]]:
        """The stored day curve, one list of points per channel (index 8 = fan)."""
        return _parse_schedule(await self._get("/chartdata.js"))

    async def async_get_state(self, include_schedule: bool = False) -> RivalState:
        levels, fan = await self.async_get_levels()
        hand = await self._get_flag("/handmodestate")
        unlocked = await self._get_flag("/blockrange")
        chnumb = await self._get("/chnumb")
        parts = chnumb.split(",")
        night = len(parts) > 2 and parts[2].strip() == "1"
        schedule = await self.async_get_schedule() if include_schedule else []
        return RivalState(
            levels=levels,
            fan_level=fan,
            hand_mode=hand,
            manual_unlocked=unlocked,
            night_indicator=night,
            schedule=schedule,
        )

    # ----------------------------------------------------------------- write

    async def async_set_manual(
        self, enabled: bool, levels: list[int] | None = None
    ) -> None:
        """Enter or leave manual mode, mirroring the web UI's hand toggle.

        When entering, `levels` (one per channel) are applied first so the
        light does not jump to the controller's stored manual levels.
        """
        if enabled:
            if levels is not None:
                await self.async_set_all(levels)
            await self._get("/handmode", {"onoff": 1})
            await self._get("/pwm_man", {"state": "true"})
            await self._get("/blockrangeset", {"state": "true"})
        else:
            await self._get("/handmode", {"onoff": 0})
            await self._get("/pwm_man", {"state": "false"})
            await self._get("/blockrangeset", {"state": "false"})

    async def async_set_channel(self, channel: int, level: int) -> None:
        """Set one channel (0-based; FAN_CHANNEL for the cooler) to 0-100 %."""
        await self._get("/light", {"range": channel, "level": _clamp_level(level)})

    async def async_set_all(self, levels: list[int], fan: int | None = None) -> None:
        """Set every channel at once (`/lightsetmode`)."""
        info = self.info or await self.async_get_info()
        params: dict[str, Any] = {"ch": info.channel_count}
        for idx in range(info.channel_count):
            value = levels[idx] if idx < len(levels) else 0
            params[f"l{idx}"] = _clamp_level(value)
        if info.fan_enabled and fan is not None:
            params["f"] = _clamp_level(fan)
        await self._get("/lightsetmode", params)

    async def async_sync_time(self, now: datetime) -> None:
        """Set the controller clock (it has no NTP; the web UI does this on load)."""
        await self._get(
            "/synchtime", {"hour": now.hour, "min": now.minute, "sec": now.second}
        )

    async def async_set_schedule(
        self, times: list[int], channel_levels: list[list[int]]
    ) -> None:
        """Write the daily schedule, exactly like the web UI's Save button.

        `times` are the schedule points in minutes since midnight (strictly
        increasing, the implicit 00:00 / 24:00 end points excluded).
        `channel_levels[ch][i]` is the level (0-100 %) of channel `ch` at
        point `i`; channels 0-7 are LED channels and 8 is the cooler. Missing
        channels are sent as zeros, as the web UI does.

        The firmware stores the schedule when it receives it; the trailing
        pwm_man / blockrangeset calls leave edit mode so it runs immediately.
        """
        validate_schedule(times, channel_levels)
        params: dict[str, Any] = {"pn": len(times)}
        for i, minute in enumerate(times):
            params[f"p{i}"] = minute
        await self._get("/pointtimes", params)

        for ch in range(SCHEDULE_CHANNELS):
            levels = channel_levels[ch] if ch < len(channel_levels) else []
            ch_params: dict[str, Any] = {"ch": ch}
            for i in range(len(times)):
                ch_params[f"p{i}"] = _clamp_level(levels[i]) if i < len(levels) else 0
            await self._get("/pointch", ch_params)

        await self._get("/pwm_man", {"state": "false"})
        await self._get("/blockrangeset", {"state": "false"})

    async def async_set_night_indicator(self, enabled: bool) -> None:
        await self._get("/lightset", {"state": "true" if enabled else "false"})
