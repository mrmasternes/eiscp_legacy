"""Test setup: import integration submodules without Home Assistant installed."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types

import pytest_asyncio

ROOT = Path(__file__).resolve().parents[2]
_COMPONENTS = ROOT / "custom_components"
_INTEGRATION = _COMPONENTS / "eiscp_legacy"


def _stub_package(name: str, path: Path) -> None:
    """Register a bare package so its __init__.py never runs."""
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_stub_package("custom_components", _COMPONENTS)
_stub_package("custom_components.eiscp_legacy", _INTEGRATION)
sys.modules["custom_components"].eiscp_legacy = sys.modules["custom_components.eiscp_legacy"]

from custom_components.eiscp_legacy.protocol import (  # noqa: E402
    PROTOCOL_ISCP,
    EiscpDecoder,
    IscpDecoder,
    Message,
)

INITIAL_STATE = {"PWR": "01", "MVL": "23", "AMT": "00", "SLI": "23", "LMD": "0D"}


class FakeReceiver:
    """A tiny fake Onkyo/Integra receiver speaking eISCP or ISCP over TCP."""

    def __init__(self, protocol: str = "eiscp") -> None:
        """Initialize the fake."""
        self.protocol = protocol
        self.state: dict[str, str] = dict(INITIAL_STATE)
        self.commands: list[str] = []
        self.silent = False
        self.connections = 0
        self.port = 0
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        """Listen on a random local port."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Stop listening and close all connections."""
        await self.drop_connections()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def drop_connections(self) -> None:
        """Close every open client connection (the server keeps listening)."""
        writers, self._writers = self._writers, []
        for writer in writers:
            writer.close()
        for writer in writers:
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def _frame(self, command: str) -> bytes:
        """Encode a reply the way a receiver does (EOF + CR/LF terminated)."""
        data = f"!1{command}\x1a\r\n".encode("ascii")
        if self.protocol == PROTOCOL_ISCP:
            return data
        return _eiscp_header(len(data)) + data

    async def _send(self, writer: asyncio.StreamWriter, command: str) -> None:
        writer.write(self._frame(command))
        await writer.drain()

    async def _apply(self, writer: asyncio.StreamWriter, message: Message) -> None:
        cmd, value = message.command, message.value
        if value == "QSTN":
            await self._send(writer, f"{cmd}{self.state.get(cmd, 'N/A')}")
            return
        if cmd not in self.state:
            return
        if cmd == "MVL" and value in ("UP", "DOWN"):
            level = int(self.state["MVL"], 16) + (1 if value == "UP" else -1)
            value = f"{max(0, level):02X}"
        self.state[cmd] = value
        await self._send(writer, f"{cmd}{value}")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.append(writer)
        decoder = IscpDecoder() if self.protocol == PROTOCOL_ISCP else EiscpDecoder()
        try:
            while data := await reader.read(4096):
                for message in decoder.feed(data):
                    self.commands.append(message.raw)
                    if not self.silent:
                        await self._apply(writer, message)
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()


def _eiscp_header(data_size: int) -> bytes:
    return b"ISCP" + (16).to_bytes(4, "big") + data_size.to_bytes(4, "big") + b"\x01\x00\x00\x00"


@pytest_asyncio.fixture
async def fake_receiver_factory():
    """Return an async factory creating started fake receivers (cleaned up afterwards)."""
    created: list[FakeReceiver] = []

    async def _factory(protocol: str = "eiscp") -> FakeReceiver:
        fake = FakeReceiver(protocol)
        await fake.start()
        created.append(fake)
        return fake

    yield _factory
    for fake in created:
        await fake.stop()


@pytest_asyncio.fixture
async def fake_receiver(fake_receiver_factory):
    """A started eISCP fake receiver."""
    return await fake_receiver_factory("eiscp")
