"""Media player platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from . import EiscpConfigEntry
from .connection import NotConnectedError, Receiver
from .const import (
    CONF_MAX_VOLUME,
    CONF_SOUND_MODES,
    CONF_SOURCES,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_MAX_VOLUME,
    DEFAULT_SOUND_MODES,
    DEFAULT_SOURCES,
    DEFAULT_VOLUME_RESOLUTION,
    DOMAIN,
    LISTENING_MODES,
)
from .protocol import (
    Message,
    is_valid_command,
    level_to_volume,
    normalize_command,
    volume_to_level,
)

_LOGGER = logging.getLogger(__name__)

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


class EiscpMediaPlayer(MediaPlayerEntity):
    """Media player entity representing a legacy receiver."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        self._receiver: Receiver = entry.runtime_data
        options = entry.options
        self._resolution: int = int(options.get(CONF_VOLUME_RESOLUTION, DEFAULT_VOLUME_RESOLUTION))
        self._max_level: float = int(options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)) / 100
        self._sources: dict[str, str] = dict(options.get(CONF_SOURCES) or DEFAULT_SOURCES)
        self._sound_modes: dict[str, str] = {
            code: LISTENING_MODES[code]
            for code in options.get(CONF_SOUND_MODES, DEFAULT_SOUND_MODES)
            if code in LISTENING_MODES
        }

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Onkyo / Integra",
        )
        self._attr_source_list = list(self._sources.values())
        self._attr_sound_mode_list = list(self._sound_modes.values())
        self._attr_available = self._receiver.connected
        self._unavailable_logged = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to receiver updates."""
        self._update_from_state()
        self.async_on_remove(self._receiver.add_message_listener(self._handle_message))
        self.async_on_remove(self._receiver.add_connection_listener(self._handle_connection))

    @callback
    def _handle_message(self, message: Message) -> None:
        """Handle a message from the receiver."""
        if message.command in _STATE_COMMANDS:
            self._update_from_state()
            self.async_write_ha_state()

    @callback
    def _handle_connection(self, connected: bool) -> None:
        """Handle a connection state change."""
        self._update_availability(connected)
        self.async_write_ha_state()

    def _update_availability(self, connected: bool) -> None:
        """Update availability and log transitions once."""
        self._attr_available = connected
        if not connected and not self._unavailable_logged:
            _LOGGER.info("Receiver %s is unavailable", self._receiver.host)
            self._unavailable_logged = True
        elif connected and self._unavailable_logged:
            _LOGGER.info("Receiver %s is back online", self._receiver.host)
            self._unavailable_logged = False

    def _update_from_state(self) -> None:
        """Recompute entity attributes from the receiver state."""
        self._update_availability(self._receiver.connected)
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
        if not sli or sli == "N/A":
            self._attr_source = None
        else:
            code = sli.upper()
            self._attr_source = (
                self._sources.get(code) or DEFAULT_SOURCES.get(code) or f"Unknown ({code})"
            )

        lmd = state.get("LMD")
        if not lmd or lmd == "N/A":
            self._attr_sound_mode = None
        else:
            code = lmd.upper()
            self._attr_sound_mode = LISTENING_MODES.get(code, f"Unknown ({code})")

    def _send(self, command: str) -> None:
        """Send a command, translating connection errors."""
        try:
            self._receiver.send(command)
        except NotConnectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            ) from err

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
        for code, name in self._sources.items():
            if name == source:
                self._send(f"SLI{code}")
                return
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_source")

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select a listening mode by name."""
        for code, name in LISTENING_MODES.items():
            if name == sound_mode:
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
