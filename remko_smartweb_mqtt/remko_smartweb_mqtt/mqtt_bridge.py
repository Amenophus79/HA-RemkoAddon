from __future__ import annotations

import json
import logging
import os
import queue
import re
import socket
from typing import Any

import paho.mqtt.client as mqtt
import requests

from . import APP_VERSION
from .feedback import STARTING, build_feedback_payload
from .models import Command, HeatPumpState

LOGGER = logging.getLogger(__name__)
DEGREE_C = "\u00b0C"


class MqttBridge:
    def __init__(self, options: dict[str, Any], commands: queue.Queue[Command]) -> None:
        self.options = options
        self.commands = commands
        self.device_name = str(options["remko"]["device_name"]).strip()
        self.device_slug = slugify(self.device_name)
        mqtt_options = self._resolve_mqtt_options(options["mqtt"])
        self.host = mqtt_options["host"]
        self.port = int(mqtt_options["port"])
        self.username = mqtt_options.get("username") or ""
        self.password = mqtt_options.get("password") or ""
        self.topic_prefix = strip_topic(options["mqtt"]["topic_prefix"], "remko")
        self.discovery_prefix = strip_topic(
            options["mqtt"]["discovery_prefix"],
            "homeassistant",
        )
        self.retain_state = bool(options["mqtt"]["retain_state"])
        self.base_topic = f"{self.topic_prefix}/{self.device_slug}"
        self.state_topic = f"{self.base_topic}/state"
        self.availability_topic = f"{self.base_topic}/availability"
        self.error_topic = f"{self.base_topic}/error"
        self.feedback_topic = f"{self.base_topic}/feedback"

        client_id = f"remko-smartweb-{self.device_slug}-{socket.gethostname()}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id[:64],
            clean_session=True,
        )
        if self.username:
            self.client.username_pw_set(self.username, self.password)
        self.client.will_set(self.availability_topic, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def connect(self) -> None:
        LOGGER.info("Connecting to MQTT broker %s:%s", self.host, self.port)
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def close(self) -> None:
        try:
            self.publish_availability("offline")
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            LOGGER.exception("Error while closing MQTT client")

    def publish_availability(self, state: str) -> None:
        self.client.publish(self.availability_topic, state, retain=True)

    def publish_state(self, state: HeatPumpState) -> None:
        payload = json.dumps(state.as_payload(), ensure_ascii=False, separators=(",", ":"))
        self.client.publish(self.state_topic, payload, retain=self.retain_state)

    def publish_feedback(
        self,
        status: str,
        message: str = "",
        *,
        available: bool | None = None,
    ) -> None:
        payload = json.dumps(
            build_feedback_payload(status, message, available=available),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.client.publish(self.feedback_topic, payload, retain=True)

    def publish_error(self, error: BaseException) -> None:
        payload = {
            "error": str(error),
            "type": type(error).__name__,
        }
        self.client.publish(
            self.error_topic,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=False,
        )

    def publish_discovery(self) -> None:
        for component, object_id, payload in self._discovery_payloads():
            topic = f"{self.discovery_prefix}/{component}/{object_id}/config"
            self.client.publish(
                topic,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                retain=True,
            )
        LOGGER.info("Published MQTT discovery for %s", self.device_name)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        LOGGER.info("MQTT connected: %s", reason_code)
        self.publish_availability("online")
        self.publish_discovery()
        self.publish_feedback(STARTING, "Waiting for the first REMKO SmartWeb poll", available=False)
        for topic in self.command_topics():
            client.subscribe(topic)
            LOGGER.info("Subscribed to %s", topic)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        LOGGER.warning("MQTT disconnected: %s", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        topic = message.topic
        payload = message.payload.decode("utf-8", errors="replace").strip()
        try:
            command = self._parse_command(topic, payload)
        except ValueError as exc:
            LOGGER.warning("Ignoring invalid command on %s: %s", topic, exc)
            self.publish_error(exc)
            return
        LOGGER.info("Received command: %s=%r", command.kind, command.value)
        self.commands.put(command)

    def command_topics(self) -> list[str]:
        return [
            f"{self.base_topic}/power/set",
            f"{self.base_topic}/mode/set",
            f"{self.base_topic}/temperature/set",
            f"{self.base_topic}/command/set",
        ]

    def _parse_command(self, topic: str, payload: str) -> Command:
        if topic.endswith("/power/set"):
            normalized = payload.upper()
            if normalized in {"ON", "1", "TRUE", "EIN", "AN"}:
                return Command("power", True)
            if normalized in {"OFF", "0", "FALSE", "AUS"}:
                return Command("power", False)
            raise ValueError("power command must be ON or OFF")

        if topic.endswith("/mode/set"):
            if not payload:
                raise ValueError("mode command must not be empty")
            return Command("mode", payload)

        if topic.endswith("/temperature/set"):
            try:
                return Command("temperature", float(payload.replace(",", ".")))
            except ValueError as exc:
                raise ValueError("temperature command must be numeric") from exc

        if topic.endswith("/command/set"):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError("command payload must be JSON") from exc
            if not isinstance(data, dict):
                raise ValueError("command payload must be a JSON object")
            return Command("batch", data)

        raise ValueError(f"unknown command topic: {topic}")

    def _discovery_payloads(self) -> list[tuple[str, str, dict[str, Any]]]:
        device = {
            "identifiers": [f"remko_smartweb_{self.device_slug}"],
            "name": self.device_name,
            "manufacturer": "REMKO",
            "model": "SmartWeb heat pump",
            "sw_version": APP_VERSION,
        }
        common = {
            "state_topic": self.state_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        feedback_common = {
            "state_topic": self.feedback_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        object_prefix = f"remko_{self.device_slug}"
        controls = self.options["controls"]

        return [
            (
                "binary_sensor",
                f"{object_prefix}_smartweb_available",
                {
                    **feedback_common,
                    "name": "SmartWeb Verfügbarkeit",
                    "unique_id": f"{object_prefix}_smartweb_available",
                    "device_class": "connectivity",
                    "payload_on": "true",
                    "payload_off": "false",
                    "value_template": "{{ 'true' if value_json.available else 'false' }}",
                },
            ),
            (
                "sensor",
                f"{object_prefix}_smartweb_feedback",
                {
                    **feedback_common,
                    "name": "SmartWeb Status",
                    "unique_id": f"{object_prefix}_smartweb_feedback",
                    "icon": "mdi:web-check",
                    "value_template": "{{ value_json.status }}",
                    "json_attributes_topic": self.feedback_topic,
                },
            ),
            (
                "sensor",
                f"{object_prefix}_temperature_top",
                {
                    **common,
                    "name": "Temperatur oben",
                    "unique_id": f"{object_prefix}_temperature_top",
                    "device_class": "temperature",
                    "state_class": "measurement",
                    "unit_of_measurement": DEGREE_C,
                    "value_template": "{{ value_json.temperature_top }}",
                },
            ),
            (
                "sensor",
                f"{object_prefix}_temperature_bottom",
                {
                    **common,
                    "name": "Temperatur unten",
                    "unique_id": f"{object_prefix}_temperature_bottom",
                    "device_class": "temperature",
                    "state_class": "measurement",
                    "unit_of_measurement": DEGREE_C,
                    "value_template": "{{ value_json.temperature_bottom }}",
                },
            ),
            (
                "sensor",
                f"{object_prefix}_status",
                {
                    **common,
                    "name": "Zustand",
                    "unique_id": f"{object_prefix}_status",
                    "icon": "mdi:heat-pump",
                    "value_template": "{{ value_json.status }}",
                },
            ),
            (
                "sensor",
                f"{object_prefix}_mode_state",
                {
                    **common,
                    "name": "Betriebsmodus Status",
                    "unique_id": f"{object_prefix}_mode_state",
                    "icon": "mdi:cog-outline",
                    "value_template": "{{ value_json.mode }}",
                },
            ),
            (
                "switch",
                f"{object_prefix}_power",
                {
                    **common,
                    "name": "Betrieb",
                    "unique_id": f"{object_prefix}_power",
                    "command_topic": f"{self.base_topic}/power/set",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "state_on": "ON",
                    "state_off": "OFF",
                    "value_template": "{{ value_json.power }}",
                    "icon": "mdi:power",
                },
            ),
            (
                "select",
                f"{object_prefix}_mode",
                {
                    **common,
                    "name": "Betriebsmodus",
                    "unique_id": f"{object_prefix}_mode",
                    "command_topic": f"{self.base_topic}/mode/set",
                    "options": controls["supported_modes"],
                    "value_template": "{{ value_json.mode }}",
                    "icon": "mdi:form-select",
                },
            ),
            (
                "number",
                f"{object_prefix}_target_temperature",
                {
                    **common,
                    "name": "Solltemperatur",
                    "unique_id": f"{object_prefix}_target_temperature",
                    "command_topic": f"{self.base_topic}/temperature/set",
                    "device_class": "temperature",
                    "unit_of_measurement": DEGREE_C,
                    "value_template": "{{ value_json.target_temperature }}",
                    "min": float(controls["min_temperature"]),
                    "max": float(controls["max_temperature"]),
                    "step": float(controls["temperature_step"]),
                    "mode": "box",
                },
            ),
        ]

    def _resolve_mqtt_options(self, configured: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(configured)
        if str(resolved.get("host", "")).lower() not in {"", "auto"}:
            return resolved

        service_data = read_supervisor_mqtt_service()
        if service_data:
            resolved.update({key: value for key, value in service_data.items() if value})
            return resolved

        resolved["host"] = os.environ.get("MQTT_HOST") or "core-mosquitto"
        resolved["port"] = int(os.environ.get("MQTT_PORT") or resolved.get("port") or 1883)
        resolved["username"] = os.environ.get("MQTT_USERNAME") or resolved.get("username") or ""
        resolved["password"] = os.environ.get("MQTT_PASSWORD") or resolved.get("password") or ""
        return resolved


def read_supervisor_mqtt_service() -> dict[str, Any] | None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        response = requests.get(
            "http://supervisor/services/mqtt",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        LOGGER.debug("Could not read MQTT service from Supervisor", exc_info=True)
        return None

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    service = {
        "host": data.get("host") or data.get("hostname"),
        "port": data.get("port"),
        "username": data.get("username"),
        "password": data.get("password"),
    }
    return {key: value for key, value in service.items() if value not in (None, "")}


def strip_topic(value: str, default: str) -> str:
    stripped = str(value or "").strip().strip("/")
    return stripped or default


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    slug = re.sub(r"[^a-z0-9_-]+", "_", lowered)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "heatpump"
