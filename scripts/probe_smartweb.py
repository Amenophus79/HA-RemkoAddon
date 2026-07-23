#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "remko_smartweb_mqtt"
sys.path.insert(0, str(PACKAGE_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe REMKO SmartWeb once or in a polling loop without installing the Home Assistant add-on."
    )
    parser.add_argument("--config", default="test.json", help="Path to local test credentials JSON.")
    parser.add_argument("--loop", action="store_true", help="Poll repeatedly using remko.poll_interval_minutes.")
    parser.add_argument("--max-polls", type=int, default=1, help="Maximum polls before exiting.")
    parser.add_argument("--timeout-seconds", type=int, help="Override remko.request_timeout_seconds.")
    parser.add_argument("--device-url", help="Override remko.device_url for direct remote-control page tests.")
    parser.add_argument("--live-value-timeout-seconds", type=int, help="Override remko.live_value_timeout_seconds.")
    parser.add_argument("--live-value-check-interval-seconds", type=int, help="Override remko.live_value_check_interval_seconds.")
    parser.add_argument("--debug-dir", help="Write failure screenshot, HTML, and text to this directory.")
    args = parser.parse_args()

    try:
        from remko_smartweb_mqtt.config import ConfigError, load_options
        from remko_smartweb_mqtt.feedback import AVAILABLE, ERROR, UNAVAILABLE, build_feedback_payload
        from remko_smartweb_mqtt.smartweb import RemkoSmartWebClient, SmartWebError
    except ImportError as exc:
        return emit(
            {
                "feedback": build_dependency_feedback(str(exc)),
                "hint": "Install runtime dependencies first, for example: python3 -m pip install -r remko_smartweb_mqtt/requirements.txt",
            },
            exit_code=3,
        )

    try:
        options = load_options(args.config)
    except ConfigError as exc:
        return emit(
            {
                "feedback": build_feedback_payload(ERROR, str(exc), available=False),
                "hint": "Fill test.json with REMKO credentials. test.json is ignored by Git.",
            },
            exit_code=4,
        )
    if args.timeout_seconds:
        options["remko"]["request_timeout_seconds"] = args.timeout_seconds
    if args.device_url:
        options["remko"]["device_url"] = args.device_url
    if args.live_value_timeout_seconds is not None:
        options["remko"]["live_value_timeout_seconds"] = args.live_value_timeout_seconds
    if args.live_value_check_interval_seconds is not None:
        options["remko"]["live_value_check_interval_seconds"] = args.live_value_check_interval_seconds

    client = RemkoSmartWebClient(options)
    interval_seconds = int(options["remko"]["poll_interval_minutes"]) * 60
    poll_count = 0
    exit_code = 0

    try:
        while True:
            poll_count += 1
            try:
                state = client.poll()
                print_json(
                    {
                        "feedback": build_feedback_payload(
                            AVAILABLE,
                            "REMKO SmartWeb data read successfully",
                            available=True,
                        ),
                        "state": state.as_payload(),
                    }
                )
            except SmartWebError as exc:
                debug_payload = write_debug_artifacts(client, args.debug_dir)
                print_json(
                    {
                        "feedback": build_feedback_payload(
                            UNAVAILABLE,
                            str(exc),
                            available=False,
                        ),
                        **debug_payload,
                    }
                )
            except Exception as exc:
                debug_payload = write_debug_artifacts(client, args.debug_dir)
                print_json(
                    {
                        "feedback": build_feedback_payload(ERROR, str(exc), available=False),
                        "type": type(exc).__name__,
                        **debug_payload,
                    }
                )
                exit_code = 2

            if not args.loop or poll_count >= args.max_polls or exit_code:
                return exit_code
            time.sleep(interval_seconds)
    finally:
        client.close()


def build_dependency_feedback(message: str) -> dict[str, Any]:
    return {
        "available": False,
        "status": "dependency_missing",
        "message": message,
        "last_update": None,
    }


def write_debug_artifacts(client: Any, debug_dir: str | None) -> dict[str, Any]:
    if not debug_dir:
        return {}
    target = Path(debug_dir)
    target.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    try:
        driver = client._ensure_driver()
        screenshot_path = target / "smartweb_probe.png"
        html_path = target / "smartweb_probe.html"
        text_path = target / "smartweb_probe.txt"
        driver.save_screenshot(str(screenshot_path))
        html_path.write_text(driver.page_source or "", encoding="utf-8")
        text_path.write_text(client._body_text(), encoding="utf-8")
        artifacts = {
            "debug_screenshot": str(screenshot_path),
            "debug_html": str(html_path),
            "debug_text": str(text_path),
            "debug_url": driver.current_url,
        }
    except Exception as exc:
        artifacts = {"debug_error": f"{type(exc).__name__}: {exc}"}
    return artifacts


def emit(payload: dict[str, Any], exit_code: int) -> int:
    print_json(payload)
    return exit_code


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
