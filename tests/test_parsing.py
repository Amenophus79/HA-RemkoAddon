from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.parsing import (
    BOTTOM_LABELS,
    MODE_LABELS,
    STATUS_LABELS,
    TARGET_LABELS,
    TOP_LABELS,
    extract_label_float,
    extract_label_value,
    format_number,
    normalize_power,
)


class ParsingTests(unittest.TestCase):
    def test_extracts_temperatures_and_state_from_remko_text(self) -> None:
        text = """
        Warmwasserwärmepumpe
        Temperatur oben
        48,7 °C
        Temperatur unten
        42.1 °C
        Solltemperatur
        50 °C
        Betriebsmodus
        Auto
        Betriebszustand
        Heizen
        """

        self.assertEqual(extract_label_float(text, TOP_LABELS), 48.7)
        self.assertEqual(extract_label_float(text, BOTTOM_LABELS), 42.1)
        self.assertEqual(extract_label_float(text, TARGET_LABELS), 50.0)
        self.assertEqual(extract_label_value(text, MODE_LABELS), "Auto")
        self.assertEqual(extract_label_value(text, STATUS_LABELS), "Heizen")
        self.assertEqual(normalize_power("Heizen"), "ON")

    def test_handles_unavailable_overview_without_fake_temperatures(self) -> None:
        overview = """
        Device-Overview
        Product Filter
        WIFI Stick - Warmwasserwärmepumpe
        Operator: Norman Trapp
        Add Device
        """

        self.assertIsNone(extract_label_float(overview, TOP_LABELS))
        self.assertIsNone(extract_label_float(overview, BOTTOM_LABELS))
        self.assertIsNone(extract_label_value(overview, MODE_LABELS))
        self.assertIsNone(normalize_power(None, None, None))

    def test_formats_numbers_for_smartweb_inputs(self) -> None:
        self.assertEqual(format_number(50.0), "50")
        self.assertEqual(format_number(48.5), "48.5")


if __name__ == "__main__":
    unittest.main()
