"""Diagnostics support for the eISCP Legacy Receiver integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import EiscpConfigEntry

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EiscpConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    receiver = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "receiver": {
            "connected": receiver.connected,
            "protocol": receiver.protocol,
            "port": receiver.port,
            "state": dict(receiver.state),
            "stats": dict(receiver.stats),
        },
    }
