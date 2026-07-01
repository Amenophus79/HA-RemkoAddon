#!/usr/bin/with-contenv bashio
set -euo pipefail

bashio::log.info "Starting REMKO SmartWeb MQTT bridge"
exec /opt/venv/bin/python -m remko_smartweb_mqtt
