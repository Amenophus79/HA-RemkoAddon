from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.smartweb import RemkoSmartWebClient, device_url_candidates


class SmartWebLoginTests(unittest.TestCase):
    def test_direct_device_url_skips_overview_wait_after_login(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._remko = {"device_url": "https://smartweb.remko.media/geraet/fernbedienung/device"}
        client._wait_for_overview_screen = Mock()

        client._wait_after_login()

        client._wait_for_overview_screen.assert_not_called()

    def test_without_direct_device_url_waits_for_overview_after_login(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._remko = {"device_url": ""}
        client._wait_for_overview_screen = Mock()

        client._wait_after_login()

        client._wait_for_overview_screen.assert_called_once_with()

    def test_normal_remote_url_prefers_fullscreen_candidate(self) -> None:
        candidates = device_url_candidates(
            "https://smartweb.remko.media/geraet/fernbedienung/device-id"
        )

        self.assertEqual(
            candidates,
            [
                "https://smartweb.remko.media/geraet/fernbedienung_vollbild/device-id",
                "https://smartweb.remko.media/geraet/fernbedienung/device-id",
            ],
        )

    def test_fullscreen_remote_url_keeps_fullscreen_candidate_first(self) -> None:
        candidates = device_url_candidates(
            "https://smartweb.remko.media/geraet/fernbedienung_vollbild/device-id"
        )

        self.assertEqual(
            candidates,
            [
                "https://smartweb.remko.media/geraet/fernbedienung_vollbild/device-id",
                "https://smartweb.remko.media/geraet/fernbedienung/device-id",
            ],
        )

    def test_delay_before_value_read_waits_configured_seconds(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._value_read_delay_seconds = 10

        with patch("remko_smartweb_mqtt.smartweb.time.sleep") as sleep:
            client._delay_before_value_read("poll")

        sleep.assert_called_once_with(10)

    def test_delay_before_value_read_skips_zero_delay(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._value_read_delay_seconds = 0

        with patch("remko_smartweb_mqtt.smartweb.time.sleep") as sleep:
            client._delay_before_value_read("poll")

        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
