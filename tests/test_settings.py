"""Controller settings (the web UI's config.html) through Home Assistant, against the mock."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.rival_aqua.const import DOMAIN

from .mock_controller import Controller
from .test_integration import _setup, controller  # noqa: F401  (fixture)


async def _call(hass, domain, service, data, **kw):
    return await hass.services.async_call(domain, service, data, blocking=True, **kw)


async def test_settings_entities(hass: HomeAssistant, controller: Controller) -> None:
    await _setup(hass, controller.host)
    states = {s.entity_id: s.state for s in hass.states.async_all()}

    assert states["sensor.aquarium_ip_address"] == "192.168.5.200"
    assert states["sensor.aquarium_wi_fi_network"] == "HomeNet"
    assert states["sensor.aquarium_hotspot_name"] == "Rival_LED"
    assert not any("11223344" in str(v) for v in states.values())  # password never in a state
    assert "button.aquarium_restart" in states


async def test_hotspot(hass: HomeAssistant, controller: Controller) -> None:
    await _setup(hass, controller.host)

    await _call(hass, DOMAIN, "set_hotspot", {"name": "Aqua_Light"})
    assert controller.hotspot == ("Aqua_Light", "11223344")
    assert controller.names[:5] == ["Cool White", "Green", "Blue", "Warm White", "Red"]
    assert hass.states.get("sensor.aquarium_hotspot_name").state == "Aqua_Light"

    await _call(hass, DOMAIN, "set_hotspot", {"password": "55667788"})
    assert controller.hotspot == ("Aqua_Light", "55667788")

    for bad in ({"name": "ab"}, {"name": "with space"}, {"password": "1234567"}, {"password": "abcdefgh"}, {}):
        with pytest.raises(ServiceValidationError):
            await _call(hass, DOMAIN, "set_hotspot", bad)
    assert controller.hotspot == ("Aqua_Light", "55667788")


async def test_wifi_and_maintenance(hass: HomeAssistant, controller: Controller) -> None:
    await _setup(hass, controller.host)

    resp = await _call(hass, DOMAIN, "scan_wifi", {}, return_response=True)
    assert resp == {"networks": ["HomeNet", "HomeNet-5G", "Neighbour"]}

    with pytest.raises(HomeAssistantError, match="could not join"):
        await _call(hass, DOMAIN, "connect_wifi", {"ssid": "HomeNet-5G", "password": "wrong"})
    assert controller.home == "HomeNet"
    await _call(hass, DOMAIN, "connect_wifi", {"ssid": "HomeNet-5G", "password": "secret123"})
    assert controller.home == "HomeNet-5G"

    await _call(hass, "button", "press", {"entity_id": "button.aquarium_restart"})
    assert controller.reboots == 1

    await _call(hass, DOMAIN, "forget_wifi", {})
    assert controller.home == "" and controller.reboots == 2

    await _call(hass, DOMAIN, "factory_reset", {})
    await hass.async_block_till_done()
    assert controller.factory_resets == 1


async def test_removed_entities_cleaned_up(hass: HomeAssistant, controller: Controller) -> None:
    """Entities dropped in 0.5.0 are removed from the registry on the next setup."""
    from homeassistant.helpers import entity_registry as er

    entry = await _setup(hass, controller.host)
    reg = er.async_get(hass)
    prefix = entry.unique_id or entry.entry_id
    for platform, key in [
        ("text", "channel_0_name"),
        ("text", "channel_2_color"),
        ("switch", "cooler_enabled"),
        ("button", "sync_time"),
        ("light", "channel_0"),
        ("switch", "manual_mode"),
    ]:
        reg.async_get_or_create(platform, DOMAIN, f"{prefix}_{key}", config_entry=entry)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    uids = {e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    for key in ("channel_0_name", "channel_2_color", "cooler_enabled", "sync_time", "channel_0", "manual_mode"):
        assert f"{prefix}_{key}" not in uids
    assert f"{prefix}_hotspot_name" in uids  # not caught by the cleanup
    assert f"{prefix}_channel_0" not in uids  # channel light (dropped too)
    assert f"{prefix}_light" in uids
