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
    assert states["switch.aquarium_cooler_channel"] == "off"
    assert states["text.aquarium_channel_1_name"] == "Cool White"
    assert states["text.aquarium_channel_4_name"] == "Warm White"  # trailing space stripped
    assert states["text.aquarium_cool_white_colour"] == "#FFFFFF"
    assert states["text.aquarium_blue_colour"] == "#0000FF"
    assert "text.aquarium_cooler_colour" not in states
    assert "button.aquarium_restart" in states


async def test_channel_name_and_colour(hass: HomeAssistant, controller: Controller) -> None:
    await _setup(hass, controller.host)

    await _call(hass, "text", "set_value", {"entity_id": "text.aquarium_channel_3_name", "value": "Royal Blue"})
    await hass.async_block_till_done()  # reload
    assert controller.names[:5] == ["Cool White", "Green", "Royal Blue", "Warm White", "Red"]
    assert controller.hotspot == ("Rival_LED", "11223344")  # re-sent unchanged
    i = controller.log.index("/saveparam?namepoint=Rival_LED&passpoint=11223344")
    assert controller.log[i + 1].startswith("/savenamechan?name0=Cool")
    # Same entity, new name after the reload
    assert hass.states.get("light.aquarium_blue").name == "Aquarium Royal Blue"
    assert hass.states.get("text.aquarium_channel_3_name").state == "Royal Blue"

    with pytest.raises((ValueError, ServiceValidationError)):
        await _call(hass, "text", "set_value", {"entity_id": "text.aquarium_channel_1_name", "value": "it's"})

    await _call(hass, "text", "set_value", {"entity_id": "text.aquarium_red_colour", "value": "#ff8800"})
    assert controller.colors[4] == "#FF8800"
    assert hass.states.get("text.aquarium_red_colour").state == "#FF8800"
    resp = await _call(hass, DOMAIN, "get_schedule", {}, return_response=True)
    assert resp["colors"][4] == "#FF8800"  # the schedule card picks it up
    with pytest.raises((ValueError, ServiceValidationError)):
        await _call(hass, "text", "set_value", {"entity_id": "text.aquarium_red_colour", "value": "red"})


async def test_cooler_channel(hass: HomeAssistant, controller: Controller) -> None:
    await _setup(hass, controller.host)
    assert hass.states.get("fan.aquarium_cooler") is None

    await _call(hass, "switch", "turn_on", {"entity_id": "switch.aquarium_cooler_channel"})
    await hass.async_block_till_done()
    assert controller.fan
    assert hass.states.get("switch.aquarium_cooler_channel").state == "on"
    assert hass.states.get("fan.aquarium_cooler") is not None
    assert hass.states.get("text.aquarium_cooler_colour").state == "#FF4500"

    await _call(hass, "switch", "turn_off", {"entity_id": "switch.aquarium_cooler_channel"})
    await hass.async_block_till_done()
    assert not controller.fan
    fan = hass.states.get("fan.aquarium_cooler")
    assert fan is None or fan.state == "unavailable"


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
