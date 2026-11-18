"""Light platform for Rival Aqua.

* One combined light. With the stock Cool White / Green / Blue / Warm White /
  Red channels it uses HA's RGBWW colour mode; otherwise it is a brightness
  light that scales the current channel mix.
* One brightness light per channel for fine-grained control.

Any change made from Home Assistant puts the controller into manual mode
(the daily schedule pauses). Turn the "Manual mode" switch off to resume it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGBWW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RivalConfigEntry, RivalCoordinator
from .entity import RivalEntity
from .levels import (
    brightness_to_level,
    level_to_brightness,
    levels_to_brightness_and_rgbww,
    mix_ratios,
    rgbww_slots,
    rgbww_to_levels,
    scale_levels,
)

PARALLEL_UPDATES = 1
FALLBACK_LEVEL = 50


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RivalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    info = coordinator.info
    entities: list[LightEntity] = [RivalMainLight(coordinator)]
    entities += [
        RivalChannelLight(coordinator, idx) for idx in range(info.channel_count)
    ]
    async_add_entities(entities)


def _fmt_minute(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class RivalMainLight(RivalEntity, LightEntity):
    """All channels as one light."""

    _attr_name = None  # the device's main feature: use the device name

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "light")
        info = coordinator.info
        self._count = info.channel_count
        self._slots = rgbww_slots(info.channel_names, info.channel_count)
        mode = ColorMode.RGBWW if self._slots else ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {mode}
        self._attr_color_mode = mode
        self._last_levels: list[int] | None = None

    @property
    def _levels(self) -> list[int]:
        data = self.coordinator.data
        return list(data.levels) if data else [0] * self._count

    @callback
    def _handle_coordinator_update(self) -> None:
        if any(self._levels):
            self._last_levels = self._levels
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        return any(self._levels)

    @property
    def brightness(self) -> int:
        return level_to_brightness(max(self._levels, default=0))

    @property
    def rgbww_color(self) -> tuple[int, int, int, int, int] | None:
        if not self._slots:
            return None
        levels = self._levels if any(self._levels) else (self._last_levels or self._levels)
        return levels_to_brightness_and_rgbww(levels, self._slots)[1]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        names = self.coordinator.info.channel_names
        attrs: dict[str, Any] = {
            "mode": "manual" if data and data.manual else "schedule",
        }
        for idx, level in enumerate(self._levels):
            attrs[f"{names[idx].strip().lower().replace(' ', '_')}_level"] = level
        return attrs

    def _restore_levels(self) -> list[int]:
        """Levels to use when turning on from off with no parameters."""
        if self._last_levels and any(self._last_levels):
            return self._last_levels
        schedule = self.coordinator.data.schedule if self.coordinator.data else []
        peaks = [
            max((p.level for p in schedule[idx]), default=0) if idx < len(schedule) else 0
            for idx in range(self._count)
        ]
        return peaks if any(peaks) else [FALLBACK_LEVEL] * self._count

    async def async_turn_on(self, **kwargs: Any) -> None:
        current = self._levels if any(self._levels) else self._restore_levels()
        cur_brightness = level_to_brightness(max(current))
        brightness = kwargs.get(ATTR_BRIGHTNESS, cur_brightness)

        if self._slots and ATTR_RGBWW_COLOR in kwargs:
            levels = rgbww_to_levels(
                kwargs[ATTR_RGBWW_COLOR], brightness, self._slots, self._count
            )
        else:
            ratios = mix_ratios(current) or [1.0] * self._count
            levels = scale_levels(ratios, brightness)

        await self.coordinator.async_set_levels(levels)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if any(self._levels):
            self._last_levels = self._levels
        await self.coordinator.async_set_levels([0] * self._count)


class RivalChannelLight(RivalEntity, LightEntity):
    """A single LED channel."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, coordinator: RivalCoordinator, channel: int) -> None:
        super().__init__(coordinator, f"channel_{channel}")
        self._channel = channel
        self._attr_name = coordinator.info.channel_names[channel].strip()
        self._last_level: int | None = None

    @property
    def _level(self) -> int:
        data = self.coordinator.data
        if not data or self._channel >= len(data.levels):
            return 0
        return data.levels[self._channel]

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._level:
            self._last_level = self._level
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        return self._level > 0

    @property
    def brightness(self) -> int:
        return level_to_brightness(self._level)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attrs: dict[str, Any] = {"level_percent": self._level}
        if data and self._channel < len(data.schedule):
            attrs["schedule"] = {
                _fmt_minute(p.minute): p.level for p in data.schedule[self._channel]
            }
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            level = brightness_to_level(kwargs[ATTR_BRIGHTNESS])
        else:
            level = self._level or self._last_level or FALLBACK_LEVEL
        await self.coordinator.async_set_channel(self._channel, level)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._level:
            self._last_level = self._level
        await self.coordinator.async_set_channel(self._channel, 0)
