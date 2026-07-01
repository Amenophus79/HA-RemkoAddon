from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"))

from remko_smartweb_mqtt.feedback import AVAILABLE, UNAVAILABLE, build_feedback_payload


class FeedbackTests(unittest.TestCase):
    def test_available_feedback(self) -> None:
        payload = build_feedback_payload(AVAILABLE, "ok")

        self.assertTrue(payload["available"])
        self.assertEqual(payload["status"], AVAILABLE)
        self.assertEqual(payload["message"], "ok")
        self.assertIn("+00:00", payload["last_update"])

    def test_unavailable_feedback_for_greyed_out_pump(self) -> None:
        payload = build_feedback_payload(
            UNAVAILABLE,
            "Timed out opening device. The overview action icon may be disabled.",
            available=False,
        )

        self.assertFalse(payload["available"])
        self.assertEqual(payload["status"], UNAVAILABLE)
        self.assertIn("disabled", payload["message"])


if __name__ == "__main__":
    unittest.main()
