"""Constants for the eISCP Legacy Receiver integration."""

from __future__ import annotations

import re

DOMAIN = "eiscp_legacy"

CONF_PROTOCOL = "protocol"
CONF_VOLUME_RESOLUTION = "volume_resolution"
CONF_MAX_VOLUME = "max_volume"
CONF_SOURCES = "sources"
CONF_SOUND_MODES = "sound_modes"

DEFAULT_PORT = 60128
DEFAULT_NAME = "Receiver"
VOLUME_RESOLUTIONS = (50, 80, 100, 200)
DEFAULT_VOLUME_RESOLUTION = 100
DEFAULT_MAX_VOLUME = 100

EVENT_MESSAGE = f"{DOMAIN}_message"

DEFAULT_SOURCES: dict[str, str] = {
    "00": "VCR/DVR",
    "01": "CBL/SAT",
    "02": "GAME",
    "03": "AUX1",
    "04": "AUX2",
    "05": "PC",
    "06": "VIDEO7",
    "07": "Hidden1",
    "08": "Hidden2",
    "10": "BD/DVD",
    "20": "TAPE",
    "21": "TAPE2",
    "22": "PHONO",
    "23": "CD",
    "24": "FM",
    "25": "AM",
    "26": "TUNER",
    "27": "MUSIC SERVER",
    "28": "INTERNET RADIO",
    "29": "USB",
    "2A": "USB (rear)",
    "2B": "NETWORK",
    "2C": "USB (toggle)",
    "30": "MULTI CH",
    "31": "XM",
    "32": "SIRIUS",
    "40": "UNIVERSAL PORT",
}

LISTENING_MODES: dict[str, str] = {
    "00": "STEREO",
    "01": "DIRECT",
    "02": "SURROUND",
    "03": "FILM / Game-RPG",
    "04": "THX",
    "05": "ACTION / Game-Action",
    "06": "MUSICAL / Game-Rock",
    "07": "MONO MOVIE",
    "08": "ORCHESTRA",
    "09": "UNPLUGGED",
    "0A": "STUDIO-MIX",
    "0B": "TV LOGIC",
    "0C": "ALL CH STEREO",
    "0D": "THEATER-DIMENSIONAL",
    "0E": "ENHANCED 7 / Game-Sports",
    "0F": "MONO",
    "11": "PURE AUDIO",
    "12": "MULTIPLEX",
    "13": "FULL MONO",
    "14": "DOLBY VIRTUAL",
    "15": "DTS Surround Sensation",
    "16": "Audyssey DSX",
    "1F": "Whole House Mode",
    "40": "5.1ch Surround / Straight Decode",
    "41": "Dolby EX / DTS ES",
    "42": "THX Cinema",
    "43": "THX Surround EX",
    "44": "THX Music",
    "45": "THX Games",
    "50": "THX U2/S2/I/S Cinema",
    "51": "THX U2/S2/I/S Music",
    "52": "THX U2/S2/I/S Games",
    "80": "PLII/PLIIx Movie",
    "81": "PLII/PLIIx Music",
    "82": "Neo:6 / Neo:X Cinema",
    "83": "Neo:6 / Neo:X Music",
    "84": "PLII/PLIIx THX Cinema",
    "85": "Neo:6 / Neo:X THX Cinema",
    "86": "PLII/PLIIx Game",
    "87": "Neural Surr",
    "88": "Neural THX / Neural Surround",
    "89": "PLII/PLIIx THX Games",
    "8A": "Neo:6 / Neo:X THX Games",
    "8B": "PLII/PLIIx THX Music",
    "8C": "Neo:6 / Neo:X THX Music",
    "8D": "Neural THX Cinema",
    "8E": "Neural THX Music",
    "8F": "Neural THX Games",
    "90": "PLIIz Height",
    "91": "Neo:6 Cinema DTS SS",
    "92": "Neo:6 Music DTS SS",
    "93": "Neural Digital Music",
    "94": "PLIIz + THX Cinema",
    "95": "PLIIz + THX Music",
    "96": "PLIIz + THX Games",
    "97": "PLIIz + THX U2/S2 Cinema",
    "98": "PLIIz + THX U2/S2 Music",
    "99": "PLIIz + THX U2/S2 Games",
    "9A": "Neo:X Game",
    "A0": "PLIIx Movie + Audyssey DSX",
    "A1": "PLIIx Music + Audyssey DSX",
    "A2": "PLIIx Game + Audyssey DSX",
    "A3": "Neo:6 Cinema + Audyssey DSX",
    "A4": "Neo:6 Music + Audyssey DSX",
    "A5": "Neural Surround + Audyssey DSX",
    "A6": "Neural Digital Music + Audyssey DSX",
    "A7": "Dolby EX + Audyssey DSX",
}

DEFAULT_SOUND_MODES: list[str] = [
    "00",
    "01",
    "02",
    "0C",
    "0D",
    "0F",
    "11",
    "40",
    "41",
    "80",
    "81",
    "82",
    "83",
    "86",
]

_CODE_RE = re.compile(r"^[0-9A-F]{2}$")


def parse_sources(text: str) -> dict[str, str]:
    """Parse ``code=name`` lines (``:`` also accepted) into a dict.

    Blank lines and lines starting with ``#`` are ignored. Raises ValueError
    for malformed lines or when no source is defined.
    """
    sources: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        positions = [pos for sep in "=:" if (pos := line.find(sep)) >= 0]
        if not positions:
            raise ValueError(f"Missing separator in line: {line}")
        pos = min(positions)
        code = line[:pos].strip().upper()
        name = line[pos + 1 :].strip()
        if not _CODE_RE.match(code):
            raise ValueError(f"Invalid source code: {code}")
        if not name:
            raise ValueError(f"Empty source name for code {code}")
        sources[code] = name
    if not sources:
        raise ValueError("No sources defined")
    return sources


def format_sources(sources: dict[str, str]) -> str:
    """Format a sources dict as one ``code=name`` per line."""
    return "\n".join(f"{code}={name}" for code, name in sources.items())
