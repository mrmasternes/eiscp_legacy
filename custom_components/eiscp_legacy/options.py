"""Home Assistant independent handling of the integration options."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from .const import (
    CONF_ENFORCE_MAX_VOLUME,
    CONF_MAX_VOLUME,
    CONF_MODEL,
    CONF_SOUND_MODES,
    CONF_SOURCE_NAMES,
    CONF_SOURCES,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_MAX_VOLUME,
    DEFAULT_SOUND_MODES,
    DEFAULT_SOURCES,
    DEFAULT_VOLUME_RESOLUTION,
    LISTENING_MODES,
)
from .models import MODEL_OTHER, get_profile

_UNKNOWN_RE = re.compile(r"^Unknown \(([0-9A-Fa-f]{2})\)$")


def available_sources(model_key: str | None) -> list[str]:
    """Return the input codes a model supports (all known codes for "other")."""
    profile = get_profile(model_key)
    if profile is None:
        return list(DEFAULT_SOURCES)
    return list(profile.sources)


def available_sound_modes(model_key: str | None) -> list[str]:
    """Return the listening mode codes a model supports (all known for "other")."""
    profile = get_profile(model_key)
    if profile is None:
        return list(LISTENING_MODES)
    return list(profile.listening_modes)


def standard_source_name(code: str) -> str:
    """Return the standard name of an input code."""
    return DEFAULT_SOURCES.get(code) or f"Unknown ({code})"


def source_label(code: str) -> str:
    """Return a label identifying an input code, for example ``PHONO (22)``."""
    name = DEFAULT_SOURCES.get(code)
    return f"{name} ({code})" if name else f"Unknown ({code})"


def default_options(model_key: str | None) -> dict[str, Any]:
    """Return the default options for a model."""
    profile = get_profile(model_key)
    return {
        CONF_MODEL: model_key if profile is not None else MODEL_OTHER,
        CONF_VOLUME_RESOLUTION: DEFAULT_VOLUME_RESOLUTION,
        CONF_MAX_VOLUME: DEFAULT_MAX_VOLUME,
        CONF_SOURCES: available_sources(model_key),
        CONF_SOURCE_NAMES: {},
        CONF_SOUND_MODES: (
            list(profile.listening_modes) if profile is not None else list(DEFAULT_SOUND_MODES)
        ),
    }


def migrate_options(old: Mapping[str, Any]) -> dict[str, Any]:
    """Convert options of version 1.1 (sources as a dict) to the current format."""
    new = default_options(MODEL_OTHER)
    new.update({k: v for k, v in old.items() if k not in (CONF_SOURCES, CONF_SOURCE_NAMES)})
    new[CONF_MODEL] = MODEL_OTHER
    old_sources = old.get(CONF_SOURCES)
    if isinstance(old_sources, Mapping) and old_sources:
        new[CONF_SOURCES] = [str(code).upper() for code in old_sources]
        new[CONF_SOURCE_NAMES] = {
            str(code).upper(): name
            for code, name in old_sources.items()
            if name and name != DEFAULT_SOURCES.get(str(code).upper())
        }
    elif isinstance(old_sources, list) and old_sources:
        new[CONF_SOURCES] = list(old_sources)
        new[CONF_SOURCE_NAMES] = dict(old.get(CONF_SOURCE_NAMES) or {})
    new[CONF_SOUND_MODES] = list(old.get(CONF_SOUND_MODES) or new[CONF_SOUND_MODES])
    return new


def change_model(options: Mapping[str, Any], new_model: str) -> dict[str, Any]:
    """Return options for a new model.

    Inputs and listening modes are reset to the defaults of the new model; custom
    names are kept for inputs the new model still has.
    """
    new = dict(options)
    defaults = default_options(new_model)
    new[CONF_MODEL] = defaults[CONF_MODEL]
    new[CONF_SOURCES] = defaults[CONF_SOURCES]
    new[CONF_SOUND_MODES] = defaults[CONF_SOUND_MODES]
    available = set(new[CONF_SOURCES])
    new[CONF_SOURCE_NAMES] = {
        code: name
        for code, name in (options.get(CONF_SOURCE_NAMES) or {}).items()
        if code in available
    }
    return new


# Option keys that can change without reloading the entry.
LIVE_OPTION_KEYS = frozenset({CONF_MAX_VOLUME, CONF_ENFORCE_MAX_VOLUME})


def max_volume_percent(options: Mapping[str, Any]) -> int:
    """Return the configured volume limit in percent."""
    try:
        return int(options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))
    except (TypeError, ValueError):
        return DEFAULT_MAX_VOLUME


def enforce_max_volume(options: Mapping[str, Any]) -> bool:
    """Return True when the volume limit is enforced on the receiver."""
    return bool(options.get(CONF_ENFORCE_MAX_VOLUME, False))


def volume_resolution(options: Mapping[str, Any]) -> int:
    """Return the configured number of volume steps."""
    try:
        return int(options.get(CONF_VOLUME_RESOLUTION, DEFAULT_VOLUME_RESOLUTION))
    except (TypeError, ValueError):
        return DEFAULT_VOLUME_RESOLUTION


def limit_steps(resolution: int, max_volume: int) -> int:
    """Return the volume limit in receiver steps."""
    return round(resolution * max_volume / 100)


def enforcement_target(options: Mapping[str, Any], mvl_value: str | None) -> str | None:
    """Return the 2-digit hex volume to send back, or None when nothing is needed.

    Only when enforcement is on and the (hex) volume is above the limit.
    """
    if not enforce_max_volume(options) or not mvl_value:
        return None
    try:
        level = int(mvl_value, 16)
    except ValueError:
        return None
    limit = limit_steps(volume_resolution(options), max_volume_percent(options))
    if level <= limit:
        return None
    return f"{limit:02X}"


def options_need_reload(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    """Return True unless only the live-updatable volume limit options differ."""
    keys = (set(old) | set(new)) - LIVE_OPTION_KEYS
    return any(old.get(key) != new.get(key) for key in keys)


class CodeMap:
    """Map between receiver codes and display names."""

    def __init__(
        self,
        enabled: Iterable[str],
        custom: Mapping[str, str],
        standard: Mapping[str, str],
    ) -> None:
        """Initialize the map."""
        self._standard = standard
        self._display: dict[str, str] = {}
        used: set[str] = set()
        for code in enabled:
            if code in self._display:
                continue
            name = custom.get(code) or standard.get(code) or f"Unknown ({code})"
            if name in used:
                name = f"{name} ({code})"
            used.add(name)
            self._display[code] = name
        self._reverse: dict[str, str] = {}
        for code, name in self._display.items():
            self._reverse.setdefault(name, code)
        for code, name in standard.items():
            self._reverse.setdefault(name, code)

    @property
    def options(self) -> list[str]:
        """Display names of the enabled codes, in order."""
        return list(self._display.values())

    def name(self, code: str) -> str:
        """Return the display name of a code, also for hidden ones."""
        return self._display.get(code) or self._standard.get(code) or f"Unknown ({code})"

    def code(self, name: str) -> str | None:
        """Return the code for a display name (enabled, then any known name)."""
        if (code := self._reverse.get(name)) is not None:
            return code
        if (match := _UNKNOWN_RE.match(name)) is not None:
            return match.group(1).upper()
        return None

    def options_with(self, current_code: str | None) -> list[str]:
        """Return the options plus the name of a hidden current code."""
        options = self.options
        if current_code and current_code not in self._display:
            name = self.name(current_code)
            if name not in options:
                options.append(name)
        return options


class SourceMap(CodeMap):
    """Inputs (SLI codes) enabled by the options."""

    def __init__(self, options: Mapping[str, Any]) -> None:
        """Build the map from config entry options."""
        enabled = options.get(CONF_SOURCES)
        if isinstance(enabled, Mapping):
            enabled = list(enabled)
        super().__init__(
            enabled if enabled is not None else available_sources(options.get(CONF_MODEL)),
            options.get(CONF_SOURCE_NAMES) or {},
            DEFAULT_SOURCES,
        )


class SoundModeMap(CodeMap):
    """Listening modes (LMD codes) enabled by the options."""

    def __init__(self, options: Mapping[str, Any]) -> None:
        """Build the map from config entry options."""
        enabled = options.get(CONF_SOUND_MODES)
        super().__init__(
            enabled
            if enabled is not None
            else default_options(options.get(CONF_MODEL))[CONF_SOUND_MODES],
            {},
            LISTENING_MODES,
        )
