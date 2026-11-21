"""Optional, auto-detected receiver features.

This module has no Home Assistant imports so it can be unit tested on its own.
Each feature is one ISCP command that older receivers may or may not support.
Unsupported commands get no reply at all, which is how detection works.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
import logging
from typing import Any, Protocol

from .connection import NotConnectedError

_LOGGER = logging.getLogger(__name__)

PLATFORM_NUMBER = "number"
PLATFORM_SELECT = "select"
PLATFORM_SENSOR = "sensor"
PLATFORM_SWITCH = "switch"

CATEGORY_CONFIG = "config"

# A frequency at or above this (in 10 kHz units) is FM, below it AM (kHz).
FM_MIN_RAW = 8750

SWL_MIN = -15
SWL_MAX = 12
SLEEP_MAX = 90
PRESET_COUNT = 40

_NOT_AVAILABLE = "N/A"


class _Queryable(Protocol):
    """The part of the receiver connection needed for detection."""

    async def query(self, command: str, timeout: float = 5.0) -> str:  # noqa: ASYNC109
        """Query a 3-letter command."""


def _usable(value: str | None) -> str | None:
    """Return the stripped, upper-case value, or None when missing or N/A."""
    if value is None:
        return None
    value = value.strip().upper()
    if not value or value == _NOT_AVAILABLE:
        return None
    return value


# -- value codecs -------------------------------------------------------------


def decode_subwoofer_level(value: str | None) -> int | None:
    """Decode an SWL value (``-F``..``+C``, ``00``) to dB."""
    value = _usable(value)
    if value is None or len(value) != 2:
        return None
    if value == "00":
        return 0
    sign, digit = value[0], value[1]
    if sign not in "+-":
        return None
    try:
        level = int(digit, 16)
    except ValueError:
        return None
    if level == 0:
        return 0
    level = level if sign == "+" else -level
    return level if SWL_MIN <= level <= SWL_MAX else None


def encode_subwoofer_level(level: float) -> str:
    """Encode dB (-15..+12) as an SWL value."""
    steps = max(SWL_MIN, min(SWL_MAX, round(level)))
    if steps == 0:
        return "00"
    return f"{'+' if steps > 0 else '-'}{abs(steps):X}"


def decode_sleep(value: str | None) -> int | None:
    """Decode an SLP value to minutes (``00``/``OFF`` is 0)."""
    value = _usable(value)
    if value is None:
        return None
    if value == "OFF":
        return 0
    try:
        minutes = int(value, 16)
    except ValueError:
        return None
    return minutes if 0 <= minutes <= SLEEP_MAX else None


def encode_sleep(minutes: float) -> str:
    """Encode minutes as an SLP value (0 is ``OFF``)."""
    steps = max(0, min(SLEEP_MAX, round(minutes)))
    return "OFF" if steps == 0 else f"{steps:02X}"


def format_tuner_frequency(value: str | None) -> str | None:
    """Format a TUN value as ``87.50 MHz`` (FM) or ``1400 kHz`` (AM)."""
    value = _usable(value)
    if value is None:
        return None
    try:
        raw = int(value)
    except ValueError:
        return None
    if raw >= FM_MIN_RAW:
        return f"{raw / 100:.2f} MHz"
    return f"{raw} kHz"


def decode_preset(value: str | None) -> str | None:
    """Decode a PRS value (hex ``01``..``28``) to the option ``"1"``..``"40"``."""
    value = _usable(value)
    if value is None:
        return None
    try:
        preset = int(value, 16)
    except ValueError:
        return None
    return str(preset) if 1 <= preset <= PRESET_COUNT else None


def encode_preset(option: str) -> str | None:
    """Encode the option ``"1"``..``"40"`` as a PRS value."""
    try:
        preset = int(option)
    except ValueError:
        return None
    return f"{preset:02X}" if 1 <= preset <= PRESET_COUNT else None


def decode_switch(value: str | None) -> bool | None:
    """Decode a ``00``/``01`` value."""
    value = _usable(value)
    if value == "01":
        return True
    if value == "00":
        return False
    return None


def encode_switch(on: bool) -> str:
    """Encode a switch state."""
    return "01" if on else "00"


# -- feature table ------------------------------------------------------------


@dataclass(frozen=True)
class Feature:
    """One optional receiver feature."""

    key: str
    command: str
    platform: str
    probe: bool = True
    entity_category: str | None = None
    # Select: code -> option key (a translation key, except for presets).
    options: dict[str, str] | None = None
    # Number only.
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    unit: str | None = None
    # Codecs: wire value -> state, and entity value -> wire value.
    decode: Callable[[str | None], Any] | None = None
    encode: Callable[[Any], str | None] | None = None
    enabled_default: bool = True
    assumed_state: bool = False

    @property
    def option_list(self) -> list[str]:
        """Return the select options in code order."""
        return list(self.options.values()) if self.options else []


def _option_codecs(
    options: dict[str, str],
) -> tuple[Callable[[str | None], str | None], Callable[[str], str | None]]:
    """Build decode/encode functions for a code -> option map."""
    by_option = {option: code for code, option in options.items()}

    def decode(value: str | None) -> str | None:
        value = _usable(value)
        return options.get(value) if value is not None else None

    def encode(option: str) -> str | None:
        return by_option.get(option)

    return decode, encode


def _select(
    key: str, command: str, options: dict[str, str], category: str | None = CATEGORY_CONFIG
) -> Feature:
    decode, encode = _option_codecs(options)
    return Feature(
        key,
        command,
        PLATFORM_SELECT,
        entity_category=category,
        options=options,
        decode=decode,
        encode=encode,
    )


def _switch(key: str, command: str, category: str | None = CATEGORY_CONFIG) -> Feature:
    return Feature(
        key,
        command,
        PLATFORM_SWITCH,
        entity_category=category,
        decode=decode_switch,
        encode=encode_switch,
    )


def _trigger(key: str, command: str) -> Feature:
    return Feature(
        key,
        command,
        PLATFORM_SWITCH,
        probe=False,
        entity_category=CATEGORY_CONFIG,
        decode=decode_switch,
        encode=encode_switch,
        enabled_default=False,
        assumed_state=True,
    )


LATE_NIGHT_OPTIONS = {"00": "off", "01": "low", "02": "high"}
DIMMER_OPTIONS = {
    "00": "bright",
    "01": "dim",
    "02": "dark",
    "03": "shut_off",
    "08": "bright_led_off",
}
AUDIO_SELECTOR_OPTIONS = {
    "00": "auto",
    "01": "multichannel",
    "02": "analog",
    "03": "ilink",
    "04": "hdmi",
    "05": "coax_opt",
    "06": "balance",
}
MONITOR_RESOLUTION_OPTIONS = {
    "00": "through",
    "01": "auto",
    "02": "480p",
    "03": "720p",
    "04": "1080i",
    "05": "1080p",
    "06": "source",
    "07": "1080p_24",
}
HDMI_OUTPUT_OPTIONS = {
    "00": "analog",
    "01": "main",
    "02": "sub",
    "03": "both",
    "04": "both_main",
    "05": "both_sub",
}
PRESET_OPTIONS = {f"{n:02X}": str(n) for n in range(1, PRESET_COUNT + 1)}

FEATURES: tuple[Feature, ...] = (
    Feature(
        "subwoofer_level",
        "SWL",
        PLATFORM_NUMBER,
        min_value=SWL_MIN,
        max_value=SWL_MAX,
        step=1,
        unit="dB",
        decode=decode_subwoofer_level,
        encode=encode_subwoofer_level,
    ),
    _select("late_night", "LTN", LATE_NIGHT_OPTIONS, category=None),
    _switch("re_eq", "RAS"),
    _select("dimmer", "DIM", DIMMER_OPTIONS),
    Feature(
        "sleep_timer",
        "SLP",
        PLATFORM_NUMBER,
        min_value=0,
        max_value=SLEEP_MAX,
        step=1,
        unit="min",
        decode=decode_sleep,
        encode=encode_sleep,
    ),
    _select("audio_selector", "SLA", AUDIO_SELECTOR_OPTIONS),
    _select("monitor_resolution", "RES", MONITOR_RESOLUTION_OPTIONS),
    _select("hdmi_output", "HDO", HDMI_OUTPUT_OPTIONS),
    Feature("tuner_frequency", "TUN", PLATFORM_SENSOR, decode=format_tuner_frequency),
    Feature(
        "tuner_preset",
        "PRS",
        PLATFORM_SELECT,
        options=PRESET_OPTIONS,
        decode=decode_preset,
        encode=encode_preset,
    ),
    _switch("zone2_power", "ZPW", category=None),
    _trigger("trigger_a", "TGA"),
    _trigger("trigger_b", "TGB"),
    _trigger("trigger_c", "TGC"),
)

FEATURES_BY_KEY: dict[str, Feature] = {feature.key: feature for feature in FEATURES}


def features_for_platform(platform: str, enabled: Collection[str]) -> list[Feature]:
    """Return the features of a platform that should get an entity."""
    return [
        feature
        for feature in FEATURES
        if feature.platform == platform and (not feature.probe or feature.key in enabled)
    ]


def refresh_commands_for(enabled: Collection[str]) -> tuple[str, ...]:
    """Return the commands of enabled, queryable features (in table order)."""
    return tuple(
        feature.command for feature in FEATURES if feature.probe and feature.key in enabled
    )


async def async_detect_features(
    receiver: _Queryable,
    timeout: float = 1.0,  # noqa: ASYNC109
    skip: Collection[str] = (),
) -> set[str]:
    """Query each probeable feature and return the keys that got a reply.

    Any reply counts (an empty value too) except ``N/A``. Features in ``skip``
    are not queried. A timeout means unsupported.
    """
    found: set[str] = set()
    for feature in FEATURES:
        if not feature.probe or feature.key in skip:
            continue
        try:
            value = await receiver.query(feature.command, timeout)
        except (TimeoutError, NotConnectedError):
            _LOGGER.debug("Feature %s (%s) not detected", feature.key, feature.command)
            continue
        if value.strip().upper() == _NOT_AVAILABLE:
            continue
        _LOGGER.debug("Feature %s (%s) detected: %r", feature.key, feature.command, value)
        found.add(feature.key)
    return found
