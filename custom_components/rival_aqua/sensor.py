"""Diagnostic sensors for Rival Aqua: network details."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import RivalNetwork
from .coordinator import RivalConfigEntry, RivalCoordinator
from .entity import RivalEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RivalSensorDescription(SensorEntityDescription):
    value: Callable[[RivalNetwork], str | None]


SENSORS = (
    RivalSensorDescription(key="ip_address", translation_key="ip_address", value=lambda n: n.ip),
    RivalSensorDescription(
        key="wifi_network",
        translation_key="wifi_network",
        # "" = not joined to a home network (hotspot only)
        value=lambda n: n.home_network if n.home_network is None else (n.home_network or "—"),
    ),
    RivalSensorDescription(
        key="hotspot_name", translation_key="hotspot_name", value=lambda n: n.hotspot_name
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RivalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(RivalNetworkSensor(coordinator, d) for d in SENSORS)


class RivalNetworkSensor(RivalEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: RivalSensorDescription

    def __init__(self, coordinator: RivalCoordinator, description: RivalSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | None:
        return self.entity_description.value(self.coordinator.network)
