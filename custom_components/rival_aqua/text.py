"""Text entities for Rival Aqua settings: channel names and display colours."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CHANNEL_NAME_MAX, FAN_CHANNEL
from .coordinator import RivalConfigEntry, RivalCoordinator
from .entity import RivalEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RivalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    info = coordinator.info
    entities: list[TextEntity] = []
    for ch in range(info.channel_count):
        entities.append(RivalChannelNameText(coordinator, ch))
        entities.append(RivalChannelColorText(coordinator, ch))
    if info.fan_enabled:
        entities.append(RivalChannelColorText(coordinator, FAN_CHANNEL))
    async_add_entities(entities)


class RivalChannelNameText(RivalEntity, TextEntity):
    """A channel's name (the settings page's name field). Saved to the controller."""

    _attr_translation_key = "channel_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 1
    _attr_native_max = CHANNEL_NAME_MAX
    _attr_pattern = r"^[^'\"\\]+$"

    def __init__(self, coordinator: RivalCoordinator, channel: int) -> None:
        super().__init__(coordinator, f"channel_{channel}_name")
        self._channel = channel
        self._attr_translation_placeholders = {"number": str(channel + 1)}

    @property
    def native_value(self) -> str:
        return self.coordinator.info.channel_names[self._channel].strip()

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_channel_name(self._channel, value)


class RivalChannelColorText(RivalEntity, TextEntity):
    """A channel's display colour (#RRGGBB) used by the web UI and the schedule card."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 7
    _attr_native_max = 7
    _attr_pattern = r"^#[0-9A-Fa-f]{6}$"

    def __init__(self, coordinator: RivalCoordinator, channel: int) -> None:
        super().__init__(coordinator, f"channel_{channel}_color")
        self._channel = channel
        if channel == FAN_CHANNEL:
            self._attr_translation_key = "cooler_color"
        else:
            self._attr_translation_key = "channel_color"
            self._attr_translation_placeholders = {
                "channel": coordinator.info.channel_names[channel].strip()
            }

    @property
    def native_value(self) -> str | None:
        colors = self.coordinator.info.channel_colors
        return colors[self._channel].upper() if self._channel < len(colors) else None

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_channel_color(self._channel, value)
