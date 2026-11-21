# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
