# Changelog

## 0.2.5

- Fixes Home Assistant option validation by using non-optional schema types for options that have visible default values.
- Keeps empty visible fields such as `device_url`, `username`, and `password` saveable.

## 0.2.4

- Adds missing changelog entries for the Home Assistant update dialog.
- Keeps the REMKO SmartWeb defaults introduced in 0.2.3.
- Updates the local Dockerfile fallback build version to match the add-on version.

## 0.2.3

- Prefills the known REMKO SmartWeb overview URL, device name, login selectors, value selectors, and button selectors.
- Marks optional selector and login fields as optional in the Home Assistant options schema.
- Reduces the amount of manual option entry needed during installation.

## 0.2.2

- Fixes numeric option defaults so Home Assistant accepts `float` schema values for min/max target temperature.

## 0.2.1

- Maps the Home Assistant add-on configuration folder to `/config`.
- Changes the default credentials file path to `/config/credentials.json`.

## 0.2.0

- Adds direct REMKO remote-control URL support with fullscreen URL preference.
- Adds REMKO AJAX login handling and clearer login rejection diagnostics.
- Adds local Docker test setup and MQTT Explorer instructions.
- Adds Home Assistant issue visibility through logbook/notification feedback.
- Adds GitHub Actions test coverage workflow.
- Adds tests for parsing, feedback, MQTT topic slugs, and SmartWeb navigation defaults.

## 0.1.0

- Initial experimental REMKO SmartWeb MQTT bridge.
- Adds configurable 15-minute polling interval.
- Adds MQTT discovery for sensors, switch, select, and number entities.
- Adds MQTT command topics for power, mode, target temperature, and combined JSON commands.
