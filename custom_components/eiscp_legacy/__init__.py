"""The eISCP Legacy Receiver integration."""

from __future__ import annotations

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

from .connection import Receiver
from .const import CONF_PROTOCOL, DOMAIN, EVENT_MESSAGE
from .protocol import PROTOCOL_EISCP, Message

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER]

type EiscpConfigEntry = ConfigEntry[Receiver]


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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: EiscpConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EiscpConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.stop()
    return unload_ok
