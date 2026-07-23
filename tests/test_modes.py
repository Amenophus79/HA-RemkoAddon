from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.modes import (
    canonicalize_mode,
    count_visible_modes,
    mode_click_labels,
)


class ModeTests(unittest.TestCase):
    def test_canonicalizes_english_automatic_to_configured_mode(self) -> None:
        supported = ["Off", "Automatic", "Eco", "Hybrid", "Fastheating", "Vacation"]

        self.assertEqual(canonicalize_mode("Automatisch", supported), "Automatic")
        self.assertEqual(canonicalize_mode("Auto", supported), "Automatic")
        self.assertEqual(canonicalize_mode("Aus", supported), "Off")

    def test_mode_click_labels_include_language_aliases(self) -> None:
        labels = mode_click_labels(
            "Automatisch",
            ["Off", "Automatic", "Eco", "Hybrid", "Fastheating", "Vacation"],
        )

        self.assertIn("Automatisch", labels)
        self.assertIn("automatic", labels)

    def test_count_visible_modes_understands_english_values(self) -> None:
        text = "Off Automatic Eco Hybrid Fastheating Vacation"

        self.assertEqual(
            count_visible_modes(
                text,
                ["Off", "Automatic", "Eco", "Hybrid", "Fastheating", "Vacation"],
            ),
            6,
        )


if __name__ == "__main__":
    unittest.main()
