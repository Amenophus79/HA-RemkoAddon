from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.smartweb import (
    RemkoSmartWebClient,
    SmartWebError,
    SmartWebMaintenanceError,
    device_url_candidates,
    extract_maintenance_notice,
)
from remko_smartweb_mqtt.models import HeatPumpState


class SmartWebLoginTests(unittest.TestCase):
    def test_successful_poll_parks_browser_after_reading(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._open_device_page = Mock()
        client._delay_before_value_read = Mock()
        client._read_state = Mock(return_value=HeatPumpState(temperature_top=48.5))
        client._looks_like_placeholder_state = Mock(return_value=False)
        client._park_browser = Mock()

        state = client.poll()

        self.assertEqual(state.temperature_top, 48.5)
        client._park_browser.assert_called_once_with()

    def test_failed_poll_parks_browser_before_propagating_error(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._open_device_page = Mock(side_effect=SmartWebError("offline"))
        client._park_browser = Mock()

        with self.assertRaisesRegex(SmartWebError, "offline"):
            client.poll()

        client._park_browser.assert_called_once_with()

    def test_park_browser_uses_blank_page_without_closing_session(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._driver = Mock()
        client.close = Mock()

        client._park_browser()

        client._driver.switch_to.default_content.assert_called_once_with()
        client._driver.get.assert_called_once_with("about:blank")
        client.close.assert_not_called()

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

    def test_disabled_overview_action_blocks_direct_device_url(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._device_action_result = Mock(
            return_value={
                "found": True,
                "enabled": False,
                "clicked": False,
                "reason": "aria-disabled",
            }
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "skipping the direct device URL until the next poll",
        ):
            client._raise_if_device_action_disabled("Heat pump")

        client._device_action_result.assert_called_once_with(
            "Heat pump",
            click_when_enabled=False,
        )

    def test_enabled_overview_action_allows_direct_device_url(self) -> None:
        client = RemkoSmartWebClient.__new__(RemkoSmartWebClient)
        client._device_action_result = Mock(
            return_value={
                "found": True,
                "enabled": True,
                "clicked": False,
                "reason": "enabled",
            }
        )

        client._raise_if_device_action_disabled("Heat pump")

        client._device_action_result.assert_called_once_with(
            "Heat pump",
            click_when_enabled=False,
        )

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
