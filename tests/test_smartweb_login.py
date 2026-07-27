from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.smartweb import (
    RemkoSmartWebClient,
    SmartWebMaintenanceError,
    device_url_candidates,
    extract_maintenance_notice,
)


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

    def test_extract_maintenance_notice_from_login_page_text(self) -> None:
        notice = extract_maintenance_notice(
            """
            REMKO Smart-Webportal
            Login
            Email*
            Password*
            Important Informations
            Because of maintenance work, the Smartweb will be
            unavailable on the 27.07.2026, from 11:00 to 13:00
            (CEST).
            Register
            REMKO Smart-Webportal
            Important Informations
            Because of maintenance work, the Smartweb will be
            unavailable on the 27.07.2026, from 11:00 to 13:00
            (CEST).
            """
        )

        self.assertEqual(
            notice,
            "Important Informations Because of maintenance work, the Smartweb will be "
            "unavailable on the 27.07.2026, from 11:00 to 13:00 (CEST).",
        )

    def test_maintenance_notice_raises_specific_error(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._body_text = Mock(
            return_value=(
                "REMKO Smart-Webportal\n"
                "Important Informations\n"
                "Because of maintenance work, the Smartweb will be unavailable."
            )
        )

        with self.assertRaises(SmartWebMaintenanceError) as ctx:
            client._raise_for_maintenance_notice()

        self.assertIn("maintenance notice", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
