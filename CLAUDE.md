# ha-rival-aqua

Home Assistant custom integration (`custom_components/rival_aqua`, domain `rival_aqua`) for
Rival Aqua aquarium LED lights with the Rival WiFi controller (Kremenchuk, Ukraine).
Local polling over HTTP, no cloud. Distributed via HACS.

## The device

- Viktor's controller: `http://192.168.5.200` on the IoT network. 5 channels:
  Cool White, Green, Blue, Warm White, Red. Fan disabled (`/chnumb` → `5,0,1`).
- ESP-based firmware with its own web UI (index.html + uscript.js, config.html). The whole API was
  reverse-engineered from those scripts. See the API table in README.md.
- Plain `GET` only, `text/plain`, no auth. The device is weak: send requests **sequentially**
  (the client serialises them with a lock).
- No NTP: the clock is set via `/synchtime`. The integration syncs it every 6 h.
- Manual mode = `/handmode?onoff=1` + `/pwm_man?state=true` + `/blockrangeset?state=true`.
  Any HA light change enters manual mode first. The "Manual mode" switch off resumes the schedule.
- Schedule save (web UI "Save" button, `savepoint()` in uscript.js):
  `/pointtimes?pn=N&p0=<min>..` → `/pointch?ch=0..8&p0=<level>..` (always 9 channels, 8 = cooler,
  zeros for unused) → `/pwm_man?state=false` → `/blockrangeset?state=false`.
  Max 16 interior points (the UI allows 18 including the fixed 00:00 and 24:00 ends).

## Working with the real controller

- Read-only probes are fine any time: `python3 tools/rival_probe.py 192.168.5.200`
  or `curl http://192.168.5.200/curlevelrange`.
- **Ask Viktor before any write** (`/light`, `/lightsetmode`, `/handmode`, `/pointtimes`, `/pointch`,
  ...). It changes the light over a live aquarium.
- Not yet verified on real hardware: write paths in manual mode, and whether the schedule save
  round-trips (save the current schedule unchanged, then check `/chartdata.js` is identical).
  Also unverified: every settings write (`/saveparam` + `/savenamechan`, `/color`, `/fanenset`,
  Wi-Fi join/forget, `/setdefault`); in particular whether `/saveparam` restarts the hotspot or reboots.
- Never commit real values read from the controller (hotspot password, nearby SSIDs): the repo is public.

## Code layout

- `api.py`: aiohttp client, no HA imports (testable standalone). Parsing of the JS files lives here.
- `coordinator.py`: DataUpdateCoordinator, 10 s poll, write helpers that raise HomeAssistantError.
- `light.py`: combined RGBWW light (maps the 5 channels by name, see `levels.py`) plus one light per channel.
  The channel lights are hidden (registry `hidden_by=integration`) unless the controller is in manual mode.
- `switch.py` (manual mode, night indicator), `button.py` (restart), `fan.py` (cooler, only if enabled),
  `sensor.py` (network, diagnostic). Device page: Controls = main light + manual mode (+ channels in
  manual mode); Configuration = restart + night indicator. Entities dropped in 0.5.0 are removed from
  the registry in `__init__._async_remove_old_entities`.
- `services.py`: schedule get/set, plus hotspot, Wi-Fi scan/join/forget and factory reset.
- `frontend/rival-aqua-schedule-card.js`: schedule editor card (no build step), served by `__init__.py`.

## Tests

```bash
pip install pytest-homeassistant-custom-component
pytest                                 # HA end-to-end tests against tests/mock_controller.py
python3 tests/check_api_standalone.py  # API client only
```

`tests/mock_controller.py` reproduces the real responses captured on 2026-11-18. Keep it in sync if
real hardware behaves differently.

## Conventions

- Python 3.13, ruff (`ruff check custom_components --select E,F,W,B,UP,I --ignore E501`).
- Translations: `strings.json` + `translations/en.json` + `translations/uk.json`. Keep all three in sync.
- Bump `version` in `manifest.json` on every release.
