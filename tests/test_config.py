from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.config import ConfigError, load_options


class ConfigTests(unittest.TestCase):
    def test_credentials_file_overrides_addon_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials_path = root / "credentials.json"
            options_path = root / "options.json"
            credentials_path.write_text(
                json.dumps(
                    {
                        "remko": {
                            "username": "real@example.com",
                            "password": "secret",
                            "device_name": "WIFI Stick - Warmwasserwärmepumpe",
                        },
                        "mqtt": {"host": "mqtt.local"},
                    }
                ),
                encoding="utf-8",
            )
            options_path.write_text(
                json.dumps(
                    {
                        "remko": {
                            "credentials_file": str(credentials_path),
                            "username": "placeholder",
                            "password": "placeholder",
                            "device_name": "placeholder",
                            "poll_interval_minutes": 7,
                        }
                    }
                ),
                encoding="utf-8",
            )

            options = load_options(options_path)

        self.assertEqual(options["remko"]["username"], "real@example.com")
        self.assertEqual(options["remko"]["device_name"], "WIFI Stick - Warmwasserwärmepumpe")
        self.assertEqual(options["remko"]["poll_interval_minutes"], 7)
        self.assertEqual(options["mqtt"]["host"], "mqtt.local")

    def test_missing_credentials_raise_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options_path = Path(temp_dir) / "options.json"
            options_path.write_text(json.dumps({"remko": {"credentials_file": ""}}), encoding="utf-8")

            with self.assertRaises(ConfigError) as ctx:
                load_options(options_path)

        self.assertIn("Missing required REMKO option", str(ctx.exception))

    def test_power_on_mode_accepts_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options_path = Path(temp_dir) / "options.json"
            options_path.write_text(
                json.dumps(
                    {
                        "remko": {
                            "credentials_file": "",
                            "username": "user@example.com",
                            "password": "secret",
                            "device_name": "WIFI Stick - Warmwasserwärmepumpe",
                            "power_on_mode": "Automatisch",
                        }
                    }
                ),
                encoding="utf-8",
            )

            options = load_options(options_path)

        self.assertEqual(options["remko"]["power_on_mode"], "Automatic")


if __name__ == "__main__":
    unittest.main()
