"""Switches for Rival Aqua: manual mode, night indicator, cooler channel."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
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
    async_add_entities(
        [
            RivalManualModeSwitch(coordinator),
            RivalNightIndicatorSwitch(coordinator),
            RivalCoolerEnabledSwitch(coordinator),
        ]
    )


class RivalManualModeSwitch(RivalEntity, SwitchEntity):
    """On = manual levels; off = follow the controller's daily schedule."""

    _attr_translation_key = "manual_mode"

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "manual_mode")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.manual)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manual(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manual(False)


class RivalNightIndicatorSwitch(RivalEntity, SwitchEntity):
    """The controller's status LED at night ("Ночная индикация")."""

    _attr_translation_key = "night_indicator"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "night_indicator")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.night_indicator)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_night_indicator(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_night_indicator(False)


class RivalCoolerEnabledSwitch(RivalEntity, SwitchEntity):
    """Whether the controller drives a cooler on channel 8 ("Вентилятор" in its settings).

    Toggling it reloads the integration so the cooler fan entity appears or disappears.
    """

    _attr_translation_key = "cooler_enabled"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "cooler_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.info.fan_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_fan_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_fan_enabled(False)
