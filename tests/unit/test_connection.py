"""Tests for the asyncio receiver connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import socket

import pytest
import pytest_asyncio

from custom_components.eiscp_legacy import connection
from custom_components.eiscp_legacy.connection import (
    CannotConnect,
    NoResponse,
    NotConnectedError,
    Receiver,
    async_probe,
)

HOST = "127.0.0.1"


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


async def _until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:  # noqa: ASYNC109
    """Poll until predicate is true."""
    async with asyncio.timeout(timeout):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.005)


@pytest.fixture(autouse=True)
def _fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "RECONNECT_DELAY", 0.05)
    monkeypatch.setattr(connection, "INITIAL_BACKOFF", 0.05)


@pytest_asyncio.fixture
async def make_receiver():
    """Factory for receivers that are stopped at teardown."""
    created: list[Receiver] = []

    async def _make(port: int, protocol: str = "eiscp", **kwargs) -> Receiver:
        options = {
            "command_interval": 0.0,
            "keepalive_interval": 5.0,
            "connect_timeout": 2.0,
            "power_on_refresh_delay": 0.05,
        }
        options.update(kwargs)
        receiver = Receiver(HOST, port, protocol, **options)
        created.append(receiver)
        return receiver

    yield _make
    for receiver in created:
        await receiver.stop()


async def _connected(
    make_receiver: Callable[..., Awaitable[Receiver]], fake, protocol: str = "eiscp", **kwargs
) -> Receiver:
    receiver = await make_receiver(fake.port, protocol, **kwargs)
    await receiver.start()
    assert await receiver.wait_connected(3.0)
    return receiver


async def test_probe_success(fake_receiver) -> None:
    assert await async_probe(HOST, fake_receiver.port, "eiscp", timeout=2.0) == "01"


async def test_probe_cannot_connect() -> None:
    with pytest.raises(CannotConnect):
        await async_probe(HOST, _closed_port(), "eiscp", timeout=1.0)


async def test_probe_no_response(fake_receiver) -> None:
    fake_receiver.silent = True
    with pytest.raises(NoResponse):
        await async_probe(HOST, fake_receiver.port, "eiscp", timeout=0.3)


async def test_probe_peer_closes() -> None:
    async def _close(_reader, writer) -> None:
        writer.close()

    server = await asyncio.start_server(_close, HOST, 0)
    try:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(NoResponse):
            await async_probe(HOST, port, "eiscp", timeout=1.0)
    finally:
        server.close()
        await server.wait_closed()


async def test_start_populates_state(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    await _until(lambda: {"PWR", "MVL", "AMT", "SLI", "LMD"} <= receiver.state.keys())
    assert receiver.state == {"PWR": "01", "MVL": "23", "AMT": "00", "SLI": "23", "LMD": "0D"}
    assert receiver.stats["connects"] == 1
    assert receiver.stats["last_connected"] is not None
    assert receiver.stats["messages_received"] >= 5


async def test_send_updates_state_and_notifies(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    await _until(lambda: len(receiver.state) >= 5)
    seen = []
    remove = receiver.add_message_listener(seen.append)
    receiver.send("PWR00")
    await _until(lambda: receiver.state.get("PWR") == "00")
    assert any(m.raw == "PWR00" for m in seen)
    remove()
    count = len(seen)
    receiver.send("MVL30")
    await _until(lambda: receiver.state.get("MVL") == "30")
    assert len(seen) == count


async def test_volume_up_down(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    receiver.send("MVLUP")
    await _until(lambda: receiver.state.get("MVL") == "24")
    receiver.send("MVLDOWN")
    await _until(lambda: receiver.state.get("MVL") == "23")


async def test_listener_exception_is_contained(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)

    def _boom(_message) -> None:
        raise RuntimeError("boom")

    receiver.add_message_listener(_boom)
    receiver.send("AMT01")
    await _until(lambda: receiver.state.get("AMT") == "01")
    assert receiver.connected


async def test_query_returns_value(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    fake_receiver.state["MVL"] = "40"
    assert await receiver.query("MVL", timeout=2.0) == "40"
    assert await receiver.query("ZZZ", timeout=2.0) == "N/A"


async def test_query_timeout(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    await _until(lambda: len(receiver.state) >= 5)
    fake_receiver.silent = True
    with pytest.raises(TimeoutError):
        await receiver.query("MVL", timeout=0.2)
    assert not receiver._pending


async def test_not_connected_errors(make_receiver) -> None:
    receiver = await make_receiver(_closed_port())
    with pytest.raises(NotConnectedError):
        receiver.send("PWR01")
    with pytest.raises(NotConnectedError):
        await receiver.query("PWR")
    receiver.refresh()  # no-op, must not raise
    assert not receiver.connected


async def test_reconnect_after_drop(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    events: list[bool] = []
    receiver.add_connection_listener(events.append)
    await fake_receiver.drop_connections()
    await _until(lambda: events[:2] == [False, True])
    assert receiver.connected
    assert fake_receiver.connections == 2
    assert receiver.stats["connects"] == 2
    assert receiver.stats["disconnects"] == 1
    receiver.send("PWR00")
    await _until(lambda: receiver.state.get("PWR") == "00")


async def test_connects_when_server_appears_later(fake_receiver_factory, make_receiver) -> None:
    fake = await fake_receiver_factory()
    port = fake.port
    await fake.stop()
    receiver = await make_receiver(port)
    await receiver.start()
    await _until(lambda: receiver.stats["last_error"] is not None)
    assert not receiver.connected

    async def _hold(reader, writer) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(_hold, HOST, port)
    try:
        assert await receiver.wait_connected(3.0)
    finally:
        await receiver.stop()
        server.close()
        await server.wait_closed()


async def test_power_on_triggers_refresh(fake_receiver, make_receiver) -> None:
    fake_receiver.state["PWR"] = "00"
    receiver = await _connected(make_receiver, fake_receiver)
    await _until(lambda: len(receiver.state) >= 5)
    fake_receiver.commands.clear()
    receiver.send("PWR01")
    await _until(
        lambda: "MVLQSTN" in fake_receiver.commands and "LMDQSTN" in fake_receiver.commands
    )
    assert fake_receiver.commands[0] == "PWR01"


async def test_pending_query_fails_on_stop(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    await _until(lambda: len(receiver.state) >= 5)
    fake_receiver.silent = True
    task = asyncio.create_task(receiver.query("MVL", timeout=5.0))
    await _until(lambda: bool(receiver._pending))
    await receiver.stop()
    with pytest.raises(NotConnectedError):
        await task


async def test_stop_is_clean_and_idempotent(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    events: list[bool] = []
    receiver.add_connection_listener(events.append)
    run_task = receiver._run_task
    await receiver.stop()
    await receiver.stop()
    assert events == [False]
    assert not receiver.connected
    assert run_task is not None
    assert run_task.done()
    with pytest.raises(NotConnectedError):
        receiver.send("PWR01")
    assert receiver._refresh_handle is None


async def test_stop_while_connecting_and_sleeping(make_receiver) -> None:
    receiver = await make_receiver(_closed_port())
    await receiver.start()
    await asyncio.sleep(0.02)
    await receiver.stop()
    assert receiver._run_task is None


async def test_start_twice_does_not_duplicate(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver)
    await receiver.start()
    await asyncio.sleep(0.05)
    assert fake_receiver.connections == 1


async def test_custom_create_task(fake_receiver, make_receiver) -> None:
    names: list[str] = []

    def _create(coro, name):
        names.append(name)
        return asyncio.create_task(coro, name=name)

    receiver = await _connected(make_receiver, fake_receiver, create_task=_create)
    assert receiver.connected
    assert len(names) == 1


async def test_keepalive_sends_power_query(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver, keepalive_interval=0.05)
    await _until(lambda: len(receiver.state) >= 5)
    fake_receiver.commands.clear()
    await _until(lambda: "PWRQSTN" in fake_receiver.commands)
    assert receiver.connected


async def test_dead_connection_detected(fake_receiver, make_receiver) -> None:
    receiver = await _connected(make_receiver, fake_receiver, keepalive_interval=0.03)
    await _until(lambda: len(receiver.state) >= 5)
    fake_receiver.silent = True
    await _until(lambda: receiver.stats["disconnects"] >= 1)
    assert "stopped responding" in receiver.stats["last_error"]


async def test_iscp_protocol(fake_receiver_factory, make_receiver) -> None:
    fake = await fake_receiver_factory("iscp")
    assert await async_probe(HOST, fake.port, "iscp", timeout=2.0) == "01"
    receiver = await _connected(make_receiver, fake, "iscp")
    await _until(lambda: len(receiver.state) >= 5)
    receiver.send("SLI03")
    await _until(lambda: receiver.state.get("SLI") == "03")
    assert await receiver.query("MVL", timeout=2.0) == "23"
