"""Constants for the Rival Aqua integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "rival_aqua"
MANUFACTURER = "Rival Aqua"

CARD_FILENAME = "rival-aqua-schedule-card.js"
CARD_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=10)
TIME_SYNC_INTERVAL = timedelta(hours=6)

# Channel names (as reported by /namechannellist.js, lower-cased, stripped)
# mapped onto Home Assistant's RGBWW tuple order: R, G, B, cold white, warm white.
RGBWW_NAME_MAP: dict[str, int] = {
    "red": 0,
    "green": 1,
    "blue": 2,
    "cool white": 3,
    "cold white": 3,
    "warm white": 4,
}
