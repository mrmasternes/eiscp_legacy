"""Number platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EiscpConfigEntry
from .const import CONF_MAX_VOLUME
from .entity import EiscpEntity, EiscpFeatureEntity
from .features import PLATFORM_NUMBER, Feature, features_for_platform
from .options import max_volume_percent

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EiscpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number entities for a config entry."""
    entities: list[NumberEntity] = [EiscpVolumeNumber(entry), EiscpVolumeLimitNumber(entry)]
    entities.extend(
        EiscpFeatureNumber(entry, feature)
        for feature in features_for_platform(PLATFORM_NUMBER, entry.data.get("features", []))
    )
    async_add_entities(entities)


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
        self._attr_native_max_value = self._max_steps
        mvl = self._receiver.state.get("MVL")
        try:
            self._attr_native_value = int(mvl, 16) if mvl and mvl != "N/A" else None
        except ValueError:
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        self._send(f"MVL{min(int(value), self._max_steps):02X}")


class EiscpVolumeLimitNumber(EiscpEntity, NumberEntity):
    """The maximum volume (percent), stored in the entry options."""

    _attr_translation_key = "volume_limit"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_volume_limit"
        self._attr_native_value: float | None = None

    def _handle_update(self) -> None:
        self._attr_native_value = max_volume_percent(self._entry.options)

    async def async_set_native_value(self, value: float) -> None:
        """Store the new limit; listeners are notified by the update listener."""
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_MAX_VOLUME: int(value)}
        )


class EiscpFeatureNumber(EiscpFeatureEntity, NumberEntity):
    """A numeric receiver setting (subwoofer level, sleep timer)."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: EiscpConfigEntry, feature: Feature) -> None:
        """Initialize the entity."""
        super().__init__(entry, feature)
        self._attr_native_min_value = feature.min_value or 0
        self._attr_native_max_value = feature.max_value or 0
        self._attr_native_step = feature.step or 1
        self._attr_native_unit_of_measurement = feature.unit
        self._attr_native_value: float | None = None

    def _handle_update(self) -> None:
        assert self._feature.decode is not None
        self._attr_native_value = self._feature.decode(self._raw)

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        assert self._feature.encode is not None
        self._send(f"{self._command}{self._feature.encode(value)}")
