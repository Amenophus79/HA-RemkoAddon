from __future__ import annotations

from .parsing import clean_value

MODE_ALIASES = {
    "automatisch": ["automatic", "auto"],
    "automatic": ["automatisch", "auto"],
    "heizen": ["heating", "heat"],
    "heating": ["heizen", "heat"],
    "kühlen": ["kuehlen", "cooling", "cool"],
    "kuehlen": ["kühlen", "cooling", "cool"],
    "cooling": ["kühlen", "kuehlen", "cool"],
    "aus": ["off"],
    "off": ["aus"],
    "fastheating": ["fast heating", "schnellheizen", "schnellladung"],
    "fast heating": ["fastheating", "schnellheizen", "schnellladung"],
    "vacation": ["holiday", "urlaub"],
    "holiday": ["vacation", "urlaub"],
}


def canonicalize_mode(value: str | None, supported_modes: list[str]) -> str | None:
    cleaned = clean_value(value)
    if not cleaned:
        return None
    for mode in supported_modes:
        if text_matches_mode(cleaned, mode):
            return mode
    return None


def text_matches_mode(text: str | None, desired: str) -> bool:
    current = clean_value(text)
    wanted = clean_value(desired)
    if not current or not wanted:
        return False
    current_lower = current.casefold()
    wanted_lower = wanted.casefold()
    if current_lower == wanted_lower:
        return True
    if current_lower in mode_aliases(wanted_lower):
        return True
    if wanted_lower in mode_aliases(current_lower):
        return True
    return (
        len(wanted_lower) >= 3
        and current_lower.startswith(wanted_lower)
    ) or (
        len(current_lower) >= 3
        and wanted_lower.startswith(current_lower)
    )


def count_visible_modes(text: str, supported_modes: list[str]) -> int:
    text_lower = text.casefold()
    count = 0
    for mode in supported_modes:
        mode_lower = clean_value(mode)
        if not mode_lower:
            continue
        mode_lower = mode_lower.casefold()
        candidates = [mode_lower, *mode_aliases(mode_lower)]
        if any(candidate in text_lower for candidate in candidates):
            count += 1
    return count


def mode_click_labels(mode: str, supported_modes: list[str]) -> list[str]:
    labels = unique_values([mode])
    for supported_mode in supported_modes:
        if text_matches_mode(supported_mode, mode):
            labels.append(supported_mode)
    labels.extend(mode_aliases(mode.casefold()))
    return unique_values(labels)


def mode_aliases(mode: str) -> list[str]:
    return MODE_ALIASES.get(mode.casefold(), [])


def unique_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = clean_value(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result
