# Local Docker Test Setup

This directory starts the REMKO SmartWeb MQTT add-on together with a local Mosquitto broker. It is intended for local testing with MQTT Explorer without installing the add-on in Home Assistant.

## Prepare Configuration

From the repository root:

```sh
cp local-docker/data/options.example.json local-docker/data/options.json
cp local-docker/data/credentials.example.json local-docker/data/credentials.json
```

Edit `local-docker/data/credentials.json` and fill in your REMKO username and password.

Adjust `local-docker/data/options.json` if needed:

- `remko.device_url`: Direct REMKO remote-control URL for the pump.
- `remko.poll_interval_minutes`: Poll interval. The first poll runs immediately.
- `mqtt.host`: Keep `mqtt` when using this compose setup.
- `mqtt.retain_state`: `true` is useful for MQTT Explorer because the latest state remains visible.

Real `options.json` and `credentials.json` files are ignored by Git.

## Start

```sh
cd local-docker
docker compose up --build
```

The first image build downloads the Home Assistant base image, Chromium, Chromedriver, and Python dependencies. After startup, the add-on logs in headless to REMKO SmartWeb and publishes MQTT messages to the local broker.

For Apple Silicon or another architecture label, you can set:

```sh
BUILD_ARCH=aarch64 docker compose up --build
```

## MQTT Explorer

Connect MQTT Explorer to:

```text
Host: localhost
Port: 1883
Username: empty
Password: empty
```

Useful topics:

```text
remko/wifi_stick_warmwasserw_rmepumpe/state
remko/wifi_stick_warmwasserw_rmepumpe/feedback
remko/wifi_stick_warmwasserw_rmepumpe/availability
homeassistant/+/+/config
```

Control topics:

```text
remko/wifi_stick_warmwasserw_rmepumpe/power/set
remko/wifi_stick_warmwasserw_rmepumpe/mode/set
remko/wifi_stick_warmwasserw_rmepumpe/temperature/set
remko/wifi_stick_warmwasserw_rmepumpe/command/set
```

Examples:

```text
Topic: remko/wifi_stick_warmwasserw_rmepumpe/mode/set
Payload: Eco
```

```text
Topic: remko/wifi_stick_warmwasserw_rmepumpe/command/set
Payload: {"mode":"Automatic","temperature":50}
```

Be careful with control topics: they send real commands to the heat pump.

## Logs

```sh
docker compose logs -f remko-addon
docker compose logs -f mqtt
```

## Stop And Clean Up

```sh
docker compose down
```

To remove the built local image as well:

```sh
docker image rm remko-smartweb-mqtt:local
```
