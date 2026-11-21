"""Select platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EiscpConfigEntry
from .const import DOMAIN
from .entity import EiscpEntity
from .options import CodeMap

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EiscpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entities for a config entry."""
    async_add_entities([EiscpInputSelect(entry), EiscpListeningModeSelect(entry)])


class _EiscpCodeSelect(EiscpEntity, SelectEntity):
    """Select backed by a receiver command with a hex code value."""

    _command: str
    _unknown_key: str
    _map: CodeMap

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._code: str | None = None
        self._current_name: str | None = None

    @property
    def options(self) -> list[str]:
        """Return the enabled names, plus the active one when it is hidden."""
        return self._map.options_with(self._code)

    @property
    def current_option(self) -> str | None:
        """Return the active name."""
        return self._current_name

    def _handle_update(self) -> None:
        value = self._receiver.state.get(self._command)
        if not value or value == "N/A":
            self._code = None
            self._current_name = None
        else:
            self._code = value.upper()
            self._current_name = self._map.name(self._code)

    async def async_select_option(self, option: str) -> None:
        """Send the selected option to the receiver."""
        code = self._map.code(option)
        if code is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=self._unknown_key
            )
        self._send(f"{self._command}{code}")


class EiscpInputSelect(_EiscpCodeSelect):
    """Input selector."""

    _attr_translation_key = "input"
    _command = "SLI"
    _unknown_key = "unknown_source"
    _state_commands = frozenset({"SLI"})

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_input"
        self._map = self.source_map


class EiscpListeningModeSelect(_EiscpCodeSelect):
    """Listening mode selector."""

    _attr_translation_key = "listening_mode"
    _command = "LMD"
    _unknown_key = "unknown_sound_mode"
    _state_commands = frozenset({"LMD"})

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_listening_mode"
        self._map = self.sound_mode_map
