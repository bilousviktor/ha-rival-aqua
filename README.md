# Rival Aqua for Home Assistant

Local control of **Rival Aqua** aquarium LED lights (Rival WiFi controller, Kremenchuk, Ukraine)
from Home Assistant. No cloud and no app: the integration talks to the controller's own web API
over your LAN.

## What you get

| Entity | What it does |
|---|---|
| `light.<name>` | All channels as one light (there are no per-channel lights). With the stock channels (Cool White, Green, Blue, Warm White, Red) it's an **RGBWW** light; otherwise brightness-only, scaling the current mix. |
| `switch.<name>_manual_mode` | Auto/hand toggle. **On** = manual levels, **off** = the controller follows its own daily schedule. |
| `fan.<name>_cooler` | Only if the cooler is enabled on the controller. |

The controller clock is synced from HA automatically every 6 h.

### Settings (the controller's settings page)

Device page → *Configuration* and *Diagnostic*:

| Entity / action | What it does |
|---|---|
| `switch.<name>_night_indicator` | The controller's night status LED ("Ночная индикация"). |
| `button.<name>_restart` | Reboots the controller. It reconnects on its own. |
| `sensor.<name>_ip_address`, `_wi_fi_network`, `_hotspot_name` | Network details (diagnostic). The hotspot password is never stored in a state. |
| `rival_aqua.set_hotspot` | Changes the controller's own hotspot name (4-20 of `A-Z a-z 0-9 - _`) and/or password (8-12 digits). |
| `rival_aqua.scan_wifi` | Lists the Wi-Fi networks the controller sees (returns a response). |
| `rival_aqua.connect_wifi` | Joins another home network. ⚠️ It leaves the current one: HA loses it until you add it again with its new IP. |
| `rival_aqua.forget_wifi` | Forgets the home network and reboots into hotspot-only mode. ⚠️ HA can't reach it afterwards; reconnect via its hotspot. |
| `rival_aqua.factory_reset` | The settings page's Reset. ⚠️ Back up the schedule first (card → download icon). |

Firmware updates stay on the controller's own web page.

### Schedule (periods and levels)

Live changes from the lights above don't need saving, same as manual mode in the web UI. To change the
**stored daily schedule** use the schedule card or the actions below.

### Schedule card

The integration ships a dashboard card that edits the schedule like the controller's own chart. It is
loaded automatically: no resource to add. Edit a dashboard → *Add card* → search **Rival Aqua schedule**,
or in YAML:

```yaml
type: custom:rival-aqua-schedule-card
title: Aquarium            # optional
# config_entry_id: ...     # only with several controllers (or `entity: light.aquarium`)
# height: 280              # optional chart height in px
```

* Drag a point **sideways** to move its time (5-minute steps, hold Shift for 1 minute) or **up/down** to
  change that channel's level. The drag locks to whichever direction you start in.
* Tap empty space and press **Add point**, or double-tap to add one right away. The new point takes
  the levels the curve already has at that time.
* Select a point to set its exact time and every channel's level, or to delete it (also Delete key).
* The colour chips at the top edit one channel alone. Use them when several lines overlap.
* The download icon saves the schedule as a CSV in the same format as the controller's preset file
  (settings page → Presets). The upload icon loads such a file into the editor; check it, then Save.
* Nothing reaches the light until **Save**. Save sends what the web UI's Save button sends, turns
  manual mode off, and reads the schedule back from the controller. **Revert** discards your edits.

 `set_schedule` sends exactly what the web UI's **Save**
button sends, so the schedule is saved on the controller and keeps running even without Home Assistant.

```yaml
# Read the current schedule (Developer tools → Actions, or in a script with response_variable)
action: rival_aqua.get_schedule
data:
  config_entry_id: <your entry id>

# Save a new one. Levels per point: a list in channel order
# (Cool White, Green, Blue, Warm White, Red) or a mapping by channel name.
action: rival_aqua.set_schedule
data:
  config_entry_id: <your entry id>
  points:
    - { time: "09:00", levels: [0, 0, 0, 0, 0] }
    - { time: "10:00", levels: { Cool White: 60, Warm White: 10, Red: 10 } }
    - { time: "20:00", levels: [60, 10, 10, 10, 10] }
    - { time: "22:00", levels: [0, 0, 0, 0, 0] }
```

Up to 16 points; times strictly increasing; the light ramps linearly between points. Saving also
turns manual mode off so the new schedule takes effect immediately.

**Any change from Home Assistant switches the controller to manual mode** (the schedule pauses), like
the hand icon in the web UI. Turn **Manual mode** off to resume the schedule.

## Install

**HACS:** HACS → ⋮ → *Custom repositories* → add this repo as an *Integration* → install → restart HA.

**Manual:** copy `custom_components/rival_aqua` into `/config/custom_components/` and restart HA.

Then go to *Settings → Devices & services → Add integration → Rival Aqua* and enter the controller's IP.

### Network notes

* Home Assistant must reach the controller on TCP port 80. If the light is on an isolated IoT VLAN,
  allow HA → controller traffic.
* The controller has no MAC/serial endpoint, so the IP is its identity: **give it a DHCP reservation**.
* The controller has no NTP. The schedule runs on its internal clock, so the integration keeps that
  clock synced; this also fixes drift after power cuts.

## Automation ideas

```yaml
# Dim to a blue "moonlight" for feeding time, then return to the schedule
- alias: Aquarium feeding light
  triggers:
    - trigger: time
      at: "19:30:00"
  actions:
    - action: light.turn_on
      target: { entity_id: light.aquarium }
      data: { rgbww_color: [0, 0, 255, 0, 0], brightness_pct: 15 }
    - delay: "00:10:00"
    - action: switch.turn_off
      target: { entity_id: switch.aquarium_manual_mode }
```

## Controller API (reverse-engineered from its web UI)

All endpoints are `GET` on port 80, `text/plain` responses, no auth.

| Endpoint | Meaning |
|---|---|
| `/chnumb` | `channels,fan_enabled,night_indicator` (e.g. `5,0,1`) |
| `/curlevelrange` | the schedule's levels right now in %, `;`-separated (fan last if enabled). **Not** the output in manual mode: it keeps reporting the schedule |
| `/chmanlvl?ch=N` | manual-mode level of channel N in % (8 = cooler); the actual output while in manual mode |
| `/handmodestate`, `/blockrange` | manual-mode flags `0`/`1` |
| `/chmanlvl?ch=N` | stored manual level of channel N |
| `/namechannellist.js`, `/color.js` | channel names and colours (JS arrays) |
| `/chartdata.js` | the daily schedule (Chart.js datasets) |
| `/curver`, `/curip`, `/curhomelan` | firmware version, IP, home WiFi |
| `/light?range=N&level=0-100` | set one channel (`N=8` is the cooler) |
| `/lightsetmode?ch=5&l0=..&l4=..[&f=..]` | set all channels |
| `/handmode?onoff=1`, `/pwm_man?state=true`, `/blockrangeset?state=true` | enter manual mode (`0`/`false` to leave) |
| `/synchtime?hour=H&min=M&sec=S` | set the clock |
| `/lightset?state=true/false` | night indicator |
| `/pointtimes?pn=N&p0=<min>..` then `/pointch?ch=0..8&p0=<lvl>..`, then `/pwm_man?state=false` + `/blockrangeset?state=false` | **Save** the schedule (the web UI's save button) |
| `/user_preset.csv` | schedule as CSV: times row, then 9 channel rows (upload is `POST /upload`, field `photo`) |
| `/wifisetup.js` | hotspot name and password (JS vars, readable without auth) |
| `/saveparam?namepoint=..&passpoint=..` then `/savenamechan?name0=..` | settings page **Save**: hotspot, then channel names |
| `/color?range=N&level=RRGGBB` | channel colour (applied immediately) |
| `/fanenset?state=true/false` | enable the cooler channel |
| `/scanlan` then `/wifilist.js`; `/connectwifi?namewifi=..&passwifi=..` (answers `connect`) | Wi-Fi scan and join; empty values + `/reboot` = forget |
| `/reboot`, `/setdefault` | reboot, reset to defaults |

`tools/rival_probe.py <ip>` prints the read-only values for a quick check.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest            # runs the integration against tests/mock_controller.py
```
