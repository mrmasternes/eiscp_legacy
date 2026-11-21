# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Power switch, a Volume limit slider and an Enforce volume limit switch (also in the options). Changing only the volume limit no longer reloads the integration.
- Auto-detected extra controls: subwoofer level, late night, Re-EQ, display dimmer, sleep timer, audio selector, monitor resolution, HDMI output, tuner frequency and preset, Zone 2 power. Entities are created only for features the receiver answers; detected features are cached.
- 12 V trigger A/B/C switches (assumed state, disabled by default).
- Choose the receiver model during setup and in the options; only the inputs and listening modes of that model are offered.
- Options flow with three pages: model and volume, which inputs and listening modes to show, and input names.
- `select` entities for input and listening mode, and a `number` volume slider, on the same device as the media player.
- A hidden input or listening mode that the receiver switches to is still shown with its proper name.

### Changed

- Options are stored in a new format (config entry version 1.2) and existing options are migrated automatically.
- Input names are edited per input instead of as `code=name` text lines.

## [0.1.0]

### Added

- Initial release.
- Config flow (host, port, protocol, name) with reconfigure support.
- `media_player` entity: power, volume set/step, mute, input source, listening mode (sound mode).
- Options: volume resolution, max volume cap, custom input names, listening modes.
- Actions `eiscp_legacy.send_raw_command` and `eiscp_legacy.query`.
- Event `eiscp_legacy_message` fired for every message received from the receiver.
- Diagnostics download.
- Automatic reconnect with backoff and 60 s keepalive.
