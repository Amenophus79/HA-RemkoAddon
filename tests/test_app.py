from __future__ import annotations

import queue
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.app import apply_command, command_settle_seconds, process_pending_commands
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
        self.assertEqual(command_settle_seconds(options(command_cooldown_seconds=5)), 30)
        self.assertEqual(command_settle_seconds(options(command_cooldown_seconds=90)), 90)

    def test_process_pending_commands_handles_only_one_command_per_call(self) -> None:
        command_queue: queue.Queue[Command] = queue.Queue()
        command_queue.put(Command("mode", "Eco"))
        command_queue.put(Command("mode", "Automatic"))
        smartweb = SmartWebFake()
        mqtt_bridge = MqttBridgeFake()

        processed = process_pending_commands(command_queue, smartweb, mqtt_bridge, options())

        self.assertTrue(processed)
        self.assertEqual(smartweb.calls, [("mode", "Eco")])
        self.assertEqual(mqtt_bridge.patches, [{"operating_mode": "Eco", "power": "ON"}])
        self.assertEqual(command_queue.qsize(), 1)


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


class MqttBridgeFake:
    def __init__(self) -> None:
        self.patches: list[dict[str, object]] = []
        self.errors: list[BaseException] = []
        self.feedback: list[tuple[str, str, bool | None]] = []

    def publish_optimistic_state(self, **values: object) -> bool:
        self.patches.append(values)
        return True

    def publish_error(self, error: BaseException) -> None:
        self.errors.append(error)

    def publish_feedback(
        self,
        status: str,
        message: str = "",
        *,
        available: bool | None = None,
    ) -> None:
        self.feedback.append((status, message, available))


def options(mode_set_retry_seconds: int = 20, command_cooldown_seconds: int = 90) -> dict:
    return {
        "remko": {
            "power_on_mode": "Automatic",
            "mode_set_retry_seconds": mode_set_retry_seconds,
            "command_cooldown_seconds": command_cooldown_seconds,
        },
        "controls": {
            "supported_modes": ["Off", "Automatic", "Eco", "Hybrid", "Fastheating", "Vacation"],
            "min_temperature": 10.0,
            "max_temperature": 60.0,
        },
    }


if __name__ == "__main__":
    unittest.main()
