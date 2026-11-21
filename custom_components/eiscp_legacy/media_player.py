"""Media player platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from . import EiscpConfigEntry
from .connection import NotConnectedError
from .const import DOMAIN
from .entity import EiscpEntity
from .protocol import is_valid_command, level_to_volume, normalize_command, volume_to_level

PARALLEL_UPDATES = 1

_STATE_COMMANDS = frozenset({"PWR", "MVL", "AMT", "SLI", "LMD"})

SERVICE_SEND_RAW_COMMAND = "send_raw_command"
SERVICE_QUERY = "query"

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EiscpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player for a config entry."""
    async_add_entities([EiscpMediaPlayer(entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_RAW_COMMAND,
        {vol.Required("command"): cv.string},
        "async_send_raw_command",
    )
    platform.async_register_entity_service(
        SERVICE_QUERY,
        {
            vol.Required("command"): vol.All(cv.string, vol.Upper, vol.Length(min=3, max=3)),
            vol.Optional("timeout", default=5.0): vol.All(
                vol.Coerce(float), vol.Range(min=0.5, max=30)
            ),
        },
        "async_query",
        supports_response=SupportsResponse.ONLY,
    )


class EiscpMediaPlayer(EiscpEntity, MediaPlayerEntity):
    """Media player entity representing a legacy receiver."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = SUPPORTED_FEATURES
    _state_commands = _STATE_COMMANDS

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = entry.entry_id
        self._attr_source_list = self.source_map.options
        self._attr_sound_mode_list = self.sound_mode_map.options

    def _handle_update(self) -> None:
        """Recompute entity attributes from the receiver state."""
        state = self._receiver.state

        power = state.get("PWR")
        if power == "01":
            self._attr_state = MediaPlayerState.ON
        elif power == "00":
            self._attr_state = MediaPlayerState.OFF
        else:
            self._attr_state = None

        mvl = state.get("MVL")
        self._attr_volume_level = (
            None if mvl is None or mvl == "N/A" else volume_to_level(mvl, self._resolution)
        )

        amt = state.get("AMT")
        if amt == "01":
            self._attr_is_volume_muted = True
        elif amt == "00":
            self._attr_is_volume_muted = False
        else:
            self._attr_is_volume_muted = None

        sli = state.get("SLI")
        self._attr_source = None if not sli or sli == "N/A" else self.source_map.name(sli.upper())

        lmd = state.get("LMD")
        self._attr_sound_mode = (
            None if not lmd or lmd == "N/A" else self.sound_mode_map.name(lmd.upper())
        )

    async def async_turn_on(self) -> None:
        """Turn the receiver on."""
        self._send("PWR01")

    async def async_turn_off(self) -> None:
        """Turn the receiver off."""
        self._send("PWR00")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level (0..1)."""
        self._send("MVL" + level_to_volume(volume, self._resolution, self._max_level))

    async def async_volume_up(self) -> None:
        """Increase the volume unless the configured maximum is reached."""
        if self._attr_volume_level is not None and self._attr_volume_level >= self._max_level:
            return
        self._send("MVLUP")

    async def async_volume_down(self) -> None:
        """Decrease the volume."""
        self._send("MVLDOWN")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the receiver."""
        self._send("AMT01" if mute else "AMT00")

    async def async_select_source(self, source: str) -> None:
        """Select an input source by its configured name."""
        if (code := self.source_map.code(source)) is not None:
            self._send(f"SLI{code}")
            return
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_source")

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select a listening mode by name."""
        if (code := self.sound_mode_map.code(sound_mode)) is not None:
            self._send(f"LMD{code}")
            return
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_sound_mode"
        )

    async def async_send_raw_command(self, command: str) -> None:
        """Send a raw ISCP command (service)."""
        command = normalize_command(command)
        if not is_valid_command(command):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_command",
                translation_placeholders={"command": command},
            )
        self._send(command)

    async def async_query(self, command: str, timeout: float) -> dict[str, Any]:  # noqa: ASYNC109
        """Query a 3-letter command and return its value (service)."""
        try:
            value = await self._receiver.query(command, timeout=timeout)
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="query_timeout"
            ) from err
        except NotConnectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            ) from err
        return {"command": command, "value": value}
