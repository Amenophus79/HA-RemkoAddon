# REMKO SmartWeb MQTT Add-on Repository

This repository contains one Home Assistant add-on:

- `remko_smartweb_mqtt`: polls REMKO SmartWeb and bridges values and commands to MQTT.

## Local installation

Copy this repository into the Home Assistant add-on repository folder or add it as a custom add-on repository. Then reload the add-on store and install **REMKO SmartWeb MQTT**.

The add-on configuration lives in:

```text
remko_smartweb_mqtt/config.yaml
```

See `remko_smartweb_mqtt/DOCS.md` for options, MQTT topics, and selector examples.

## Continuous integration

GitHub Actions runs the unit tests with coverage on pushes and pull requests. The total coverage value is written to the workflow job summary and `coverage.xml`/`coverage.json` are uploaded as artifacts.
