"""Sensor platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EiscpConfigEntry
from .entity import EiscpFeatureEntity
from .features import PLATFORM_SENSOR, features_for_platform

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EiscpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor entities for a config entry."""
    async_add_entities(
        EiscpFeatureSensor(entry, feature)
        for feature in features_for_platform(PLATFORM_SENSOR, entry.data.get("features", []))
    )


class EiscpFeatureSensor(EiscpFeatureEntity, SensorEntity):
    """A text sensor for a receiver value (tuner frequency)."""

    _attr_native_value: str | None = None

    def _handle_update(self) -> None:
        assert self._feature.decode is not None
        self._attr_native_value = self._feature.decode(self._raw)
