"""Buttons for Rival Aqua."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    async_add_entities([RivalSyncTimeButton(coordinator), RivalRebootButton(coordinator)])


class RivalSyncTimeButton(RivalEntity, ButtonEntity):
    """Push Home Assistant's local time to the controller clock now.

    The integration also does this automatically every few hours.
    """

    _attr_translation_key = "sync_time"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "sync_time")

    async def async_press(self) -> None:
        await self.coordinator.async_sync_time()


class RivalRebootButton(RivalEntity, ButtonEntity):
    """Restart the controller (settings page "Перезагрузка"). It reconnects on its own."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RivalCoordinator) -> None:
        super().__init__(coordinator, "reboot")

    async def async_press(self) -> None:
        await self.coordinator.async_reboot()
