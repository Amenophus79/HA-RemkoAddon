from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)


class HomeAssistantLogNotifier:
    def __init__(
        self,
        options: dict[str, Any],
        writer: Callable[[dict[str, Any], str, str], bool] | None = None,
        notification_writer: Callable[[dict[str, Any], str, str], bool] | None = None,
        notification_dismisser: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self._options = options
        self._writer = writer or write_homeassistant_log
        self._notification_writer = notification_writer or create_persistent_notification
        self._notification_dismisser = notification_dismisser or dismiss_persistent_notification
        self._last_key: tuple[str, str] | None = None

    def notify_once(self, status: str, message: str, *, level: str = "warning") -> bool:
        key = (status, message)
        if key == self._last_key:
            return False
        self._last_key = key
        wrote_log = False
        wrote_notification = False
        if bool(self._options["remko"].get("homeassistant_log", True)):
            wrote_log = self._writer(self._options, level, f"{status}: {message}")
        if bool(self._options["remko"].get("homeassistant_notification", True)):
            wrote_notification = self._notification_writer(self._options, status, message)
        return wrote_log or wrote_notification

    def reset(self) -> None:
        if (
            self._last_key is not None
            and bool(self._options["remko"].get("homeassistant_notification", True))
        ):
            self._notification_dismisser(self._options)
        self._last_key = None


def write_homeassistant_log(options: dict[str, Any], level: str, message: str) -> bool:
    payload = {
        "message": message,
        "level": level,
        "logger": str(options["remko"].get("homeassistant_log_logger") or "remko_smartweb_mqtt"),
    }
    return call_homeassistant_service("system_log", "write", payload)


def create_persistent_notification(
    options: dict[str, Any],
    status: str,
    message: str,
) -> bool:
    payload = {
        "title": "REMKO SmartWeb MQTT",
        "message": f"Status: {status}\n\n{message}",
        "notification_id": notification_id(options),
    }
    return call_homeassistant_service("persistent_notification", "create", payload)


def dismiss_persistent_notification(options: dict[str, Any]) -> bool:
    return call_homeassistant_service(
        "persistent_notification",
        "dismiss",
        {"notification_id": notification_id(options)},
    )


def notification_id(options: dict[str, Any]) -> str:
    return str(
        options["remko"].get("homeassistant_notification_id")
        or "remko_smartweb_mqtt_unavailable"
    )


def call_homeassistant_service(domain: str, service: str, payload: dict[str, Any]) -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        LOGGER.debug("SUPERVISOR_TOKEN is not set; cannot call Home Assistant service")
        return False

    try:
        import requests
    except ImportError:
        LOGGER.debug("requests is not installed; cannot call Home Assistant service")
        return False

    try:
        response = requests.post(
            f"http://supervisor/core/api/services/{domain}/{service}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except Exception:
        LOGGER.warning("Could not call Home Assistant service %s.%s", domain, service, exc_info=True)
        return False
    return True
