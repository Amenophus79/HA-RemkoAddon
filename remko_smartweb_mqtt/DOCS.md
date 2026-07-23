# Documentation

## Installation

Copy this repository into a Home Assistant add-on repository location, reload the add-on store, install **REMKO SmartWeb MQTT**, fill in the options, and start the add-on.

## Credentials file

The add-on can read credentials from a separate JSON file. By default it looks for this file inside the Home Assistant add-on configuration folder:

```text
/config/credentials.json
```

In Home Assistant this path maps to the app-specific config folder on the host, for example `/app_configs/<repository>_remko_smartweb_mqtt/credentials.json` on current versions or `/addon_configs/<repository>_remko_smartweb_mqtt/credentials.json` on older installations. Use `credentials.example.json` as the template. Real `credentials.json` files are ignored by Git and must not be committed.

On app start, the app creates `/config/credentials.example.json` if it does not exist yet. It does not overwrite an existing template or create/overwrite the real `/config/credentials.json` file.

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

If you know the remote-control URL behind the house icon, set `remko.device_url`. The add-on will still log in first, then open this URL directly instead of relying on the overview row click. Prefer the fullscreen URL for headless polling:

```text
https://smartweb.remko.media/geraet/fernbedienung_vollbild/<device-id>
```

When the normal URL is configured, the add-on tries the fullscreen variant first and then falls back to the configured URL:

```text
https://smartweb.remko.media/geraet/fernbedienung/<device-id>
```

## Behavior

At startup the add-on connects to MQTT and publishes Home Assistant MQTT discovery. It then starts a mandatory headless Chromium session, logs in to `https://smartweb.remko.media/`, selects the configured device name from the overview, and reads:

- temperature at the top
- temperature at the bottom
- target temperature, if visible
- operating mode

Polling repeats every `remko.poll_interval_minutes` minutes. The default is `15`.

If the REMKO overview action icon is greyed out or the pump screen cannot be opened, the add-on publishes a feedback payload to `remko/<device_slug>/feedback` with `status: unavailable`, `available: false`, and a message explaining the timeout. Home Assistant also gets a SmartWeb availability binary sensor and SmartWeb status sensor through MQTT discovery.

If `remko.homeassistant_log` is enabled, unavailable/error states are additionally written to the Home Assistant system log with the configured `remko.homeassistant_log_logger` logger name. The add-on calls Home Assistant Core through the Supervisor proxy and `system_log.write`; repeated identical messages are suppressed until a successful poll resets the notifier.

If `remko.homeassistant_notification` is enabled, unavailable/error states are also shown as a persistent notification in the Home Assistant UI. The notification uses `remko.homeassistant_notification_id`, so a new failure updates the existing notification instead of creating a pile of duplicates. A successful poll dismisses it automatically.

`<device_slug>` means the MQTT-safe version of `remko.device_name`: it is lowercased and non-ASCII/special characters are replaced with underscores. For `WIFI Stick - Warmwasserwärmepumpe`, the slug becomes `wifi_stick_warmwasserw_rmepumpe`.

## Control

Home Assistant can control the heat pump through the discovered MQTT entities. Any MQTT client can also publish directly:

```text
remko/<device_slug>/power/set        ON or OFF
remko/<device_slug>/mode/set         Off, Automatic, Eco, Hybrid, Fastheating, Vacation
remko/<device_slug>/temperature/set  Numeric temperature
```

Without dedicated SmartWeb power buttons, `power/set OFF` sets operating mode `Off`; `power/set ON` sets `remko.power_on_mode`, which defaults to `Automatic`.

For combined commands:

```text
Topic: remko/<device_slug>/command/set
Payload: {"power":"ON","mode":"Automatic","temperature":45}
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

Because REMKO SmartWeb can differ between devices and software versions, selectors are configurable. The observed REMKO values are prefilled in the add-on options. Empty optional selectors use automatic detection. If a value is missing in Home Assistant, inspect the REMKO page in a desktop browser and set a selector for that element.

Selectors use CSS unless they start with `xpath:`. Example:

```yaml
selectors:
  username_input: "[id='benutzer']"
  password_input: "[id='password']"
  login_button: "[id='login_do']"
  temperature_top: "[id='RoomValue']"
  temperature_bottom: "[id='IndoorValue']"
  target_temperature: "[id='ID1333_000_000_value']"
  operating_mode: "[id='ID1192_000_000_value']"
  operating_mode_button: "[id='ID1192_000_button']"
  target_temperature_button: "[id='ID1333_000_button']"
  timer_button: "[id='ID1404_000_button']"
```

The first REMKO login page seen on July 1, 2026 has visible labels `Email*`, `Password*`, and a `Login` button. The observed DOM uses `input#benutzer`, `input#password`, and `button#login_do`; these are configured as defaults.

The device overview seen on July 1, 2026 shows the pump row as `WIFI Stick - Warmwasserwärmepumpe`. The first action icon in that row is the small house icon. Leave `selectors.device_link` empty first: the add-on will try to find that row from `remko.device_name` and click the first action icon automatically. If the icon is greyed out, SmartWeb appears to consider the device unavailable; the add-on will time out with a clear error and retry on the next poll.

Switching from the overview to the pump screen can take time. Increase `remko.request_timeout_seconds` if your SmartWeb account often needs more than the default `90` seconds.

The remote-control page embeds the actual REMKO app in `iframe#appFrame`. The scraper switches into that frame before reading values.

On the observed SmartWeb SVG view, `#RoomValue` contains the top temperature and `#IndoorValue` contains the bottom temperature. These DOM ids are used automatically before the label-based fallback parser.

The observed button configuration uses these ids:

- `ID1192`: operating mode
- `ID1333`: desired storage loading temperature
- `ID1404`: timer

The current operating mode is read automatically from `#ID1192_000_000_value`. For commands, the add-on opens `#ID1192_000_button` and then clicks the requested mode in the second view with six operating-mode buttons: `Off`, `Automatic`, `Eco`, `Hybrid`, `Fastheating`, and `Vacation`. The active mode there is highlighted in green.

In the observed mode editor these options have stable ids: `1192_2` = Off, `1192_3` = Automatic, `1192_9` = Eco, `1192_10` = Hybrid, `1192_11` = Fastheating, and `1192_12` = Vacation. The scraper targets `#modes .mode` first and reads `.mode.selected` when the editor is open.

Mode writes are verified. The add-on clicks the requested mode, waits `remko.mode_set_retry_seconds` seconds, opens the pump view again, and checks whether `#ID1192_000_000_value` confirms the requested mode. If SmartWeb did not accept it yet, the add-on repeats this up to `remko.mode_set_attempts` times. The defaults are three attempts with a 20 second pause.

The desired storage temperature is read automatically from `#ID1333_000_000_value`. For temperature commands, the add-on opens `#ID1333_000_button` before looking for the input control.

The operating mode, target temperature, and timer button selectors are configured with the observed stable ids by default. Change them only if REMKO changes the ids or the automatic detection is not enough.

For the remaining workflow, send screenshots of:

- the heat pump detail page with both temperatures, mode, and status visible
- the open mode selector
- the temperature edit control
- the power on/off control

## Notes

The add-on always uses headless Chromium through Selenium. It does not need a display server, desktop session, VNC, or Xvfb. Screenshots for selector discovery should be captured from your normal browser outside the add-on.

Keep the poll interval reasonably high so REMKO SmartWeb is not queried unnecessarily often.
