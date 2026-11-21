"""Tests for the per-model profile data."""

from __future__ import annotations

import re

from custom_components.eiscp_legacy import const, models


def test_dtc_9_8_profile() -> None:
    profile = models.get_profile("dtc_9_8")
    assert profile is not None
    assert profile.name == "Integra DTC-9.8"
    assert profile.sources == (
        "00",  # VCR/DVR
        "01",  # CBL/SAT
        "02",  # GAME
        "03",  # AUX1
        "04",  # AUX2
        "10",  # BD/DVD
        "20",  # TAPE
        "22",  # PHONO
        "23",  # CD
        "24",  # FM
        "25",  # AM
        "26",  # TUNER
        "31",  # XM
        "32",  # SIRIUS
    )
    assert profile.listening_modes == (
        "00",  # STEREO
        "01",  # DIRECT
        "02",  # SURROUND
        "04",  # THX
        "07",  # MONO MOVIE
        "08",  # ORCHESTRA
        "09",  # UNPLUGGED
        "0A",  # STUDIO-MIX
        "0B",  # TV LOGIC
        "0C",  # ALL CH STEREO
        "0D",  # THEATER-DIMENSIONAL
        "0F",  # MONO
        "13",  # FULL MONO
        "40",  # 5.1ch Surround / Straight Decode
        "41",  # Dolby EX / DTS ES
        "42",  # THX Cinema
        "43",  # THX Surround EX
        "50",  # THX U2/S2 Cinema
        "51",  # THX U2/S2 Music
        "52",  # THX U2/S2 Games
        "80",  # PLII/PLIIx Movie
        "81",  # PLII/PLIIx Music
        "82",  # Neo:6 Cinema
        "83",  # Neo:6 Music
        "84",  # PLII/PLIIx THX Cinema
        "85",  # Neo:6 THX Cinema
        "86",  # PLII/PLIIx Game
        "88",  # Neural THX
        "89",  # PLII/PLIIx THX Games
        "8A",  # Neo:6 THX Games
    )


def test_profile_codes_have_names() -> None:
    for profile in models.MODELS.values():
        assert profile.sources
        assert profile.listening_modes
        for code in profile.sources:
            assert code in const.DEFAULT_SOURCES, (profile.key, code)
        for code in profile.listening_modes:
            assert code in const.LISTENING_MODES, (profile.key, code)
        assert all(re.fullmatch(r"[0-9A-F]{2}", c) for c in profile.sources)
        assert all(re.fullmatch(r"[0-9A-F]{2}", c) for c in profile.listening_modes)


def test_keys_unique_and_slug_like() -> None:
    keys = [p.key for p in models.MODELS.values()]
    assert len(keys) == len(set(keys))
    for key, profile in models.MODELS.items():
        assert key == profile.key
        assert re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", key)
    assert models.MODEL_OTHER not in models.MODELS


def test_get_profile_unknown() -> None:
    assert models.get_profile("other") is None
    assert models.get_profile(None) is None
    assert models.get_profile("no_such_model") is None


def test_model_choices_sorted() -> None:
    choices = models.model_choices()
    assert len(choices) == len(models.MODELS)
    names = [name for _, name in choices]
    assert names == sorted(names)
    assert all(key != models.MODEL_OTHER for key, _ in choices)
