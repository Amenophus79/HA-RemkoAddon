from __future__ import annotations

import queue
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.mqtt_bridge import (
    MqttBridge,
    MqttConnectionError,
    mqtt_host_candidates,
    slugify,
)


class MqttBridgeTests(unittest.TestCase):
    def test_slugify_removes_separator_punctuation(self) -> None:
        self.assertEqual(
            slugify("WIFI Stick - Warmwasserwärmepumpe"),
            "wifi_stick_warmwasserw_rmepumpe",
        )

    def test_mqtt_host_candidates_add_home_assistant_mosquitto_aliases(self) -> None:
        self.assertEqual(
            mqtt_host_candidates("core-mosquitto"),
            ["core-mosquitto", "core-mosquitto.local.hass.io", "addon_core_mosquitto"],
        )

    def test_connect_tries_mosquitto_alias_when_core_hostname_fails(self) -> None:
        bridge = MqttBridge(self._options("core-mosquitto"), queue.Queue())
        client = RetryClient(success_host="addon_core_mosquitto")
        bridge.client = client

        with self.assertLogs("remko_smartweb_mqtt.mqtt_bridge", level="WARNING"):
            bridge.connect()

        self.assertEqual(
            client.attempts,
            ["core-mosquitto", "core-mosquitto.local.hass.io", "addon_core_mosquitto"],
        )
        self.assertEqual(bridge.host, "addon_core_mosquitto")
        self.assertTrue(client.loop_started)

    def test_connect_reports_all_mqtt_candidates_when_unreachable(self) -> None:
        bridge = MqttBridge(self._options("core-mosquitto"), queue.Queue())
        client = RetryClient(success_host="")
        bridge.client = client

        with self.assertLogs("remko_smartweb_mqtt.mqtt_bridge", level="WARNING"):
            with self.assertRaises(MqttConnectionError) as ctx:
                bridge.connect()

        self.assertIn("core-mosquitto:1883", str(ctx.exception))
        self.assertIn("addon_core_mosquitto:1883", str(ctx.exception))
        self.assertFalse(client.loop_started)

    def _options(self, host: str) -> dict:
        return {
            "remko": {"device_name": "WIFI Stick - Warmwasserwärmepumpe"},
            "mqtt": {
                "host": host,
                "port": 1883,
                "username": "",
                "password": "",
                "topic_prefix": "remko",
                "discovery_prefix": "homeassistant",
                "retain_state": False,
            },
            "controls": {
                "supported_modes": ["Off", "Automatic"],
                "min_temperature": 10.0,
                "max_temperature": 60.0,
                "temperature_step": 0.5,
            },
        }


class RetryClient:
    def __init__(self, success_host: str) -> None:
        self.success_host = success_host
        self.attempts: list[str] = []
        self.loop_started = False

    def connect(self, host: str, port: int, keepalive: int) -> int:
        self.attempts.append(host)
        if host != self.success_host:
            raise socket.gaierror(-5, "Name has no usable address")
        return 0

    def loop_start(self) -> None:
        self.loop_started = True


if __name__ == "__main__":
    unittest.main()
