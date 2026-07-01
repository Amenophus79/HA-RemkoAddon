from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.homeassistant_log import HomeAssistantLogNotifier


class HomeAssistantLogTests(unittest.TestCase):
    def test_notifies_only_once_for_same_status_and_message(self) -> None:
        calls: list[tuple[str, str]] = []
        notifications: list[tuple[str, str]] = []
        options = {"remko": {"homeassistant_log": True}}
        notifier = HomeAssistantLogNotifier(
            options,
            writer=lambda _options, level, message: calls.append((level, message)) is None,
            notification_writer=lambda _options, status, message: notifications.append((status, message)) is None,
        )

        self.assertTrue(notifier.notify_once("unavailable", "pump offline"))
        self.assertFalse(notifier.notify_once("unavailable", "pump offline"))

        self.assertEqual(calls, [("warning", "unavailable: pump offline")])
        self.assertEqual(notifications, [("unavailable", "pump offline")])

    def test_reset_allows_same_message_after_recovery(self) -> None:
        calls: list[str] = []
        dismissed: list[bool] = []
        options = {"remko": {"homeassistant_log": True}}
        notifier = HomeAssistantLogNotifier(
            options,
            writer=lambda _options, _level, message: calls.append(message) is None,
            notification_writer=lambda _options, _status, _message: True,
            notification_dismisser=lambda _options: dismissed.append(True) is None,
        )

        notifier.notify_once("unavailable", "pump offline")
        notifier.reset()
        notifier.notify_once("unavailable", "pump offline")

        self.assertEqual(len(calls), 2)
        self.assertEqual(dismissed, [True])

    def test_disabled_option_suppresses_homeassistant_log(self) -> None:
        calls: list[str] = []
        notifications: list[str] = []
        options = {"remko": {"homeassistant_log": False, "homeassistant_notification": False}}
        notifier = HomeAssistantLogNotifier(
            options,
            writer=lambda _options, _level, message: calls.append(message) is None,
            notification_writer=lambda _options, _status, message: notifications.append(message) is None,
        )

        self.assertFalse(notifier.notify_once("unavailable", "pump offline"))
        self.assertEqual(calls, [])
        self.assertEqual(notifications, [])


if __name__ == "__main__":
    unittest.main()
