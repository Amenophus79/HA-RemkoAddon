from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .modes import canonicalize_mode


class ConfigError(RuntimeError):
    """Raised when the add-on configuration is incomplete or invalid."""


CREDENTIALS_TEMPLATE: dict[str, Any] = {
    "remko": {
        "username": "your-remko-login@example.com",
        "password": "your-remko-password",
        "device_name": "WIFI Stick - Warmwasserwärmepumpe",
    },
    "mqtt": {
        "host": "auto",
        "port": 1883,
        "username": "",
        "password": "",
    },
}


DEFAULT_OPTIONS: dict[str, Any] = {
    "remko": {
        "base_url": "https://smartweb.remko.media/",
        "overview_url": "https://smartweb.remko.media/liste",
        "device_url": "",
        "credentials_file": "/config/credentials.json",
        "username": "",
        "password": "",
        "device_name": "WIFI Stick - Warmwasserwärmepumpe",
        "poll_interval_minutes": 15,
        "request_timeout_seconds": 90,
        "live_value_timeout_seconds": 300,
        "live_value_check_interval_seconds": 10,
        "ignore_zero_temperatures": True,
        "mode_set_attempts": 3,
        "mode_set_retry_seconds": 20,
        "command_cooldown_seconds": 90,
        "power_on_mode": "Automatic",
        "homeassistant_log": True,
        "homeassistant_log_logger": "remko_smartweb_mqtt",
        "homeassistant_notification": True,
        "homeassistant_notification_id": "remko_smartweb_mqtt_unavailable",
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
        "supported_modes": ["Off", "Automatic", "Eco", "Hybrid", "Fastheating", "Vacation"],
        "min_temperature": 10.0,
        "max_temperature": 60.0,
        "temperature_step": 0.5,
    },
    "selectors": {
        "username_input": "[id='benutzer']",
        "password_input": "[id='password']",
        "login_button": "[id='login_do']",
        "device_link": "",
        "temperature_top": "[id='RoomValue']",
        "temperature_bottom": "[id='IndoorValue']",
        "target_temperature": "[id='ID1333_000_000_value']",
        "operating_mode": "[id='ID1192_000_000_value']",
        "status": "",
        "power_state": "",
        "power_on_button": "",
        "power_off_button": "",
        "mode_control": "",
        "operating_mode_button": "[id='ID1192_000_button']",
        "active_mode": "",
        "target_temperature_button": "[id='ID1333_000_button']",
        "timer_button": "[id='ID1404_000_button']",
        "target_temperature_input": "",
        "save_button": "",
    },
}


def ensure_credentials_template(path: str | os.PathLike[str] = "/data/options.json") -> Path:
    configured = load_json_file(path)
    remko_options = configured.get("remko") if isinstance(configured.get("remko"), dict) else {}
    credentials_file = str(
        remko_options.get("credentials_file")
        or DEFAULT_OPTIONS["remko"]["credentials_file"]
    ).strip()
    credentials_path = Path(credentials_file or DEFAULT_OPTIONS["remko"]["credentials_file"])
    template_path = credentials_path.parent / "credentials.example.json"

    try:
        template_path.parent.mkdir(parents=True, exist_ok=True)
        if not template_path.exists():
            template_path.write_text(
                json.dumps(CREDENTIALS_TEMPLATE, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except OSError as exc:
        raise ConfigError(f"Could not create credentials template at {template_path}: {exc}") from exc
    return template_path


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
    if int(remko["live_value_timeout_seconds"]) < 0:
        raise ConfigError("live_value_timeout_seconds must not be negative")
    if int(remko["live_value_check_interval_seconds"]) < 1:
        raise ConfigError("live_value_check_interval_seconds must be at least 1")
    if int(remko["mode_set_attempts"]) < 1:
        raise ConfigError("mode_set_attempts must be at least 1")
    if int(remko["mode_set_retry_seconds"]) < 0:
        raise ConfigError("mode_set_retry_seconds must not be negative")
    if int(remko["command_cooldown_seconds"]) < 0:
        raise ConfigError("command_cooldown_seconds must not be negative")
    controls = options["controls"]
    if float(controls["min_temperature"]) >= float(controls["max_temperature"]):
        raise ConfigError("min_temperature must be lower than max_temperature")

    modes = [mode for mode in controls.get("supported_modes", []) if str(mode).strip()]
    if not modes:
        raise ConfigError("supported_modes must contain at least one mode")
    controls["supported_modes"] = modes
    power_on_mode = canonicalize_mode(str(remko["power_on_mode"]), modes)
    if not power_on_mode:
        raise ConfigError("power_on_mode must be one of supported_modes")
    remko["power_on_mode"] = power_on_mode
