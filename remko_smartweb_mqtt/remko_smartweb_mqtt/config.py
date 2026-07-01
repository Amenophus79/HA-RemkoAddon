from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised when the add-on configuration is incomplete or invalid."""


DEFAULT_OPTIONS: dict[str, Any] = {
    "remko": {
        "base_url": "https://smartweb.remko.media/",
        "overview_url": "",
        "credentials_file": "/data/credentials.json",
        "username": "",
        "password": "",
        "device_name": "",
        "poll_interval_minutes": 15,
        "request_timeout_seconds": 90,
    },
    "mqtt": {
        "host": "auto",
        "port": 1883,
        "username": "",
        "password": "",
        "topic_prefix": "remko",
        "discovery_prefix": "homeassistant",
        "retain_state": False,
    },
    "controls": {
        "supported_modes": ["Auto", "Heizen", "Kühlen", "Standby", "Aus"],
        "min_temperature": 10.0,
        "max_temperature": 60.0,
        "temperature_step": 0.5,
    },
    "selectors": {
        "username_input": "",
        "password_input": "",
        "login_button": "",
        "device_link": "",
        "temperature_top": "",
        "temperature_bottom": "",
        "target_temperature": "",
        "operating_mode": "",
        "status": "",
        "power_state": "",
        "power_on_button": "",
        "power_off_button": "",
        "mode_control": "",
        "target_temperature_input": "",
        "save_button": "",
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_options(path: str | os.PathLike[str] = "/data/options.json") -> dict[str, Any]:
    configured = load_json_file(path)
    options = deep_merge(DEFAULT_OPTIONS, configured)
    credentials = load_credentials_file(options["remko"].get("credentials_file", ""))
    if credentials:
        options = deep_merge(options, credentials)
    validate_options(options)
    return options


def load_json_file(path: str | os.PathLike[str]) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ConfigError(f"{file_path} must contain a JSON object")
    return data


def load_credentials_file(path: str | os.PathLike[str]) -> dict[str, Any]:
    if not str(path or "").strip():
        return {}
    data = load_json_file(path)
    if not data:
        return {}
    if "remko" in data or "mqtt" in data:
        return data

    credentials: dict[str, Any] = {}
    remko = {
        key: data[key]
        for key in ("username", "password", "device_name")
        if key in data
    }
    mqtt = {
        option: data[key]
        for key, option in (
            ("mqtt_host", "host"),
            ("mqtt_port", "port"),
            ("mqtt_username", "username"),
            ("mqtt_password", "password"),
        )
        if key in data
    }
    if remko:
        credentials["remko"] = remko
    if mqtt:
        credentials["mqtt"] = mqtt
    return credentials


def validate_options(options: dict[str, Any]) -> None:
    remko = options["remko"]
    missing = [
        key
        for key in ("username", "password", "device_name")
        if not str(remko.get(key) or "").strip()
    ]
    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing required REMKO option(s): {joined}")

    interval = int(remko["poll_interval_minutes"])
    if interval < 1:
        raise ConfigError("poll_interval_minutes must be at least 1")

    controls = options["controls"]
    if float(controls["min_temperature"]) >= float(controls["max_temperature"]):
        raise ConfigError("min_temperature must be lower than max_temperature")

    modes = [mode for mode in controls.get("supported_modes", []) if str(mode).strip()]
    if not modes:
        raise ConfigError("supported_modes must contain at least one mode")
    controls["supported_modes"] = modes
