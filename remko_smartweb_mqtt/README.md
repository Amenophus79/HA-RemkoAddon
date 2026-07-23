# REMKO SmartWeb MQTT

Home Assistant add-on that logs in to REMKO SmartWeb, opens the configured heat pump from the device overview, polls values every 15 minutes by default, and exposes state and commands through MQTT.

The SmartWeb automation always runs in headless Chromium, so the add-on does not require a GUI, display server, VNC, or Xvfb.

This add-on is experimental because REMKO SmartWeb is a browser UI, not a documented public API. The default scraper uses label and text heuristics. If your REMKO page uses different markup, configure the CSS/XPath selectors in the add-on options.

## MQTT entities

The add-on publishes retained MQTT discovery configs for:

- SmartWeb availability binary sensor
- SmartWeb status sensor
- Top temperature sensor
- Bottom temperature sensor
- Status sensor
- Operating mode sensor
- Power switch
- Operating mode select
- Target temperature number

State is published as JSON to:

```text
remko/<device_slug>/state
```

SmartWeb/pump availability feedback is published as JSON to:

```text
remko/<device_slug>/feedback
```

When the REMKO overview action icon is greyed out or the pump screen cannot be opened, the feedback status becomes `unavailable` and the message explains the timeout.

If `remko.homeassistant_log` is enabled, the same non-availability is also written to the Home Assistant system log through `system_log.write`. If `remko.homeassistant_notification` is enabled, the add-on also creates a persistent notification in the Home Assistant UI and dismisses it automatically after a successful poll. Repeated identical messages are de-duplicated until the pump is readable again.

`<device_slug>` is the MQTT-safe form of `remko.device_name`: lowercase, spaces and special characters replaced with underscores. For `WIFI Stick - Warmwasserwärmepumpe`, the slug is `wifi_stick_warmwasserw_rmepumpe`, so the feedback topic is:

```text
remko/wifi_stick_warmwasserw_rmepumpe/feedback
```

Commands are accepted on:

```text
remko/<device_slug>/power/set
remko/<device_slug>/mode/set
remko/<device_slug>/temperature/set
remko/<device_slug>/command/set
```

By default, the MQTT power switch uses the operating mode screen: `OFF` selects mode `Off`, while `ON` selects `remko.power_on_mode` (`Automatic` by default).

The JSON command topic accepts payloads like:

```json
{"power":"ON","mode":"Automatic","temperature":45}
```

## Required options

- `remko.credentials_file`: Optional JSON file with REMKO/MQTT credentials, default `/config/credentials.json` in the Home Assistant add-on configuration folder.
- `remko.username`: REMKO SmartWeb login user, unless provided by the credentials file.
- `remko.password`: REMKO SmartWeb login password, unless provided by the credentials file.
- `remko.device_name`: Name shown on the device overview page, unless provided by the credentials file.
- `remko.device_url`: Optional direct remote-control URL behind the overview house icon. Prefer `fernbedienung_vollbild/<device-id>` for headless polling; when the normal `fernbedienung/<device-id>` URL is configured, the add-on tries the fullscreen variant first.
- `remko.poll_interval_minutes`: Poll interval, default `15`.
- `remko.request_timeout_seconds`: Page and connection timeout, default `90`.
- `remko.mode_set_attempts`: Verified retries for setting operating mode, default `3`.
- `remko.mode_set_retry_seconds`: Pause before each mode verification/retry, default `20`.
- `remko.power_on_mode`: Mode used by `power/set ON`, default `Automatic`.
- `remko.homeassistant_log`: Write non-availability/errors to the Home Assistant system log, default `true`.
- `remko.homeassistant_notification`: Show non-availability/errors as a Home Assistant persistent notification, default `true`.

## Selector options

Use CSS selectors by default. Prefix with `xpath:` for XPath.

Useful examples:

```yaml
selectors:
  username_input: "input#benutzer"
  password_input: "input#password"
  login_button: "button#login_do"
  temperature_top: "#RoomValue"
  temperature_bottom: "#IndoorValue"
  target_temperature: "#ID1333_000_000_value"
  operating_mode: "#ID1192_000_000_value"
  operating_mode_button: "#ID1192_000_button"
  target_temperature_button: "#ID1333_000_button"
  timer_button: "#ID1404_000_button"
```

## MQTT broker

Set `mqtt.host` to `auto` to use the Supervisor MQTT service when available. Otherwise set the broker host, port, username, and password manually.

## Tests without installing the add-on

Fast unit tests do not require Selenium, Paho, MQTT, Home Assistant, or the add-on container:

```sh
python3 -m unittest discover -s tests
```

For a real SmartWeb probe, copy `test.example.json` to `test.json`, fill in credentials, install `remko_smartweb_mqtt/requirements.txt`, then run:

```sh
python3 scripts/probe_smartweb.py --config test.json
```

`test.json` is ignored by Git.
