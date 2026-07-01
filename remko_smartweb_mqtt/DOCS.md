# Documentation

## Installation

Copy this repository into a Home Assistant add-on repository location, reload the add-on store, install **REMKO SmartWeb MQTT**, fill in the options, and start the add-on.

## Credentials file

The add-on can read credentials from a separate JSON file. By default it looks for:

```text
/data/credentials.json
```

Use `credentials.example.json` as the template. Real `credentials.json` files are ignored by Git and must not be committed.

```json
{
  "remko": {
    "username": "your-remko-login@example.com",
    "password": "your-remko-password",
    "device_name": "Name shown on the REMKO SmartWeb overview"
  },
  "mqtt": {
    "host": "auto",
    "port": 1883,
    "username": "",
    "password": ""
  }
}
```

Values in the credentials file override the same values from the Home Assistant add-on options.

## Behavior

At startup the add-on connects to MQTT and publishes Home Assistant MQTT discovery. It then starts a mandatory headless Chromium session, logs in to `https://smartweb.remko.media/`, selects the configured device name from the overview, and reads:

- temperature at the top
- temperature at the bottom
- target temperature, if visible
- operating mode
- operating status

Polling repeats every `remko.poll_interval_minutes` minutes. The default is `15`.

If the REMKO overview action icon is greyed out or the pump screen cannot be opened, the add-on publishes a feedback payload to `remko/<device_slug>/feedback` with `status: unavailable`, `available: false`, and a message explaining the timeout. Home Assistant also gets a SmartWeb availability binary sensor and SmartWeb status sensor through MQTT discovery.

If `remko.homeassistant_log` is enabled, unavailable/error states are additionally written to the Home Assistant system log with the configured `remko.homeassistant_log_logger` logger name. The add-on calls Home Assistant Core through the Supervisor proxy and `system_log.write`; repeated identical messages are suppressed until a successful poll resets the notifier.

If `remko.homeassistant_notification` is enabled, unavailable/error states are also shown as a persistent notification in the Home Assistant UI. The notification uses `remko.homeassistant_notification_id`, so a new failure updates the existing notification instead of creating a pile of duplicates. A successful poll dismisses it automatically.

`<device_slug>` means the MQTT-safe version of `remko.device_name`: it is lowercased and non-ASCII/special characters are replaced with underscores. For `WIFI Stick - Warmwasserwärmepumpe`, the slug becomes `wifi_stick_warmwasserw_rmepumpe`.

## Control

Home Assistant can control the heat pump through the discovered MQTT entities. Any MQTT client can also publish directly:

```text
remko/<device_slug>/power/set        ON or OFF
remko/<device_slug>/mode/set         Auto, Heizen, Kühlen, Standby, Aus
remko/<device_slug>/temperature/set  Numeric temperature
```

For combined commands:

```text
Topic: remko/<device_slug>/command/set
Payload: {"power":"ON","mode":"Heizen","temperature":45}
```

## Tests without installing the add-on

Run fast local tests without Home Assistant, MQTT, Paho, Selenium, or the add-on container:

```sh
python3 -m unittest discover -s tests
```

For a real SmartWeb query, copy `test.example.json` to `test.json`, fill in credentials, and install runtime dependencies locally:

```sh
python3 -m pip install -r remko_smartweb_mqtt/requirements.txt
python3 scripts/probe_smartweb.py --config test.json
```

The probe runs headless and returns JSON. A currently unavailable pump is reported as:

```json
{
  "feedback": {
    "available": false,
    "status": "unavailable",
    "message": "..."
  }
}
```

Use `--loop --max-polls N` to repeat the probe with the configured `remko.poll_interval_minutes` interval. `test.json` is ignored by Git and must not be committed.

## Selectors

Because REMKO SmartWeb can differ between devices and software versions, selectors are configurable. Empty selectors use automatic detection. If a value is missing in Home Assistant, inspect the REMKO page in a desktop browser and set a selector for that element.

Selectors use CSS unless they start with `xpath:`. Example:

```yaml
selectors:
  username_input: "input[type='email']"
  password_input: "input[type='password']"
  login_button: "xpath://button[contains(normalize-space(.), 'Login')]"
  device_link: "xpath://*[contains(normalize-space(.), 'WIFI Stick - Warmwasserwärmepumpe')]/following::*[self::a or self::button or @role='button'][1]"
  temperature_top: "xpath://*[contains(., 'Speicher oben')]/following::*[1]"
```

The first REMKO login page seen on July 1, 2026 has visible labels `Email*`, `Password*`, and a `Login` button. The add-on's automatic login detection should match this page through `input[type='email']`, `input[type='password']`, and the submit/login button fallback. Configure the selectors above only if the automatic login fails.

The device overview seen on July 1, 2026 shows the pump row as `WIFI Stick - Warmwasserwärmepumpe`. The first action icon in that row is the small house icon. Leave `selectors.device_link` empty first: the add-on will try to find that row from `remko.device_name` and click the first action icon automatically. If the icon is greyed out, SmartWeb appears to consider the device unavailable; the add-on will time out with a clear error and retry on the next poll.

Switching from the overview to the pump screen can take time. Increase `remko.request_timeout_seconds` if your SmartWeb account often needs more than the default `90` seconds.

For the remaining workflow, send screenshots of:

- the heat pump detail page with both temperatures, mode, and status visible
- the open mode selector
- the temperature edit control
- the power on/off control

## Notes

The add-on always uses headless Chromium through Selenium. It does not need a display server, desktop session, VNC, or Xvfb. Screenshots for selector discovery should be captured from your normal browser outside the add-on.

Keep the poll interval reasonably high so REMKO SmartWeb is not queried unnecessarily often.
