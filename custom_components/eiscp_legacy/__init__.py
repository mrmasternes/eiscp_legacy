"""The eISCP Legacy Receiver integration."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .connection import DEFAULT_REFRESH_COMMANDS, NotConnectedError, Receiver
from .const import CONF_FEATURES, CONF_PROTOCOL, DOMAIN, EVENT_MESSAGE, limits_signal
from .features import async_detect_features, feature_for_message, refresh_commands_for
from .options import enforcement_target, migrate_options, options_need_reload
from .protocol import PROTOCOL_EISCP, Message

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type EiscpConfigEntry = ConfigEntry[Receiver]

# Seconds after setup before missing features are asked for again.
FEATURE_RECHECK_DELAY = 30


async def async_setup_entry(hass: HomeAssistant, entry: EiscpConfigEntry) -> bool:
    """Set up a receiver from a config entry."""

    def _create_task(coro: Coroutine[Any, Any, Any], name: str) -> Any:
        return entry.async_create_background_task(hass, coro, name)

    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]
    receiver = Receiver(
        host,
        port,
        entry.data.get(CONF_PROTOCOL, PROTOCOL_EISCP),
        create_task=_create_task,
    )

    await receiver.start()
    if not await receiver.wait_connected(10):
        await receiver.stop()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": host, "port": str(port)},
        )

    entry.runtime_data = receiver

    @callback
    def _fire_event(message: Message) -> None:
        hass.bus.async_fire(
            EVENT_MESSAGE,
            {
                "entry_id": entry.entry_id,
                "command": message.command,
                "value": message.value,
                "raw": message.raw,
            },
        )

    entry.async_on_unload(receiver.add_message_listener(_fire_event))

    async def _async_stop(_event: Event) -> None:
        await receiver.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop))

    # Ask the receiver which optional features it supports. The result is merged
    # with what was cached, since a receiver in standby may not answer everything.
    # This happens before the update listener is registered so it cannot reload.
    cached: set[str] = set(entry.data.get(CONF_FEATURES, []))
    # Short timeout here to keep startup quick; a background re-check catches stragglers.
    detected = await async_detect_features(receiver, timeout=1.5, skip=cached)
    features = cached | detected
    if features != cached:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_FEATURES: sorted(features)}
        )
    receiver.refresh_commands = DEFAULT_REFRESH_COMMANDS + refresh_commands_for(features)
    receiver.refresh()

    def _enforce_volume(value: str | None) -> None:
        """Send the volume limit when enforcement is on and the volume is above it."""
        target = enforcement_target(entry.options, value)
        if target is None:
            return
        _LOGGER.debug("Volume %s is above the limit, setting %s", value, target)
        try:
            receiver.send(f"MVL{target}")
        except NotConnectedError:
            pass

    @callback
    def _add_features(new: set[str]) -> None:
        """Cache newly found features; the data change reloads the entry."""
        if not new - features:
            return
        _LOGGER.debug("New receiver features found: %s", sorted(new - features))
        features.update(new)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_FEATURES: sorted(features)}
        )

    @callback
    def _on_message(message: Message) -> None:
        if message.command == "MVL":
            _enforce_volume(message.value)
        # A feature that missed detection proves itself when the receiver reports it.
        key = feature_for_message(message.command, message.value)
        if key is not None and key not in features:
            _add_features({key})

    entry.async_on_unload(receiver.add_message_listener(_on_message))

    async def _async_recheck_features() -> None:
        """Ask again, after startup, for features the receiver did not answer."""
        await asyncio.sleep(FEATURE_RECHECK_DELAY)
        found = await async_detect_features(receiver, skip=features)
        if found:
            _add_features(found)

    entry.async_create_background_task(
        hass, _async_recheck_features(), f"{DOMAIN} feature recheck {entry.entry_id}"
    )

    # The options and data this setup was made with, to tell which changes need a reload.
    applied_options = dict(entry.options)
    applied_data = dict(entry.data)

    async def _async_update_listener(hass: HomeAssistant, entry: EiscpConfigEntry) -> None:
        nonlocal applied_options
        if dict(entry.data) != applied_data or options_need_reload(applied_options, entry.options):
            await hass.config_entries.async_reload(entry.entry_id)
            return
        # Only the volume limit changed: update entities and enforce, no reload.
        applied_options = dict(entry.options)
        async_dispatcher_send(hass, limits_signal(entry.entry_id))
        _enforce_volume(receiver.state.get("MVL"))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: EiscpConfigEntry) -> bool:
    """Migrate options to the current format."""
    if entry.version == 1 and entry.minor_version < 2:
        hass.config_entries.async_update_entry(
            entry, options=migrate_options(dict(entry.options)), minor_version=2
        )
        _LOGGER.debug("Migrated entry %s to version 1.2", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EiscpConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.stop()
    return unload_ok
