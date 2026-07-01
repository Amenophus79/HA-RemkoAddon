from __future__ import annotations

import re

TOP_LABELS = [
    "Temperatur oben",
    "Speicher oben",
    "Oben",
    "Top temperature",
    "Tank top",
]
BOTTOM_LABELS = [
    "Temperatur unten",
    "Speicher unten",
    "Unten",
    "Bottom temperature",
    "Tank bottom",
]
TARGET_LABELS = [
    "Solltemperatur",
    "Soll-Temp",
    "Soll Temp",
    "Set temperature",
    "Target temperature",
]
MODE_LABELS = [
    "Betriebsmodus",
    "Raumklima Modus",
    "Raumklimamodus",
    "Operating mode",
    "Mode",
]
STATUS_LABELS = [
    "Betriebszustand",
    "Zustand",
    "Waermepumpe Status",
    "Wärmepumpe Status",
    "Heat pump status",
    "Status",
]
POWER_LABELS = [
    "Ein/Aus",
    "Betriebszustand",
    "Power",
    "On/Off",
]
DETAIL_READY_LABELS = [
    *TOP_LABELS,
    *BOTTOM_LABELS,
    *TARGET_LABELS,
    *MODE_LABELS,
]


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip(" :\t\r\n")
    return cleaned or None


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"[-+]?\d+(?:[,.]\d+)?", value)
    if match is None:
        return None
    return float(match.group(0).replace(",", "."))


def extract_label_float(text: str, labels: list[str]) -> float | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        lower = line.lower()
        for label in labels:
            label_lower = label.lower()
            if label_lower in lower:
                start = lower.find(label_lower) + len(label_lower)
                segment = " ".join([line[start:], *lines[index + 1 : index + 3]])
                value = parse_float(segment)
                if value is not None:
                    return value
    return None


def extract_label_value(text: str, labels: list[str]) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        lower = line.lower()
        for label in labels:
            label_lower = label.lower()
            if label_lower not in lower:
                continue
            start = lower.find(label_lower) + len(label_lower)
            candidate = clean_value(line[start:])
            if candidate and not looks_like_unit_only(candidate):
                return candidate
            for next_line in lines[index + 1 : index + 3]:
                candidate = clean_value(next_line)
                if candidate and not looks_like_unit_only(candidate):
                    return candidate
    return None


def looks_like_unit_only(value: str) -> bool:
    return bool(re.fullmatch(r"[-+]?\d+(?:[,.]\d+)?\s*(?:°?c|kwh|w|hz)?", value.lower()))


def normalize_power(*values: str | None) -> str | None:
    joined = " ".join(value for value in values if value).lower()
    if not joined:
        return None
    off_tokens = ("aus", "off", "standby", "forced off", "abschaltung")
    on_tokens = ("ein", "on", "heizen", "kuehlen", "kühlen", "heating", "cooling", "auto")
    if any(re.search(rf"(^|\W){re.escape(token)}(\W|$)", joined) for token in off_tokens):
        return "OFF"
    if any(re.search(rf"(^|\W){re.escape(token)}(\W|$)", joined) for token in on_tokens):
        return "ON"
    return None


def format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")
