from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.mqtt_bridge import slugify


class MqttBridgeTests(unittest.TestCase):
    def test_slugify_removes_separator_punctuation(self) -> None:
        self.assertEqual(
            slugify("WIFI Stick - Warmwasserwärmepumpe"),
            "wifi_stick_warmwasserw_rmepumpe",
        )


if __name__ == "__main__":
    unittest.main()
