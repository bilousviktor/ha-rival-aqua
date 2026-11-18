"""Base entity for Rival Aqua."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import RivalCoordinator


class RivalEntity(CoordinatorEntity[RivalCoordinator]):
    """Common base: device info and unique id prefix."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RivalCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info
