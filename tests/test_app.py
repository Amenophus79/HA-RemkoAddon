from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.app import apply_command, command_settle_seconds
from remko_smartweb_mqtt.models import Command


class AppCommandTests(unittest.TestCase):
    def test_power_off_command_sets_off_mode_patch(self) -> None:
        smartweb = SmartWebFake()

        patch = apply_command(Command("power", False), smartweb, options())

        self.assertEqual(smartweb.calls, [("power", False)])
        self.assertEqual(patch, {"operating_mode": "Off", "power": "OFF"})

    def test_mode_command_sets_mode_patch(self) -> None:
        smartweb = SmartWebFake()

        patch = apply_command(Command("mode", "Eco"), smartweb, options())

        self.assertEqual(smartweb.calls, [("mode", "Eco")])
        self.assertEqual(patch, {"operating_mode": "Eco", "power": "ON"})

    def test_command_settle_seconds_uses_at_least_default_delay(self) -> None:
        self.assertEqual(command_settle_seconds(options(mode_set_retry_seconds=5)), 30)
        self.assertEqual(command_settle_seconds(options(mode_set_retry_seconds=45)), 45)


class SmartWebFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_power(self, enabled: bool) -> bool:
        self.calls.append(("power", enabled))
        return True

    def set_mode(self, mode: str) -> bool:
        self.calls.append(("mode", mode))
        return True

    def set_temperature(self, temperature: float) -> None:
        self.calls.append(("temperature", temperature))


def options(mode_set_retry_seconds: int = 20) -> dict:
    return {
        "remko": {
            "power_on_mode": "Automatic",
            "mode_set_retry_seconds": mode_set_retry_seconds,
        },
        "controls": {
            "supported_modes": ["Off", "Automatic", "Eco", "Hybrid", "Fastheating", "Vacation"],
            "min_temperature": 10.0,
            "max_temperature": 60.0,
        },
    }


if __name__ == "__main__":
    unittest.main()
