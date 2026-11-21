"""Switch platform for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EiscpConfigEntry
from .const import CONF_ENFORCE_MAX_VOLUME
from .entity import EiscpEntity, EiscpFeatureEntity
from .features import PLATFORM_SWITCH, Feature, decode_switch, features_for_platform
from .options import enforce_max_volume
from .protocol import Message

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EiscpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch entities for a config entry."""
    entities: list[SwitchEntity] = [EiscpPowerSwitch(entry), EiscpEnforceVolumeLimitSwitch(entry)]
    entities.extend(
        EiscpFeatureSwitch(entry, feature)
        for feature in features_for_platform(PLATFORM_SWITCH, entry.data.get("features", []))
    )
    async_add_entities(entities)


class EiscpPowerSwitch(EiscpEntity, SwitchEntity):
    """Main zone power."""

    _attr_translation_key = "power"
    _state_commands = frozenset({"PWR"})

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_is_on: bool | None = None

    def _handle_update(self) -> None:
        self._attr_is_on = decode_switch(self._receiver.state.get("PWR"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the receiver on."""
        self._send("PWR01")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the receiver off."""
        self._send("PWR00")


class EiscpEnforceVolumeLimitSwitch(EiscpEntity, SwitchEntity):
    """Whether the volume limit is also enforced against changes made on the receiver."""

    _attr_translation_key = "enforce_volume_limit"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: EiscpConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_enforce_volume_limit"
        self._attr_is_on: bool | None = None

    def _handle_update(self) -> None:
        self._attr_is_on = enforce_max_volume(self._entry.options)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable enforcement."""
        self._store(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable enforcement."""
        self._store(False)

    def _store(self, enforce: bool) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_ENFORCE_MAX_VOLUME: enforce}
        )


class EiscpFeatureSwitch(EiscpFeatureEntity, SwitchEntity):
    """A two-state receiver setting.

    Entities that cannot be queried (the 12 V triggers) use an assumed state:
    the last value sent or received.
    """

    def __init__(self, entry: EiscpConfigEntry, feature: Feature) -> None:
        """Initialize the entity."""
        super().__init__(entry, feature)
        self._attr_assumed_state = feature.assumed_state
        self._attr_is_on: bool | None = None

    def _handle_update(self) -> None:
        assert self._feature.decode is not None
        if self._attr_assumed_state:
            # Keep the optimistic state; only seed it from a received value.
            if self._attr_is_on is None:
                self._attr_is_on = self._feature.decode(self._raw)
            return
        self._attr_is_on = self._feature.decode(self._raw)

    @callback
    def _handle_message(self, message: Message) -> None:
        """Handle a message; assumed-state switches adopt any value reported."""
        if not self._attr_assumed_state:
            super()._handle_message(message)
            return
        if message.command != self._command:
            return
        assert self._feature.decode is not None
        state = self._feature.decode(message.value)
        if state is not None:
            self._attr_is_on = state
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        self._set(False)

    def _set(self, on: bool) -> None:
        assert self._feature.encode is not None
        self._send(f"{self._command}{self._feature.encode(on)}")
        if self._attr_assumed_state:
            self._attr_is_on = on
            self.async_write_ha_state()
