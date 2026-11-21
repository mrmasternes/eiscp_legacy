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
| Model | Your receiver model, or "Other / not listed". Only the inputs and listening modes that model supports are offered. |
| Name | Name of the device in Home Assistant |

You can change the IP address and port later via **Reconfigure** on the integration entry.

## Options

Open **Configure** on the integration entry. It has three pages:

1. **Model and volume**
   - *Model*: changing it resets the shown inputs and listening modes to the defaults of the new model (custom input names are kept for inputs the new model also has).
   - *Volume resolution*: number of volume steps of the receiver: 50, 80, 100 or 200. DTC-9.8-era units usually use 100.
   - *Maximum volume*: cap, in percent, so that volume can never exceed a chosen level.
2. **Inputs and listening modes**: tick the inputs and listening modes to show in Home Assistant. Only those the selected model supports are listed, and at least one input is required.
3. **Input names**: rename each shown input (for example `PHONO (22)` to `Record Player`). Leave a field empty to use the standard name.

If you upgrade from an earlier version, your existing options are migrated automatically (model "Other / not listed", your inputs and names kept).

### Hidden inputs and modes

If the receiver switches to an input or listening mode you have hidden (for example from its front panel or remote), Home Assistant still shows its proper name, and the select entities temporarily list it so the state is never "unknown".

## Entities

All entities belong to the same device:

- `media_player`: power on/off, volume set and up/down, mute, input source, listening mode (shown as Home Assistant "sound mode")
- `select` **Input**: choose the input
- `select` **Listening mode**: choose the listening mode
- `number` **Volume**: slider in receiver steps, from 0 up to the maximum volume cap
- `switch` **Power**: main zone power
- `number` **Volume limit** and `switch` **Enforce volume limit** (configuration): see below

## Volume limit

The maximum volume is the same setting as *Maximum volume* in the options. It can also be changed with the **Volume limit** slider (1 to 100 %), without reloading the integration. Home Assistant never sets the volume above it. When **Enforce volume limit** is on (also in the options), the integration additionally sends the limit to the receiver whenever the volume is raised above it by any other means (front panel, remote, another app), and once when you switch enforcement on or lower the limit.

## Extra controls

When the integration connects it asks the receiver about each optional feature below (one short query each). Entities are created only for features the receiver answers. Unsupported commands get no reply on older receivers, so unsupported features simply do not appear. Detected features are remembered, so entities do not disappear if the receiver is in standby and does not answer everything; reload the integration after switching the receiver on to pick up newly answering features.

| Entity | Command | Notes |
| --- | --- | --- |
| `number` Subwoofer level | `SWL` | -15 to +12 dB |
| `select` Late night | `LTN` | Off, Low, High |
| `switch` Re-EQ | `RAS` | Configuration |
| `select` Display dimmer | `DIM` | Bright, Dim, Dark, Shut off, Bright (LED off); configuration |
| `number` Sleep timer | `SLP` | 0 (off) to 90 minutes |
| `select` Audio selector | `SLA` | Auto, Multichannel, Analog, i.LINK, HDMI, Coaxial / optical, Balanced; configuration |
| `select` Monitor resolution | `RES` | Through, Auto, 480p, 720p, 1080i, 1080p, Source, 1080p/24; configuration |
| `select` HDMI output | `HDO` | Analog, Main, Sub, Both, Both (main), Both (sub); configuration |
| `sensor` Tuner frequency | `TUN` | For example `87.50 MHz` (FM) or `1400 kHz` (AM) |
| `select` Tuner preset | `PRS` | Presets 1 to 40 |
| `switch` Zone 2 power | `ZPW` | |
| `switch` 12 V trigger A / B / C | `TGA` / `TGB` / `TGC` | See below |

### 12 V triggers

The receiver cannot report the state of its triggers, so they are not detected. The three trigger switches are always created but **disabled by default**; enable them under the device's entities. They use an assumed state (the last value sent or received). The receiver accepts trigger commands only when the matching 12 V trigger setting in its setup menu is set to **OFF**.

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

- More extra controls: tone, center level, Audyssey
- Zone 2 / Zone 3
- Direct RS-232 serial connection
- Info sensors

## Contributing

Issues and pull requests are welcome, especially test reports for other receiver models. Please use the issue templates and include a diagnostics file and debug log. Run `ruff check .` and `pytest` before opening a pull request.

## License

[MIT](LICENSE)

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Onkyo, Integra or Pioneer. All product names and trademarks belong to their respective owners.
