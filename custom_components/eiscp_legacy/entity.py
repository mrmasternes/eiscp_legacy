"""Shared base entity for the eISCP Legacy Receiver integration."""

from __future__ import annotations

import logging

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import EiscpConfigEntry
from .connection import NotConnectedError, Receiver
from .const import (
    CONF_MAX_VOLUME,
    CONF_MODEL,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_MAX_VOLUME,
    DEFAULT_VOLUME_RESOLUTION,
    DOMAIN,
)
from .models import get_profile
from .options import SoundModeMap, SourceMap
from .protocol import Message

_LOGGER = logging.getLogger(__name__)


class EiscpEntity(Entity):
    """Base class for all entities of a receiver."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    # Receiver commands that make the entity recompute its state.
    _state_commands: frozenset[str] = frozenset()

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        self._receiver: Receiver = entry.runtime_data
        options = entry.options
        self._resolution: int = int(options.get(CONF_VOLUME_RESOLUTION, DEFAULT_VOLUME_RESOLUTION))
        max_volume = int(options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))
        self._max_level: float = max_volume / 100
        self._max_steps: int = round(self._resolution * self._max_level)
        self.source_map = SourceMap(options)
        self.sound_mode_map = SoundModeMap(options)

        profile = get_profile(options.get(CONF_MODEL))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Onkyo / Integra",
            model=profile.name if profile is not None else None,
        )
        self._attr_available = self._receiver.connected
        self._unavailable_logged = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to receiver updates."""
        self._update_availability(self._receiver.connected)
        self._handle_update()
        self.async_on_remove(self._receiver.add_message_listener(self._handle_message))
        self.async_on_remove(self._receiver.add_connection_listener(self._handle_connection))

    def _handle_update(self) -> None:
        """Recompute entity attributes from the receiver state (override)."""

    @callback
    def _handle_message(self, message: Message) -> None:
        """Handle a message from the receiver."""
        if message.command in self._state_commands:
            self._handle_update()
            self.async_write_ha_state()

    @callback
    def _handle_connection(self, connected: bool) -> None:
        """Handle a connection state change."""
        self._update_availability(connected)
        self._handle_update()
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

    def _send(self, command: str) -> None:
        """Send a command, translating connection errors."""
        try:
            self._receiver.send(command)
        except NotConnectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            ) from err
