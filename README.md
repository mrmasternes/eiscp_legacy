# eISCP Legacy Receiver

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/mrmasternes/eiscp_legacy)](https://github.com/mrmasternes/eiscp_legacy/releases)
[![Validate](https://github.com/mrmasternes/eiscp_legacy/actions/workflows/validate.yml/badge.svg)](https://github.com/mrmasternes/eiscp_legacy/actions/workflows/validate.yml)

A Home Assistant custom integration for older Onkyo / Integra / Pioneer AV receivers and pre/pros.

## What is it and why?

Home Assistant's built-in Onkyo integration needs the receiver to answer its UDP discovery and "interview" requests. Many older units (this was developed on an **Integra DTC-9.8**) do not, so the built-in integration cannot set them up.

This integration talks to the receiver directly with local push over:

- **eISCP** over TCP (port 60128), or
- **raw ISCP** through a serial-to-TCP bridge (ser2net or similar) connected to the receiver's RS-232 port.

No extra Python requirements, no cloud, no polling storm: the receiver pushes state changes and the integration reconnects automatically with backoff (keepalive every 60 s).

## Supported hardware

| Receiver | Status |
| --- | --- |
| Integra DTC-9.8 | Tested |
| Other Onkyo / Integra / Pioneer models | Please report your results |

## Installation

### HACS (custom repository)

1. Open HACS in Home Assistant.
2. Click the three-dot menu (⋮) and choose **Custom repositories**.
3. Enter `https://github.com/mrmasternes/eiscp_legacy` as the URL and select category **Integration**.
4. Download **eISCP Legacy Receiver** and restart Home Assistant.

### Manual

Copy the `custom_components/eiscp_legacy` folder into the `custom_components` folder of your Home Assistant configuration directory and restart Home Assistant.

## Configuration

> **Important:** many older receivers accept only **one** control connection at a time. Disable other controllers (Node-RED eiscp nodes, other apps) before setting up.

Go to **Settings → Devices & services → Add integration** and search for "eISCP Legacy Receiver". Fill in:

| Field | Description |
| --- | --- |
| Host | The receiver's IP address only (not `ip:port`) |
| Port | `60128` for eISCP; the bridge's TCP port for serial |
| Protocol | eISCP, or raw ISCP (serial-to-TCP bridge) |
| Name | Name of the device in Home Assistant |

You can change the IP address and port later via **Reconfigure** on the integration entry.

## Options

| Option | Description |
| --- | --- |
| Volume resolution | Number of volume steps of the receiver: 50, 80, 100 or 200. DTC-9.8-era units usually use 100. |
| Max volume | Cap, in percent, so that the slider can never exceed a chosen level. |
| Input names | One entry per line as `code=name`, where `code` is the receiver's SLI hex code. |
| Listening modes | Which listening modes are shown in the sound mode list. |

Example input names:

```text
03=HDMI
02=Playstation 2
23=Record Player
```

## Entity

One `media_player` entity with:

- power on/off
- volume set and volume up/down
- mute
- input source
- listening mode (shown as Home Assistant "sound mode")

## Actions

### `eiscp_legacy.send_raw_command`

Sends a raw eISCP command. Target the media player; the `command` field is the command and parameter without framing.

```yaml
action: eiscp_legacy.send_raw_command
target:
  entity_id: media_player.integra
data:
  command: SWL+2
```

```yaml
action: eiscp_legacy.send_raw_command
target:
  entity_id: media_player.integra
data:
  command: LMD0D
```

### `eiscp_legacy.query`

Sends a query (3-letter command) and returns the response as `{command, value}`. Optional `timeout` in seconds.

```yaml
action: eiscp_legacy.query
target:
  entity_id: media_player.integra
data:
  command: MVL
  timeout: 3
response_variable: result
```

Then use `{{ result.value }}` (volume values are hex on the wire, see below).

## Event trigger

Every message from the receiver fires the event `eiscp_legacy_message` with data `entry_id`, `command`, `value` and `raw`. Use it as an automation trigger:

```yaml
automation:
  - alias: "Log receiver volume changes"
    triggers:
      - trigger: event
        event_type: eiscp_legacy_message
        event_data:
          command: MVL
    actions:
      - action: persistent_notification.create
        data:
          message: "Volume is now {{ trigger.event.data.value }} (hex)"
```

## Useful raw eISCP commands

Support depends on the receiver model. Volume values are hex on the wire: `MVL23` is 35.

| Command | Meaning |
| --- | --- |
| `PWR` | Power (`PWR01` on, `PWR00` standby) |
| `MVL` | Master volume (hex) |
| `AMT` | Audio muting (`AMT01` on, `AMT00` off) |
| `SLI` | Input selector (hex code) |
| `LMD` | Listening mode |
| `SWL` | Subwoofer level (for example `SWL+2`) |
| `CTL` | Center level |
| `TFR` | Tone front (bass/treble) |
| `DIM` | Display dimmer |
| `SLP` | Sleep timer |
| `LTN` | Late night |
| `ADY` | Audyssey Dynamic EQ |
| `ADQ` | Audyssey Dynamic Volume |
| `ADV` | Audyssey Dynamic Volume mode |
| `TGA` / `TGB` / `TGC` | 12 V trigger outputs A / B / C |

## Troubleshooting

- **One connection at a time.** Many older receivers allow a single control connection. Disable Node-RED eiscp nodes and any other controllers or apps.
- **Host field.** Enter the IP address only, not `ip:port`; the port has its own field.
- **`no_response` during setup.** Check the protocol (eISCP vs raw ISCP) and that no other controller is connected.
- **Debug logging.** Use the integration's **Enable debug logging** button in the UI, or in `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.eiscp_legacy: debug
  ```

  Attach the log and a diagnostics download (device page) when reporting issues.

## Roadmap

- Extra controls, auto-detected per receiver: tone, subwoofer/center level, dimmer, sleep, Audyssey, late night, triggers
- Tuner presets
- Zone 2 / Zone 3
- Direct RS-232 serial connection
- Info sensors

## Contributing

Issues and pull requests are welcome, especially test reports for other receiver models. Please use the issue templates and include a diagnostics file and debug log. Run `ruff check .` and `pytest` before opening a pull request.

## License

[MIT](LICENSE)

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Onkyo, Integra or Pioneer. All product names and trademarks belong to their respective owners.
