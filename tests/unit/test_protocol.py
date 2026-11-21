"""Tests for the eISCP / ISCP protocol helpers."""

from __future__ import annotations

import pytest

from custom_components.eiscp_legacy.protocol import (
    PROTOCOL_EISCP,
    PROTOCOL_ISCP,
    EiscpDecoder,
    IscpDecoder,
    Message,
    encode,
    is_valid_command,
    level_to_volume,
    make_decoder,
    normalize_command,
    volume_to_level,
)


def _eiscp(text: str) -> bytes:
    data = text.encode("ascii")
    return b"ISCP" + (16).to_bytes(4, "big") + len(data).to_bytes(4, "big") + b"\x01\0\0\0" + data


def test_encode_eiscp_header_exact() -> None:
    assert encode(PROTOCOL_EISCP, "PWRQSTN") == (
        b"ISCP\x00\x00\x00\x10\x00\x00\x00\x0a\x01\x00\x00\x00!1PWRQSTN\r"
    )


def test_encode_iscp_plain() -> None:
    assert encode(PROTOCOL_ISCP, "PWR01") == b"!1PWR01\r"


def test_decode_round_trip() -> None:
    assert EiscpDecoder().feed(encode(PROTOCOL_EISCP, "MVL23")) == [Message("MVL", "23")]


def test_split_byte_by_byte() -> None:
    decoder = EiscpDecoder()
    messages: list[Message] = []
    for byte in _eiscp("!1PWR01\x1a\r\n"):
        messages += decoder.feed(bytes([byte]))
    assert messages == [Message("PWR", "01")]


def test_two_messages_in_one_chunk() -> None:
    data = _eiscp("!1PWR01\x1a\r\n") + _eiscp("!1MVL1E\x1a\r\n")
    assert EiscpDecoder().feed(data) == [Message("PWR", "01"), Message("MVL", "1E")]


def test_garbage_before_header() -> None:
    data = b"\x00\xffjunk" + _eiscp("!1AMT01\x1a\r\n")
    assert EiscpDecoder().feed(data) == [Message("AMT", "01")]


def test_iscp_decoder_terminators() -> None:
    decoder = IscpDecoder()
    assert decoder.feed(b"!1PWR01\x1a\r\n!1MVL") == [Message("PWR", "01")]
    assert decoder.feed(b"23\x1a\r\n") == [Message("MVL", "23")]
    assert decoder.feed(b"!1SLI03\r") == [Message("SLI", "03")]


def test_make_decoder() -> None:
    assert isinstance(make_decoder(PROTOCOL_ISCP), IscpDecoder)
    assert isinstance(make_decoder(PROTOCOL_EISCP), EiscpDecoder)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("!1PWR01", Message("PWR", "01")),
        ("PWR01\x1a\r\n", Message("PWR", "01")),
        ("!1pwrqstn", Message("PWR", "qstn")),
        ("!1NLSU0-Radio", Message("NLS", "U0-Radio")),
        ("!1PWR", Message("PWR", "")),
        ("!1", None),
        ("", None),
        ("!1!!!01", None),
    ],
)
def test_message_parse(text: str, expected: Message | None) -> None:
    assert Message.parse(text) == expected


def test_message_raw() -> None:
    assert Message("PWR", "01").raw == "PWR01"


def test_volume_to_level() -> None:
    assert volume_to_level("23", 100) == pytest.approx(0.35)
    assert volume_to_level("64", 100) == 1.0
    assert volume_to_level("FF", 100) == 1.0
    assert volume_to_level("N/A", 100) is None
    assert volume_to_level(None, 100) is None
    assert volume_to_level("23", 0) is None


def test_level_to_volume() -> None:
    assert level_to_volume(0.35, 100) == "23"
    assert level_to_volume(1.0, 100, max_level=0.5) == "32"
    assert level_to_volume(2.0, 80) == "50"
    assert level_to_volume(-1.0, 80) == "00"


def test_normalize_and_validate() -> None:
    assert normalize_command("  !1PWR01 ") == "PWR01"
    assert normalize_command("PWR01") == "PWR01"
    assert is_valid_command("PWR01")
    assert is_valid_command("NLSU0-Radio")
    assert not is_valid_command("PW")
    assert not is_valid_command("!!!01")
    assert not is_valid_command("PWR\x00")
    assert not is_valid_command("PWR" + "A" * 300)
    assert not is_valid_command("PWRé")
