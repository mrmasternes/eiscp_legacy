"""Config flow for the eISCP Legacy Receiver integration."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, PERCENTAGE
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
import voluptuous as vol

from .connection import CannotConnect, NoResponse, async_probe
from .const import (
    CONF_MAX_VOLUME,
    CONF_MODEL,
    CONF_PROTOCOL,
    CONF_SOUND_MODES,
    CONF_SOURCE_NAMES,
    CONF_SOURCES,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_MAX_VOLUME,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_VOLUME_RESOLUTION,
    DOMAIN,
    LISTENING_MODES,
    VOLUME_RESOLUTIONS,
)
from .models import MODEL_OTHER, model_choices
from .options import (
    available_sound_modes,
    available_sources,
    change_model,
    default_options,
    source_label,
    standard_source_name,
)
from .protocol import PROTOCOL_EISCP, PROTOCOL_ISCP

_LOGGER = logging.getLogger(__name__)

_HOST_WITH_PORT = re.compile(r"^[^:\[\]]+:\d+$")

_PROTOCOL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[PROTOCOL_EISCP, PROTOCOL_ISCP],
        translation_key=CONF_PROTOCOL,
        mode=SelectSelectorMode.DROPDOWN,
    )
)

_MODEL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[
            *(SelectOptionDict(value=key, label=name) for key, name in model_choices()),
            SelectOptionDict(value=MODEL_OTHER, label="Other / not listed"),
        ],
        mode=SelectSelectorMode.DROPDOWN,
    )
)


def _connection_schema(*, with_name: bool) -> vol.Schema:
    """Return the schema for the user and reconfigure steps."""
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_PROTOCOL, default=PROTOCOL_EISCP): _PROTOCOL_SELECTOR,
    }
    if with_name:
        schema[vol.Required(CONF_MODEL, default=MODEL_OTHER)] = _MODEL_SELECTOR
        schema[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = str
    return vol.Schema(schema)


async def _async_validate(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the connection settings, returning an errors dict."""
    errors: dict[str, str] = {}
    if _HOST_WITH_PORT.match(user_input[CONF_HOST]):
        errors[CONF_HOST] = "host_includes_port"
        return errors
    try:
        await async_probe(
            user_input[CONF_HOST],
            user_input[CONF_PORT],
            user_input.get(CONF_PROTOCOL, PROTOCOL_EISCP),
        )
    except CannotConnect:
        errors["base"] = "cannot_connect"
    except NoResponse:
        errors["base"] = "no_response"
    except Exception:
        _LOGGER.exception("Unexpected exception while connecting to receiver")
        errors["base"] = "unknown"
    return errors


class EiscpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for an eISCP Legacy Receiver."""

    VERSION = 1
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EiscpOptionsFlow:
        """Return the options flow."""
        return EiscpOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            # Check for duplicates before probing: the receiver usually accepts only
            # one connection, so probing an already configured one would fail.
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            errors = await _async_validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_PROTOCOL: user_input[CONF_PROTOCOL],
                    },
                    options=default_options(user_input[CONF_MODEL]),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(with_name=True), user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the connection settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            same_target = (
                host == entry.data[CONF_HOST]
                and port == entry.data[CONF_PORT]
                and user_input[CONF_PROTOCOL] == entry.data.get(CONF_PROTOCOL, PROTOCOL_EISCP)
            )
            if (
                same_target
                and entry.state is ConfigEntryState.LOADED
                and entry.runtime_data.connected
            ):
                # Already connected to this receiver; a second connection would be
                # refused by receivers that only allow one client.
                errors = {}
            else:
                errors = await _async_validate(user_input)
            if not errors:
                new_uid = f"{host}:{port}"
                for other in self._async_current_entries(include_ignore=False):
                    if other.entry_id != entry.entry_id and other.unique_id == new_uid:
                        return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_uid,
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_PROTOCOL: user_input[CONF_PROTOCOL],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(with_name=False),
                user_input
                if user_input is not None
                else {
                    CONF_HOST: entry.data[CONF_HOST],
                    CONF_PORT: entry.data[CONF_PORT],
                    CONF_PROTOCOL: entry.data.get(CONF_PROTOCOL, PROTOCOL_EISCP),
                },
            ),
            errors=errors,
        )


class EiscpOptionsFlow(OptionsFlow):
    """Handle the options of an eISCP Legacy Receiver."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the model and the volume settings."""
        current = dict(self.config_entry.options)
        if user_input is not None:
            new = {
                **current,
                CONF_VOLUME_RESOLUTION: int(user_input[CONF_VOLUME_RESOLUTION]),
                CONF_MAX_VOLUME: int(user_input[CONF_MAX_VOLUME]),
            }
            if user_input[CONF_MODEL] != current.get(CONF_MODEL, MODEL_OTHER):
                new = change_model(new, user_input[CONF_MODEL])
            self._options = new
            return await self.async_step_select()

        schema = vol.Schema(
            {
                vol.Required(CONF_MODEL): _MODEL_SELECTOR,
                vol.Required(CONF_VOLUME_RESOLUTION): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=str(res),
                                label=f"{res} steps (0x00-0x{res:02X})",
                            )
                            for res in VOLUME_RESOLUTIONS
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_MAX_VOLUME): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=100,
                        step=1,
                        unit_of_measurement=PERCENTAGE,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )
        suggested = {
            CONF_MODEL: current.get(CONF_MODEL, MODEL_OTHER),
            CONF_VOLUME_RESOLUTION: str(
                current.get(CONF_VOLUME_RESOLUTION, DEFAULT_VOLUME_RESOLUTION)
            ),
            CONF_MAX_VOLUME: current.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose which inputs and listening modes are shown."""
        errors: dict[str, str] = {}
        model = self._options.get(CONF_MODEL, MODEL_OTHER)
        source_codes = available_sources(model)
        mode_codes = available_sound_modes(model)

        if user_input is not None:
            chosen_sources = set(user_input[CONF_SOURCES])
            chosen_modes = set(user_input.get(CONF_SOUND_MODES, []))
            if not chosen_sources:
                errors[CONF_SOURCES] = "no_sources"
            else:
                self._options = {
                    **self._options,
                    # Keep the receiver's own order, not the order of clicking.
                    CONF_SOURCES: [c for c in source_codes if c in chosen_sources],
                    CONF_SOUND_MODES: [c for c in mode_codes if c in chosen_modes],
                }
                return await self.async_step_names()

        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCES): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=code, label=source_label(code))
                            for code in source_codes
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_SOUND_MODES): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=code, label=LISTENING_MODES.get(code, f"Unknown ({code})")
                            )
                            for code in mode_codes
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        if user_input is not None:
            suggested = user_input
        else:
            suggested = {
                CONF_SOURCES: [c for c in self._options.get(CONF_SOURCES, []) if c in source_codes],
                CONF_SOUND_MODES: [
                    c for c in self._options.get(CONF_SOUND_MODES, []) if c in mode_codes
                ],
            }
        return self.async_show_form(
            step_id="select",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rename the shown inputs."""
        codes: list[str] = self._options[CONF_SOURCES]
        # Field keys are shown verbatim by Home Assistant, so use readable labels.
        keys = {code: source_label(code) for code in codes}

        if user_input is not None:
            names: dict[str, str] = {}
            for code, key in keys.items():
                name = str(user_input.get(key) or "").strip()
                if name and name != standard_source_name(code):
                    names[code] = name
            return self.async_create_entry(data={**self._options, CONF_SOURCE_NAMES: names})

        custom = self._options.get(CONF_SOURCE_NAMES) or {}
        schema = vol.Schema({vol.Optional(key): TextSelector() for key in keys.values()})
        suggested = {
            key: custom.get(code) or standard_source_name(code) for code, key in keys.items()
        }
        return self.async_show_form(
            step_id="names",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )
