from __future__ import annotations

import logging
import queue
import signal
import time
from typing import Any

from .config import ConfigError, load_options
from .feedback import AVAILABLE, ERROR, UNAVAILABLE
from .homeassistant_log import HomeAssistantLogNotifier
from .models import Command
from .modes import canonicalize_mode
from .mqtt_bridge import MqttBridge
from .smartweb import RemkoSmartWebClient, SmartWebError

LOGGER = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    stop = StopFlag()
    signal.signal(signal.SIGTERM, stop.handle)
    signal.signal(signal.SIGINT, stop.handle)

    try:
        options = load_options()
    except ConfigError:
        LOGGER.exception("Invalid add-on configuration")
        raise SystemExit(1)

    command_queue: queue.Queue[Command] = queue.Queue()
    mqtt_bridge = MqttBridge(options, command_queue)
    smartweb = RemkoSmartWebClient(options)
    ha_log = HomeAssistantLogNotifier(options)
    poll_interval = int(options["remko"]["poll_interval_minutes"]) * 60

    mqtt_bridge.connect()
    next_poll = 0.0

    try:
        while not stop.requested:
            command_processed = process_pending_commands(
                command_queue,
                smartweb,
                mqtt_bridge,
                options,
            )

            now = time.monotonic()
            if command_processed or now >= next_poll:
                try:
                    state = smartweb.poll()
                    mqtt_bridge.publish_state(state)
                    mqtt_bridge.publish_feedback(
                        AVAILABLE,
                        "REMKO SmartWeb data read successfully",
                        available=True,
                    )
                    mqtt_bridge.publish_availability("online")
                    ha_log.reset()
                except Exception as exc:
                    LOGGER.exception("Polling REMKO SmartWeb failed")
                    mqtt_bridge.publish_error(exc)
                    status = UNAVAILABLE if isinstance(exc, SmartWebError) else ERROR
                    mqtt_bridge.publish_feedback(status, str(exc), available=False)
                    level = "warning" if status == UNAVAILABLE else "error"
                    ha_log.notify_once(status, str(exc), level=level)
                next_poll = time.monotonic() + poll_interval

            time.sleep(1)
    finally:
        smartweb.close()
        mqtt_bridge.close()


def process_pending_commands(
    command_queue: queue.Queue[Command],
    smartweb: RemkoSmartWebClient,
    mqtt_bridge: MqttBridge,
    options: dict[str, Any],
) -> bool:
    processed = False
    while True:
        try:
            command = command_queue.get_nowait()
        except queue.Empty:
            return processed

        try:
            apply_command(command, smartweb, options)
            processed = True
        except Exception as exc:
            LOGGER.exception("Failed to apply command %s", command)
            mqtt_bridge.publish_error(exc)
            mqtt_bridge.publish_feedback(ERROR, str(exc), available=False)


def apply_command(
    command: Command,
    smartweb: RemkoSmartWebClient,
    options: dict[str, Any],
) -> None:
    if command.kind == "power":
        smartweb.set_power(bool(command.value))
        return

    if command.kind == "mode":
        smartweb.set_mode(validate_mode(str(command.value), options))
        return

    if command.kind == "temperature":
        smartweb.set_temperature(validate_temperature(float(command.value), options))
        return

    if command.kind == "batch":
        apply_batch(command.value, smartweb, options)
        return

    raise ValueError(f"Unsupported command kind: {command.kind}")


def apply_batch(
    data: dict[str, Any],
    smartweb: RemkoSmartWebClient,
    options: dict[str, Any],
) -> None:
    if "power" in data:
        power = data["power"]
        if isinstance(power, str):
            power_enabled = power.upper() in {"ON", "1", "TRUE", "EIN", "AN"}
        else:
            power_enabled = bool(power)
        smartweb.set_power(power_enabled)

    if "mode" in data:
        smartweb.set_mode(validate_mode(str(data["mode"]), options))

    temperature = data.get("temperature", data.get("target_temperature"))
    if temperature is not None:
        smartweb.set_temperature(validate_temperature(float(temperature), options))


def validate_temperature(value: float, options: dict[str, Any]) -> float:
    controls = options["controls"]
    minimum = float(controls["min_temperature"])
    maximum = float(controls["max_temperature"])
    if value < minimum or value > maximum:
        raise ValueError(f"Temperature {value} is outside configured range {minimum}-{maximum}")
    return value


def validate_mode(value: str, options: dict[str, Any]) -> str:
    supported = [str(mode) for mode in options["controls"]["supported_modes"]]
    mode = canonicalize_mode(value, supported)
    if mode:
        return mode
    raise ValueError(f"Mode '{value}' is not one of: {', '.join(supported)}")


class StopFlag:
    requested = False

    def handle(self, signum: int, frame: Any) -> None:
        LOGGER.info("Received signal %s, stopping", signum)
        self.requested = True
