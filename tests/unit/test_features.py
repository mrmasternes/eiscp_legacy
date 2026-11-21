"""Tests for the optional feature definitions and detection."""

from __future__ import annotations

import pytest

from custom_components.eiscp_legacy.connection import NotConnectedError, Receiver
from custom_components.eiscp_legacy.features import (
    AUDIO_SELECTOR_OPTIONS,
    DIMMER_OPTIONS,
    FEATURES,
    FEATURES_BY_KEY,
    HDMI_OUTPUT_OPTIONS,
    LATE_NIGHT_OPTIONS,
    MONITOR_RESOLUTION_OPTIONS,
    PLATFORM_SENSOR,
    PLATFORM_SWITCH,
    async_detect_features,
    decode_preset,
    decode_sleep,
    decode_subwoofer_level,
    decode_switch,
    encode_preset,
    encode_sleep,
    encode_subwoofer_level,
    encode_switch,
    features_for_platform,
    format_tuner_frequency,
    refresh_commands_for,
)

PROBED = {f.key for f in FEATURES if f.probe}
TRIGGERS = {"trigger_a", "trigger_b", "trigger_c"}


@pytest.mark.parametrize(
    ("wire", "level"),
    [
        ("-F", -15),
        ("-1", -1),
        ("00", 0),
        ("+1", 1),
        ("+4", 4),
        ("+C", 12),
        ("-a", -10),
        ("+D", None),
        ("-0", 0),
        ("+0", 0),
        ("5", None),
        ("", None),
        ("N/A", None),
        (None, None),
        ("xx", None),
        ("*1", None),
    ],
)
def test_decode_subwoofer_level(wire, level) -> None:
    assert decode_subwoofer_level(wire) == level


@pytest.mark.parametrize(
    ("level", "wire"),
    [
        (-15, "-F"),
        (-1, "-1"),
        (0, "00"),
        (1, "+1"),
        (12, "+C"),
        (-20, "-F"),
        (99, "+C"),
        (3.6, "+4"),
    ],
)
def test_encode_subwoofer_level(level, wire) -> None:
    assert encode_subwoofer_level(level) == wire


def test_subwoofer_level_round_trip() -> None:
    for level in range(-15, 13):
        assert decode_subwoofer_level(encode_subwoofer_level(level)) == level


@pytest.mark.parametrize(
    ("wire", "minutes"),
    [
        ("00", 0),
        ("OFF", 0),
        ("off", 0),
        ("01", 1),
        ("1E", 30),
        ("5A", 90),
        ("5B", None),
        ("", None),
    ],
)
def test_decode_sleep(wire, minutes) -> None:
    assert decode_sleep(wire) == minutes


@pytest.mark.parametrize(
    ("minutes", "wire"), [(0, "OFF"), (1, "01"), (30, "1E"), (90, "5A"), (200, "5A"), (-5, "OFF")]
)
def test_encode_sleep(minutes, wire) -> None:
    assert encode_sleep(minutes) == wire


@pytest.mark.parametrize(
    ("wire", "text"),
    [
        ("01400", "1400 kHz"),
        ("00530", "530 kHz"),
        ("08749", "8749 kHz"),
        ("08750", "87.50 MHz"),
        ("09870", "98.70 MHz"),
        ("10790", "107.90 MHz"),
        ("N/A", None),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_format_tuner_frequency(wire, text) -> None:
    assert format_tuner_frequency(wire) == text


@pytest.mark.parametrize(
    ("wire", "option"),
    [
        ("01", "1"),
        ("0A", "10"),
        ("28", "40"),
        ("29", None),
        ("00", None),
        ("", None),
        ("N/A", None),
    ],
)
def test_decode_preset(wire, option) -> None:
    assert decode_preset(wire) == option


@pytest.mark.parametrize(
    ("option", "wire"),
    [("1", "01"), ("10", "0A"), ("40", "28"), ("0", None), ("41", None), ("x", None)],
)
def test_encode_preset(option, wire) -> None:
    assert encode_preset(option) == wire


def test_preset_options_cover_1_to_40() -> None:
    feature = FEATURES_BY_KEY["tuner_preset"]
    assert feature.option_list == [str(n) for n in range(1, 41)]
    assert feature.options["28"] == "40"
    assert feature.options["01"] == "1"


def test_switch_codec() -> None:
    assert decode_switch("01") is True
    assert decode_switch("00") is False
    assert decode_switch("N/A") is None
    assert decode_switch("") is None
    assert encode_switch(True) == "01"
    assert encode_switch(False) == "00"


def test_option_maps_match_spec() -> None:
    assert LATE_NIGHT_OPTIONS == {"00": "off", "01": "low", "02": "high"}
    assert DIMMER_OPTIONS == {
        "00": "bright",
        "01": "dim",
        "02": "dark",
        "03": "shut_off",
        "08": "bright_led_off",
    }
    assert AUDIO_SELECTOR_OPTIONS["00"] == "auto"
    assert AUDIO_SELECTOR_OPTIONS["06"] == "balance"
    assert MONITOR_RESOLUTION_OPTIONS["00"] == "through"
    assert MONITOR_RESOLUTION_OPTIONS["05"] == "1080p"
    assert MONITOR_RESOLUTION_OPTIONS["07"] == "1080p_24"
    assert list(HDMI_OUTPUT_OPTIONS.values()) == [
        "analog",
        "main",
        "sub",
        "both",
        "both_main",
        "both_sub",
    ]


def test_select_codecs() -> None:
    hdo = FEATURES_BY_KEY["hdmi_output"]
    assert hdo.decode("03") == "both"
    assert hdo.decode("") is None
    assert hdo.decode("N/A") is None
    assert hdo.decode("99") is None
    assert hdo.encode("both_sub") == "05"
    assert hdo.encode("nope") is None
    dim = FEATURES_BY_KEY["dimmer"]
    assert dim.decode("08") == "bright_led_off"
    assert dim.decode("01") == "dim"


def test_option_keys_are_translation_safe() -> None:
    for feature in FEATURES:
        if feature.options and feature.key != "tuner_preset":
            for option in feature.options.values():
                assert option == option.lower()
                assert all(c.isalnum() or c == "_" for c in option)


def test_table_integrity() -> None:
    assert len({f.key for f in FEATURES}) == len(FEATURES)
    assert len({f.command for f in FEATURES}) == len(FEATURES)
    for feature in FEATURES:
        assert len(feature.command) == 3
        assert feature.decode is not None
    for feature in FEATURES:
        if feature.platform != PLATFORM_SENSOR:
            assert feature.encode is not None


def test_triggers_are_not_probed_and_disabled_by_default() -> None:
    for key in TRIGGERS:
        feature = FEATURES_BY_KEY[key]
        assert feature.probe is False
        assert feature.enabled_default is False
        assert feature.assumed_state is True
        assert feature.platform == PLATFORM_SWITCH
        assert feature.entity_category == "config"
    assert FEATURES_BY_KEY["zone2_power"].enabled_default is True


def test_features_for_platform_always_includes_triggers() -> None:
    keys = {f.key for f in features_for_platform(PLATFORM_SWITCH, [])}
    assert keys == TRIGGERS
    keys = {f.key for f in features_for_platform(PLATFORM_SWITCH, ["zone2_power", "re_eq"])}
    assert keys == TRIGGERS | {"zone2_power", "re_eq"}
    assert features_for_platform(PLATFORM_SENSOR, []) == []


def test_refresh_commands_for() -> None:
    assert refresh_commands_for([]) == ()
    assert refresh_commands_for(["tuner_frequency", "subwoofer_level", "trigger_a"]) == (
        "SWL",
        "TUN",
    )


class _ScriptedReceiver:
    """A receiver double answering queries from a dict."""

    def __init__(self, replies: dict[str, object]) -> None:
        self.replies = replies
        self.queried: list[str] = []

    async def query(self, command: str, timeout: float = 5.0) -> str:  # noqa: ASYNC109
        self.queried.append(command)
        reply = self.replies.get(command, TimeoutError())
        if isinstance(reply, BaseException):
            raise reply
        return reply  # type: ignore[return-value]


async def test_detection_handles_errors_and_na() -> None:
    receiver = _ScriptedReceiver(
        {
            "SWL": "+4",
            "HDO": "",
            "LTN": "N/A",
            "DIM": NotConnectedError("down"),
            "SLP": TimeoutError(),
        }
    )
    found = await async_detect_features(receiver, timeout=0.1)
    assert found == {"subwoofer_level", "hdmi_output"}
    assert set(receiver.queried) == {f.command for f in FEATURES if f.probe}


async def test_detection_skips_triggers_and_skip_list() -> None:
    receiver = _ScriptedReceiver({})
    await async_detect_features(receiver, skip={"subwoofer_level"})
    assert "SWL" not in receiver.queried
    assert not {"TGA", "TGB", "TGC"} & set(receiver.queried)


async def test_detection_with_fake_receiver(fake_receiver) -> None:
    fake_receiver.unsupported = {"TFR", "CTL", "ADY", "IFA", "SLA", "TUN"}
    # N/A answer (command unknown to the fake state) counts as unsupported too.
    del fake_receiver.state["RES"]
    receiver = Receiver("127.0.0.1", fake_receiver.port, command_interval=0)
    await receiver.start()
    try:
        assert await receiver.wait_connected(5)
        found = await async_detect_features(receiver, timeout=0.3)
    finally:
        await receiver.stop()
    assert found == PROBED - {"audio_selector", "tuner_frequency", "monitor_resolution"}
    assert "hdmi_output" in found  # empty value still counts
    assert not found & TRIGGERS
    assert not any(c in ("TGA", "TGB", "TGC") for c in fake_receiver.commands)


async def test_detection_with_all_supported(fake_receiver) -> None:
    receiver = Receiver("127.0.0.1", fake_receiver.port, command_interval=0)
    await receiver.start()
    try:
        assert await receiver.wait_connected(5)
        found = await async_detect_features(receiver, timeout=0.3)
    finally:
        await receiver.stop()
    assert found == PROBED


def test_refresh_commands_property() -> None:
    receiver = Receiver("127.0.0.1", 1)
    receiver.refresh_commands = ("PWR", "SWL")
    assert receiver.refresh_commands == ("PWR", "SWL")
