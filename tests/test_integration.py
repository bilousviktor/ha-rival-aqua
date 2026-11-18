"""End-to-end: run the integration in Home Assistant against the mock controller."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.rival_aqua.const import DOMAIN

from .mock_controller import Controller


@pytest.fixture
async def controller(socket_enabled):
    ctl = Controller()
    runner = web.AppRunner(ctl.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    ctl.host = f"127.0.0.1:{port}"
    yield ctl
    await runner.cleanup()


async def _setup(hass: HomeAssistant, host: str):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f"http://{host}/", "name": "Aquarium"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


async def test_flow_cannot_connect(hass: HomeAssistant, socket_enabled) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1:1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_full(hass: HomeAssistant, controller: Controller) -> None:
    await hass.config.async_set_time_zone("Europe/Kyiv")
    entry = await _setup(hass, controller.host)
    assert entry.data[CONF_HOST] == controller.host  # http:// and / stripped

    states = {s.entity_id: s for s in hass.states.async_all()}
    print(sorted(states))
    main = states["light.aquarium"]
    assert main.state == "on"
    assert main.attributes["supported_color_modes"] == ["rgbww"]
    assert main.attributes["brightness"] == round(58 * 255 / 100)
    # R, G, B, CW, WW relative to the 58 % peak (cool white)
    assert main.attributes["rgbww_color"] == (40, 40, 40, 255, 40)
    assert main.attributes["mode"] == "schedule"
    assert "switch.aquarium_manual_mode" not in states  # the light is the only control
    assert controller.clock is not None  # clock synced on first poll

    # Night indicator enabled; fan absent (fan_en=0); dropped entities gone
    assert states["switch.aquarium_night_indicator"].state == "on"
    assert not any(e.startswith(("fan.", "text.")) for e in states)
    assert "button.aquarium_sync_clock" not in states

    # Only the combined light: no per-channel lights
    assert [e for e in states if e.startswith("light.")] == ["light.aquarium"]

    # On while the schedule is lit: nothing to do
    controller.log.clear()
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.aquarium"}, blocking=True)
    assert not any(l.startswith(("/light", "/handmode")) for l in controller.log), controller.log

    # Combined light: pure warm white at 50 % -> manual mode
    await hass.services.async_call(
        "light", "turn_on",
        {"entity_id": "light.aquarium", "rgbww_color": [0, 0, 0, 0, 255], "brightness": 128},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert controller.levels == [0, 0, 0, 50, 0], controller.levels
    assert controller.hand == 1 and controller.block == 1 and controller.pwm_man
    assert hass.states.get("light.aquarium").attributes["mode"] == "manual"

    # Brightness only keeps the mix
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.aquarium", "brightness": 255}, blocking=True
    )
    await hass.async_block_till_done()
    assert controller.levels == [0, 0, 0, 100, 0], controller.levels

    # Off -> manual mode, all channels 0
    await hass.services.async_call("light", "turn_off", {"entity_id": "light.aquarium"}, blocking=True)
    await hass.async_block_till_done()
    assert controller.levels == [0, 0, 0, 0, 0]
    assert hass.states.get("light.aquarium").state == "off"
    # Stays off after a poll: in hand mode /curlevelrange still reports the schedule
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("light.aquarium").state == "off"

    # On without params -> back to the schedule
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.aquarium"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("light.aquarium").state == "on"
    assert controller.hand == 0 and controller.block == 0 and not controller.pwm_man
    assert hass.states.get("light.aquarium").attributes["cool_white_level"] == 58  # schedule output
    assert hass.states.get("light.aquarium").attributes["mode"] == "schedule"

    # At night (schedule dark) on restores the last mix in manual mode
    controller.schedule_levels = [0, 0, 0, 0, 0]
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get("light.aquarium").state == "off"
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.aquarium"}, blocking=True)
    await hass.async_block_till_done()
    assert controller.hand == 1 and controller.levels == [58, 9, 9, 9, 9], controller.levels  # last lit mix
    assert hass.states.get("light.aquarium").state == "on"

    # Unload
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_fan(hass: HomeAssistant, controller: Controller) -> None:
    controller.fan = True
    await _setup(hass, controller.host)
    fan = hass.states.get("fan.aquarium_cooler")
    assert fan is not None and fan.attributes["percentage"] == 30
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": "fan.aquarium_cooler", "percentage": 60}, blocking=True
    )
    await hass.async_block_till_done()
    assert controller.fan_level == 60

    resp = await hass.services.async_call(
        DOMAIN, "get_schedule", {}, blocking=True, return_response=True
    )
    assert resp["fan"] == {"name": "Cooler", "color": "#FF4500"}
    assert "fan" in resp["points"][0]


async def test_no_entry_id_with_two_controllers(hass: HomeAssistant, controller: Controller) -> None:
    from homeassistant.exceptions import ServiceValidationError

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    await _setup(hass, controller.host)
    # A second (unreachable) entry that never loads does not count
    other = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "127.0.0.1:1"})
    other.add_to_hass(hass)
    await hass.config_entries.async_setup(other.entry_id)
    await hass.services.async_call(DOMAIN, "get_schedule", {}, blocking=True, return_response=True)

    # Two loaded controllers: ambiguous
    second = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: controller.host}, unique_id="second")
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    with pytest.raises(ServiceValidationError, match="config_entry_id"):
        await hass.services.async_call(DOMAIN, "get_schedule", {}, blocking=True, return_response=True)


async def test_card_is_served(hass: HomeAssistant, controller: Controller, hass_client) -> None:
    from homeassistant.setup import async_setup_component

    from unittest.mock import patch

    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await _setup(hass, controller.host)
    version = json.loads(
        (Path(__file__).parent.parent / "custom_components/rival_aqua/manifest.json").read_text()
    )["version"]
    add_js.assert_called_once_with(hass, f"/rival_aqua/rival-aqua-schedule-card.js?v={version}")
    client = await hass_client()
    resp = await client.get("/rival_aqua/rival-aqua-schedule-card.js")
    assert resp.status == 200
    assert 'customElements.define("rival-aqua-schedule-card"' in await resp.text()


async def test_unreachable_is_not_ready(hass: HomeAssistant, controller: Controller) -> None:
    entry = await _setup(hass, controller.host)
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(entry, data={CONF_HOST: "127.0.0.1:1"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_schedule_actions(hass: HomeAssistant, controller: Controller) -> None:
    from homeassistant.exceptions import ServiceValidationError

    entry = await _setup(hass, controller.host)

    # Read back exactly what the controller has (matches the real capture)
    resp = await hass.services.async_call(
        DOMAIN, "get_schedule", {"config_entry_id": entry.entry_id},
        blocking=True, return_response=True,
    )
    assert resp["channels"] == ["Cool White", "Green", "Blue", "Warm White", "Red"]
    assert [p["time"] for p in resp["points"]] == ["09:00", "10:00", "11:00", "20:00", "21:00", "23:00"]
    assert resp["points"][2]["levels"] == [59, 10, 10, 10, 10]
    assert resp["colors"] == ["#FFFFFF", "#32CD32", "#0000ff", "#ffff00", "#ff0000"]
    assert resp["fan"] is None and resp["max_points"] == 16

    # With a single controller the entry id may be left out (the dashboard card relies on this)
    assert await hass.services.async_call(
        DOMAIN, "get_schedule", {}, blocking=True, return_response=True
    ) == resp

    # Round trip: writing it back is a no-op on the controller
    before = [list(x) for x in controller.points]
    await hass.services.async_call(
        DOMAIN, "set_schedule", {"config_entry_id": entry.entry_id, "points": resp["points"]},
        blocking=True,
    )
    assert controller.points == before and controller.times == [540, 600, 660, 1200, 1260, 1380]

    # Manual mode on, then save a new schedule (mixed list / name mapping, unsorted)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.aquarium", "brightness_pct": 80}, blocking=True
    )
    assert controller.block == 1
    await hass.services.async_call(
        DOMAIN, "set_schedule",
        {"config_entry_id": entry.entry_id, "points": [
            {"time": "21:30", "levels": [0, 0, 0, 0, 0]},
            {"time": "08:00", "levels": [0, 0, 0, 0, 0]},
            {"time": "10:00", "levels": {"cool white": 70, "Warm White": 20, "Red": 15}},
            {"time": "19:00", "levels": [70, 5, 5, 20, 15]},
        ]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert controller.times == [480, 600, 1140, 1290]
    assert controller.points[0] == [0, 70, 70, 0]   # cool white
    assert controller.points[3] == [0, 20, 20, 0]   # warm white
    assert controller.points[1] == [0, 0, 5, 0]     # green
    assert controller.points[8] == [0, 0, 0, 0]     # cooler always sent
    assert controller.block == 0 and controller.hand == 0  # schedule resumed
    log = [l for l in controller.log if l.startswith(("/pointtimes", "/pointch", "/pwm_man", "/blockrangeset"))]
    i = log.index("/pointtimes?pn=4&p0=480&p1=600&p2=1140&p3=1290")
    assert log[i + 1 : i + 10] == [f"/pointch?ch={c}" + controller_points_qs(controller, c) for c in range(9)]
    assert log[i + 10 : i + 12] == ["/pwm_man?state=false", "/blockrangeset?state=false"]
    sched = await hass.services.async_call(
        DOMAIN, "get_schedule", {"config_entry_id": entry.entry_id}, blocking=True, return_response=True
    )
    assert {p["time"]: p["levels"][0] for p in sched["points"]}["10:00"] == 70

    # Validation
    bad = [
        [{"time": "25:00", "levels": [0] * 5}],
        [{"time": "10:00", "levels": [0] * 4}],
        [{"time": "10:00", "levels": {"Purple": 4}}],
        [{"time": "10:00", "levels": [0, 0, 0, 0, 101]}],
        [{"time": "10:00", "levels": [0] * 5}, {"time": "10:00", "levels": [0] * 5}],
        [{"time": f"{h:02d}:00", "levels": [0] * 5} for h in range(17)],
    ]
    for points in bad:
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "set_schedule", {"config_entry_id": entry.entry_id, "points": points},
                blocking=True,
            )
    assert controller.times == [480, 600, 1140, 1290]  # nothing written


def controller_points_qs(controller: Controller, ch: int) -> str:
    return "".join(f"&p{i}={v}" for i, v in enumerate(controller.points[ch]))
