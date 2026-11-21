"""Tests for the Home Assistant independent options handling."""

from __future__ import annotations

from custom_components.eiscp_legacy import const, models
from custom_components.eiscp_legacy.options import (
    SoundModeMap,
    SourceMap,
    available_sound_modes,
    available_sources,
    change_model,
    default_options,
    migrate_options,
    source_label,
    standard_source_name,
)

KEY = next(iter(models.MODELS))
PROFILE = models.MODELS[KEY]


def test_available_for_model() -> None:
    assert available_sources(KEY) == list(PROFILE.sources)
    assert available_sound_modes(KEY) == list(PROFILE.listening_modes)


def test_available_for_other_and_unknown() -> None:
    for key in ("other", "nonexistent", None):
        assert available_sources(key) == list(const.DEFAULT_SOURCES)
        assert available_sound_modes(key) == list(const.LISTENING_MODES)


def test_default_options_model() -> None:
    options = default_options(KEY)
    assert options == {
        "model": KEY,
        "volume_resolution": 100,
        "max_volume": 100,
        "sources": list(PROFILE.sources),
        "source_names": {},
        "sound_modes": list(PROFILE.listening_modes),
    }


def test_default_options_other() -> None:
    options = default_options("other")
    assert options["model"] == "other"
    assert options["sources"] == list(const.DEFAULT_SOURCES)
    assert options["sound_modes"] == const.DEFAULT_SOUND_MODES
    assert options["sound_modes"] is not const.DEFAULT_SOUND_MODES


def test_default_options_unknown_model_is_other() -> None:
    assert default_options("nope")["model"] == "other"


def test_migrate_options() -> None:
    old = {
        "volume_resolution": 80,
        "max_volume": 60,
        "sources": {"03": "AUX1", "22": "Record Player", "23": "Hi-Fi", "99": "Mystery"},
        "sound_modes": ["00", "0D"],
    }
    new = migrate_options(old)
    assert new == {
        "model": "other",
        "volume_resolution": 80,
        "max_volume": 60,
        "sources": ["03", "22", "23", "99"],
        "source_names": {"22": "Record Player", "23": "Hi-Fi", "99": "Mystery"},
        "sound_modes": ["00", "0D"],
    }


def test_migrate_options_fills_defaults() -> None:
    new = migrate_options({})
    assert new == default_options("other")


def test_migrate_options_empty_sources_uses_defaults() -> None:
    new = migrate_options({"sources": {}})
    assert new["sources"] == list(const.DEFAULT_SOURCES)


def test_change_model_resets_and_keeps_names() -> None:
    other_only = next(c for c in const.DEFAULT_SOURCES if c not in PROFILE.sources)
    kept = PROFILE.sources[0]
    options = {
        **default_options("other"),
        "volume_resolution": 200,
        "max_volume": 50,
        "sources": ["22"],
        "source_names": {kept: "Kept", other_only: "Gone"},
    }
    new = change_model(options, KEY)
    assert new["model"] == KEY
    assert new["volume_resolution"] == 200
    assert new["max_volume"] == 50
    assert new["sources"] == list(PROFILE.sources)
    assert new["sound_modes"] == list(PROFILE.listening_modes)
    assert new["source_names"] == {kept: "Kept"}
    assert options["source_names"] == {kept: "Kept", other_only: "Gone"}


def test_source_map_names_and_order() -> None:
    options = {"sources": ["22", "03", "23"], "source_names": {"22": "Record Player"}}
    sources = SourceMap(options)
    assert sources.options == ["Record Player", "AUX1", "CD"]
    assert sources.name("22") == "Record Player"
    assert sources.name("03") == "AUX1"


def test_source_map_safety_net_for_hidden_codes() -> None:
    sources = SourceMap({"sources": ["22"], "source_names": {}})
    assert sources.name("23") == "CD"
    assert sources.name("FF") == "Unknown (FF)"
    assert sources.options == ["PHONO"]


def test_source_map_code_lookup() -> None:
    sources = SourceMap({"sources": ["22"], "source_names": {"22": "Record Player"}})
    assert sources.code("Record Player") == "22"
    # hidden but known standard names still resolve
    assert sources.code("CD") == "23"
    assert sources.code("Unknown (7F)") == "7F"
    assert sources.code("nonsense") is None


def test_source_map_custom_name_wins_over_standard() -> None:
    sources = SourceMap({"sources": ["22", "23"], "source_names": {"22": "CD"}})
    assert sources.options == ["CD", "CD (23)"]
    assert sources.code("CD") == "22"
    assert sources.code("CD (23)") == "23"


def test_source_map_duplicate_names_disambiguated() -> None:
    sources = SourceMap(
        {"sources": ["03", "04", "05"], "source_names": {"04": "AUX1", "05": "AUX1"}}
    )
    assert sources.options == ["AUX1", "AUX1 (04)", "AUX1 (05)"]
    assert sources.name("04") == "AUX1 (04)"
    assert sources.code("AUX1 (05)") == "05"


def test_source_map_options_with() -> None:
    sources = SourceMap({"sources": ["22"], "source_names": {}})
    assert sources.options_with("22") == ["PHONO"]
    assert sources.options_with(None) == ["PHONO"]
    assert sources.options_with("23") == ["PHONO", "CD"]
    assert sources.options_with("FF") == ["PHONO", "Unknown (FF)"]
    # options itself is not modified
    assert sources.options == ["PHONO"]


def test_source_map_accepts_legacy_dict() -> None:
    sources = SourceMap({"sources": {"22": "x"}})
    assert sources.options == ["PHONO"]


def test_source_map_missing_options_use_model_defaults() -> None:
    expected = [const.DEFAULT_SOURCES[c] for c in PROFILE.sources if c in const.DEFAULT_SOURCES]
    assert SourceMap({"model": KEY}).options[: len(expected)] == expected


def test_sound_mode_map() -> None:
    modes = SoundModeMap({"sound_modes": ["0D", "00"]})
    assert modes.options == [const.LISTENING_MODES["0D"], const.LISTENING_MODES["00"]]
    assert modes.name("0D") == const.LISTENING_MODES["0D"]
    assert modes.name("01") == const.LISTENING_MODES["01"]
    assert modes.name("EE") == "Unknown (EE)"
    assert modes.code(const.LISTENING_MODES["01"]) == "01"
    assert modes.code("Unknown (EE)") == "EE"
    assert modes.code("nope") is None
    assert modes.options_with("01") == [*modes.options, const.LISTENING_MODES["01"]]
    assert modes.options_with("00") == modes.options


def test_labels() -> None:
    assert source_label("22") == "PHONO (22)"
    assert source_label("FF") == "Unknown (FF)"
    assert standard_source_name("22") == "PHONO"
    assert standard_source_name("FF") == "Unknown (FF)"
