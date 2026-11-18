"""Pure helpers converting between controller levels (0-100 %) and HA values."""

from __future__ import annotations

from .const import RGBWW_NAME_MAP


def level_to_brightness(level: int) -> int:
    return round(max(0, min(100, level)) * 255 / 100)


def brightness_to_level(brightness: int) -> int:
    level = round(max(0, min(255, brightness)) * 100 / 255)
    return max(1, level) if brightness > 0 else 0


def rgbww_slots(names: list[str], count: int) -> dict[int, int] | None:
    """Map channel index -> RGBWW tuple slot, or None if channels don't fit RGBWW.

    Requires every channel to have a distinct, recognised name so the combined
    light never silently ignores a channel.
    """
    slots: dict[int, int] = {}
    for idx in range(count):
        name = names[idx].strip().lower() if idx < len(names) else ""
        slot = RGBWW_NAME_MAP.get(name)
        if slot is None or slot in slots.values():
            return None
        slots[idx] = slot
    return slots if len(slots) == 5 else None


def levels_to_brightness_and_rgbww(
    levels: list[int], slots: dict[int, int]
) -> tuple[int, tuple[int, int, int, int, int]]:
    peak = max(levels, default=0)
    rgbww = [0, 0, 0, 0, 0]
    if peak > 0:
        for idx, slot in slots.items():
            rgbww[slot] = round(levels[idx] / peak * 255)
    return level_to_brightness(peak), tuple(rgbww)  # type: ignore[return-value]


def rgbww_to_levels(
    rgbww: tuple[int, ...], brightness: int, slots: dict[int, int], count: int
) -> list[int]:
    peak = max(rgbww, default=0)
    levels = [0] * count
    if peak <= 0 or brightness <= 0:
        return levels
    for idx, slot in slots.items():
        # Normalise so the strongest component maps to the requested brightness.
        levels[idx] = round(rgbww[slot] / peak * brightness / 255 * 100)
    return levels


def scale_levels(ratios: list[float], brightness: int) -> list[int]:
    """Scale a channel mix (peak == 1.0) to a brightness 0-255."""
    return [round(r * brightness / 255 * 100) for r in ratios]


def mix_ratios(levels: list[int]) -> list[float] | None:
    peak = max(levels, default=0)
    if peak <= 0:
        return None
    return [lvl / peak for lvl in levels]
