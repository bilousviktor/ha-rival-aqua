"""Cooler fan for Rival Aqua (only when enabled on the controller)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RivalConfigEntry, RivalCoordinator
from .entity import RivalEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RivalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if coordinator.info.fan_enabled:
        async_add_entities([RivalFan(coordinator)])


class RivalFan(RivalEntity, FanEntity):
    """The cooler channel (firmware channel 8), 0-100 % in 5 % steps."""

    _attr_translation_key = "cooler"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = 20

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "fan")

    @property
    def percentage(self) -> int | None:
        data = self.coordinator.data
        return data.fan_level if data else None

    @property
    def is_on(self) -> bool:
        return bool(self.percentage)

    async def async_set_percentage(self, percentage: int) -> None:
        await self.coordinator.async_set_fan(percentage)

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        await self.coordinator.async_set_fan(percentage if percentage is not None else 100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_fan(0)
