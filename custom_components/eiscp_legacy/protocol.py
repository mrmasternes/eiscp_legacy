"""eISCP / ISCP message framing and value helpers.

This module has no Home Assistant imports so it can be unit tested on its own.

Two wire formats are supported:

* eISCP (Ethernet): every message is wrapped in a 16-byte header that starts
  with ``ISCP``. This is what receivers speak on TCP port 60128.
* ISCP (serial / RS-232): plain ``!1<command>`` text terminated by CR, with
  replies terminated by EOF (0x1A) and/or CR/LF. Used through a serial-to-TCP
  bridge such as ser2net.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

PROTOCOL_EISCP = "eiscp"
PROTOCOL_ISCP = "iscp"
PROTOCOLS = (PROTOCOL_EISCP, PROTOCOL_ISCP)

EISCP_MAGIC = b"ISCP"
# magic, header size, data size, version, 3 reserved bytes
EISCP_HEADER = struct.Struct(">4sIIB3x")
EISCP_HEADER_SIZE = EISCP_HEADER.size  # 16
EISCP_VERSION = 1
MAX_DATA_SIZE = 1 << 16

_TERMINATORS = b"\x1a\r\n"
_MAX_ISCP_BUFFER = 4096


@dataclass(frozen=True, slots=True)
class Message:
    """A single ISCP message, e.g. command ``PWR`` with value ``01``."""

    command: str
    value: str

    @property
    def raw(self) -> str:
        """Return the message as ``<command><value>``."""
        return f"{self.command}{self.value}"

    @classmethod
    def parse(cls, text: str) -> Message | None:
        """Parse ``!1PWR01``, ``PWR01`` or similar into a message."""
        text = text.strip("\x00\x1a\r\n ")
        if text.startswith("!") and len(text) >= 2:
            # "!" followed by the unit type character ("1" = receiver).
            text = text[2:]
        if len(text) < 3:
            return None
        command = text[:3].upper()
        if not command.isalnum():
            return None
        return cls(command, text[3:].strip())


def normalize_command(command: str) -> str:
    """Strip a leading ``!1`` and surrounding whitespace from a user command."""
    command = command.strip()
    if command.startswith("!1"):
        command = command[2:]
    return command


def is_valid_command(command: str) -> bool:
    """Return True if the command looks sendable (printable ASCII, 3+ chars)."""
    if len(command) < 3 or len(command) > 200:
        return False
    if not command[:3].isalnum():
        return False
    return all(32 <= ord(char) < 127 for char in command)


def encode(protocol: str, command: str) -> bytes:
    """Encode a command (``PWR01``) for the wire."""
    data = f"!1{command}\r".encode("ascii")
    if protocol == PROTOCOL_ISCP:
        return data
    header = EISCP_HEADER.pack(EISCP_MAGIC, EISCP_HEADER_SIZE, len(data), EISCP_VERSION)
    return header + data


def _decode_text(payload: bytes) -> Message | None:
    return Message.parse(payload.decode("ascii", errors="replace"))


class EiscpDecoder:
    """Incremental decoder for an eISCP byte stream."""

    def __init__(self) -> None:
        """Initialize the decoder."""
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Message]:
        """Add received bytes and return the complete messages found."""
        self._buffer += data
        messages: list[Message] = []
        while True:
            start = self._buffer.find(EISCP_MAGIC)
            if start < 0:
                # Keep a few bytes in case the magic is split across reads.
                del self._buffer[: -(len(EISCP_MAGIC) - 1)]
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < EISCP_HEADER_SIZE:
                break
            _, header_size, data_size, _ = EISCP_HEADER.unpack_from(self._buffer)
            if header_size < EISCP_HEADER_SIZE or data_size > MAX_DATA_SIZE:
                # Not a real header; skip the magic and resync.
                del self._buffer[: len(EISCP_MAGIC)]
                continue
            total = header_size + data_size
            if len(self._buffer) < total:
                break
            payload = bytes(self._buffer[header_size:total])
            del self._buffer[:total]
            if (message := _decode_text(payload)) is not None:
                messages.append(message)
        return messages


class IscpDecoder:
    """Incremental decoder for a raw (serial style) ISCP byte stream."""

    def __init__(self) -> None:
        """Initialize the decoder."""
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Message]:
        """Add received bytes and return the complete messages found."""
        self._buffer += data
        messages: list[Message] = []
        while True:
            positions = [pos for t in _TERMINATORS if (pos := self._buffer.find(bytes([t]))) >= 0]
            if not positions:
                if len(self._buffer) > _MAX_ISCP_BUFFER:
                    self._buffer.clear()
                break
            end = min(positions)
            chunk = bytes(self._buffer[:end])
            del self._buffer[: end + 1]
            if chunk.strip() and (message := _decode_text(chunk)) is not None:
                messages.append(message)
        return messages


def make_decoder(protocol: str) -> EiscpDecoder | IscpDecoder:
    """Return a decoder for the given protocol."""
    return IscpDecoder() if protocol == PROTOCOL_ISCP else EiscpDecoder()


def volume_to_level(value: str | None, resolution: int) -> float | None:
    """Convert a hex ``MVL`` value (``"23"``) to a 0..1 level."""
    if not value or resolution <= 0:
        return None
    try:
        raw = int(value, 16)
    except ValueError:
        return None
    return max(0.0, min(1.0, raw / resolution))


def level_to_volume(level: float, resolution: int, max_level: float = 1.0) -> str:
    """Convert a 0..1 level to a hex ``MVL`` value, capped at ``max_level``."""
    level = max(0.0, min(level, max_level, 1.0))
    return f"{round(level * resolution):02X}"
