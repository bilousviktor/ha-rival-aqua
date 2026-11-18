"""The Rival Aqua aquarium light integration."""

from __future__ import annotations

import re
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import RivalAquaClient, RivalError
from .const import CARD_FILENAME, CARD_URL_PATH, DOMAIN
from .coordinator import RivalConfigEntry, RivalCoordinator, RivalRuntimeData
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Entities dropped in 0.5.0 (unique id suffixes); removed from the registry on setup.
_REMOVED_KEYS = ("_sync_time", "_cooler_enabled")
_REMOVED_KEY_PATTERN = re.compile(r"_channel_\d+_(name|color)$")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the schedule actions and the schedule editor card."""
    async_setup_services(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the dashboard card and load it in the frontend (no manual resource needed)."""
    if hass.http is None:  # http not set up (e.g. tests)
        return
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL_PATH, str(Path(__file__).parent / "frontend" / CARD_FILENAME), True
            )
        ]
    )
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        version = (await async_get_integration(hass, DOMAIN)).version
        # The version query busts the browser cache after an update.
        add_extra_js_url(hass, f"{CARD_URL_PATH}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: RivalConfigEntry) -> bool:
    """Set up Rival Aqua from a config entry."""
    client = RivalAquaClient(entry.data[CONF_HOST], async_get_clientsession(hass))
    try:
        info = await client.async_get_info()
    except RivalError as err:
        raise ConfigEntryNotReady(f"Cannot reach Rival controller: {err}") from err

    _async_remove_old_entities(hass, entry)
    coordinator = RivalCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = RivalRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_remove_old_entities(hass: HomeAssistant, entry: RivalConfigEntry) -> None:
    """Drop registry entries of entities this version no longer creates."""
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        uid = reg_entry.unique_id
        if uid.endswith(_REMOVED_KEYS) or _REMOVED_KEY_PATTERN.search(uid):
            registry.async_remove(reg_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: RivalConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
