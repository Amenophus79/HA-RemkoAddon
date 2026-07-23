from __future__ import annotations

import logging
import queue
import signal
import time
from typing import Any

from .config import ConfigError, ensure_credentials_template, load_options
from .feedback import AVAILABLE, ERROR, UNAVAILABLE
from .homeassistant_log import HomeAssistantLogNotifier
from .models import Command
from .modes import canonicalize_mode
from .mqtt_bridge import MqttBridge
from .smartweb import RemkoSmartWebClient, SmartWebError

LOGGER = logging.getLogger(__name__)
MQTT_CONNECT_RETRY_SECONDS = 30
COMMAND_SETTLE_SECONDS = 30


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    stop = StopFlag()
    signal.signal(signal.SIGTERM, stop.handle)
    signal.signal(signal.SIGINT, stop.handle)

    try:
        template_path = ensure_credentials_template()
        LOGGER.info("Credentials template is available at %s", template_path)
    except ConfigError:
        LOGGER.warning("Could not create credentials template", exc_info=True)

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

    try:
        if not connect_mqtt_with_retry(mqtt_bridge, stop):
            return
        next_poll = 0.0

        while not stop.requested:
            command_processed = process_pending_commands(
                command_queue,
                smartweb,
                mqtt_bridge,
                options,
            )

            now = time.monotonic()
            if command_processed:
                next_poll = now + command_settle_seconds(options)
                continue

            if now >= next_poll:
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


def connect_mqtt_with_retry(
    mqtt_bridge: MqttBridge,
    stop: "StopFlag",
    retry_seconds: int = MQTT_CONNECT_RETRY_SECONDS,
) -> bool:
    while not stop.requested:
        try:
            mqtt_bridge.connect()
            return True
        except Exception:
            LOGGER.exception(
                "MQTT connection failed; retrying in %s seconds",
                retry_seconds,
            )
            sleep_until_stopped(stop, retry_seconds)
    return False


def sleep_until_stopped(stop: "StopFlag", seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while not stop.requested:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1, remaining))


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
            optimistic_patch = apply_command(command, smartweb, options)
            if optimistic_patch:
                mqtt_bridge.publish_optimistic_state(**optimistic_patch)
            processed = True
        except Exception as exc:
            LOGGER.exception("Failed to apply command %s", command)
            mqtt_bridge.publish_error(exc)
            mqtt_bridge.publish_feedback(ERROR, str(exc), available=False)


def apply_command(
    command: Command,
    smartweb: RemkoSmartWebClient,
    options: dict[str, Any],
) -> dict[str, Any]:
    if command.kind == "power":
        enabled = bool(command.value)
        smartweb.set_power(enabled)
        target_mode = str(options["remko"]["power_on_mode"]) if enabled else "Off"
        return {"operating_mode": target_mode, "power": mode_to_power(target_mode)}

    if command.kind == "mode":
        mode = validate_mode(str(command.value), options)
        smartweb.set_mode(mode)
        return {"operating_mode": mode, "power": mode_to_power(mode)}

    if command.kind == "temperature":
        temperature = validate_temperature(float(command.value), options)
        smartweb.set_temperature(temperature)
        return {"target_temperature": temperature}

    if command.kind == "batch":
        return apply_batch(command.value, smartweb, options)

    raise ValueError(f"Unsupported command kind: {command.kind}")


def apply_batch(
    data: dict[str, Any],
    smartweb: RemkoSmartWebClient,
    options: dict[str, Any],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if "power" in data:
        power = data["power"]
        if isinstance(power, str):
            power_enabled = power.upper() in {"ON", "1", "TRUE", "EIN", "AN"}
        else:
            power_enabled = bool(power)
        smartweb.set_power(power_enabled)
        target_mode = str(options["remko"]["power_on_mode"]) if power_enabled else "Off"
        patch.update({"operating_mode": target_mode, "power": mode_to_power(target_mode)})

    if "mode" in data:
        mode = validate_mode(str(data["mode"]), options)
        smartweb.set_mode(mode)
        patch.update({"operating_mode": mode, "power": mode_to_power(mode)})

    temperature = data.get("temperature", data.get("target_temperature"))
    if temperature is not None:
        target_temperature = validate_temperature(float(temperature), options)
        smartweb.set_temperature(target_temperature)
        patch["target_temperature"] = target_temperature

    return patch


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


def mode_to_power(mode: str | None) -> str | None:
    if mode is None:
        return None
    return "OFF" if mode.strip().lower() == "off" else "ON"


def command_settle_seconds(options: dict[str, Any]) -> int:
    retry_seconds = int(options["remko"].get("mode_set_retry_seconds") or 0)
    return max(COMMAND_SETTLE_SECONDS, retry_seconds)


class StopFlag:
    requested = False

    def handle(self, signum: int, frame: Any) -> None:
        LOGGER.info("Received signal %s, stopping", signum)
        self.requested = True
