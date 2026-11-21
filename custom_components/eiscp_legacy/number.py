"""Number platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EiscpConfigEntry
from .entity import EiscpEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EiscpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number entities for a config entry."""
    async_add_entities([EiscpVolumeNumber(entry)])


class EiscpVolumeNumber(EiscpEntity, NumberEntity):
    """Master volume in receiver steps."""

    _attr_translation_key = "volume"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_step = 1
    _state_commands = frozenset({"MVL"})

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_volume"
        self._attr_native_max_value = self._max_steps
        self._attr_native_value: float | None = None

    def _handle_update(self) -> None:
        mvl = self._receiver.state.get("MVL")
        try:
            self._attr_native_value = int(mvl, 16) if mvl and mvl != "N/A" else None
        except ValueError:
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        self._send(f"MVL{min(int(value), self._max_steps):02X}")
