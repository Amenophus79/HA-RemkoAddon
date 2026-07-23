from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt import APP_VERSION
from remko_smartweb_mqtt.config import ConfigError, ensure_credentials_template, load_options


class ConfigTests(unittest.TestCase):
    def test_package_version_matches_addon_config_version(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt" / "config.yaml"
        config_text = config_path.read_text(encoding="utf-8")
        match = re.search(r'^version:\s*"([^"]+)"', config_text, re.MULTILINE)

        self.assertIsNotNone(match)
        self.assertEqual(APP_VERSION, match.group(1))

    def test_ensure_credentials_template_uses_configured_credentials_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials_path = root / "nested" / "credentials.json"
            options_path = root / "options.json"
            options_path.write_text(
                json.dumps({"remko": {"credentials_file": str(credentials_path)}}),
                encoding="utf-8",
            )

            template_path = ensure_credentials_template(options_path)

            self.assertEqual(template_path, root / "nested" / "credentials.example.json")
            data = json.loads(template_path.read_text(encoding="utf-8"))
            self.assertEqual(data["remko"]["device_name"], "WIFI Stick - Warmwasserwärmepumpe")
            self.assertEqual(data["mqtt"]["host"], "auto")

    def test_ensure_credentials_template_does_not_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials_path = root / "credentials.json"
            template_path = root / "credentials.example.json"
            options_path = root / "options.json"
            options_path.write_text(
                json.dumps({"remko": {"credentials_file": str(credentials_path)}}),
                encoding="utf-8",
            )
            template_path.write_text("keep me\n", encoding="utf-8")

            returned_path = ensure_credentials_template(options_path)

            self.assertEqual(returned_path, template_path)
            self.assertEqual(template_path.read_text(encoding="utf-8"), "keep me\n")

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
