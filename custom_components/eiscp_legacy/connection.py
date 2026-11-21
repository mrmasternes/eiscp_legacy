"""Asyncio connection handling for eISCP / ISCP receivers.

This module has no Home Assistant imports so it can be unit tested on its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import contextlib
from datetime import UTC, datetime
import logging
from typing import Any

from .protocol import PROTOCOL_EISCP, Message, encode, make_decoder

_LOGGER = logging.getLogger(__name__)

DEFAULT_REFRESH_COMMANDS = ("PWR", "MVL", "AMT", "SLI", "LMD")

# Module level so tests can shorten them.
RECONNECT_DELAY = 1.0
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0
MAX_MISSED_KEEPALIVES = 3
KEEPALIVE_COMMAND = "PWRQSTN"


class NotConnectedError(Exception):
    """Raised when an operation needs a connection that is not up."""


class CannotConnect(Exception):
    """Raised when the TCP connection could not be established."""


class NoResponse(Exception):
    """Raised when connected but the receiver did not answer."""


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    """Close a stream writer, ignoring errors."""
    writer.close()
    with contextlib.suppress(OSError, TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), 1.0)


async def async_probe(
    host: str,
    port: int,
    protocol: str,
    timeout: float = 5.0,  # noqa: ASYNC109
) -> str:
    """Connect once, send ``PWRQSTN`` and return the ``PWR`` value (``00``/``01``).

    Raises CannotConnect if the TCP connection fails and NoResponse if the
    receiver does not answer in time or closes the connection.
    """
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError) as err:
        raise CannotConnect(str(err) or type(err).__name__) from err

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        writer.write(encode(protocol, KEEPALIVE_COMMAND))
        await asyncio.wait_for(writer.drain(), timeout)
        decoder = make_decoder(protocol)
        while (remaining := deadline - loop.time()) > 0:
            data = await asyncio.wait_for(reader.read(4096), remaining)
            if not data:
                raise NoResponse("Connection closed by receiver")
            for message in decoder.feed(data):
                if message.command == "PWR":
                    return message.value
        raise NoResponse("No power status reply from receiver")
    except TimeoutError as err:
        raise NoResponse("No power status reply from receiver") from err
    except OSError as err:
        raise NoResponse(str(err) or type(err).__name__) from err
    finally:
        await _close_writer(writer)


class Receiver:
    """A persistent, self reconnecting connection to one receiver."""

    def __init__(
        self,
        host: str,
        port: int,
        protocol: str = PROTOCOL_EISCP,
        *,
        command_interval: float = 0.1,
        keepalive_interval: float = 60.0,
        connect_timeout: float = 10.0,
        power_on_refresh_delay: float = 2.0,
        refresh_commands: tuple[str, ...] = DEFAULT_REFRESH_COMMANDS,
        create_task: Callable[[Coroutine[Any, Any, Any], str], asyncio.Task] | None = None,
    ) -> None:
        """Initialize the receiver connection (does not connect)."""
        self.host = host
        self.port = port
        self.protocol = protocol
        self.state: dict[str, str] = {}
        self.stats: dict[str, Any] = {
            "connects": 0,
            "disconnects": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "last_error": None,
            "last_connected": None,
        }
        self._command_interval = command_interval
        self._keepalive_interval = keepalive_interval
        self._connect_timeout = connect_timeout
        self._power_on_refresh_delay = power_on_refresh_delay
        self._refresh_commands = refresh_commands
        self._create_task: Callable[[Coroutine[Any, Any, Any], str], asyncio.Task] = (
            create_task or self._default_create_task
        )
        self._run_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[str] | None = None
        self._connected = False
        self._connected_event = asyncio.Event()
        self._unavailable_logged = False
        self._refresh_handle: asyncio.TimerHandle | None = None
        self._pending: dict[str, list[asyncio.Future[str]]] = {}
        self._message_listeners: list[Callable[[Message], None]] = []
        self._connection_listeners: list[Callable[[bool], None]] = []

    @staticmethod
    def _default_create_task(coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        """Create a task with asyncio."""
        return asyncio.create_task(coro, name=name)

    @property
    def connected(self) -> bool:
        """Return True while a session is established."""
        return self._connected

    def add_message_listener(self, cb: Callable[[Message], None]) -> Callable[[], None]:
        """Register a callback for every received message; returns a remove function."""
        self._message_listeners.append(cb)

        def _remove() -> None:
            if cb in self._message_listeners:
                self._message_listeners.remove(cb)

        return _remove

    def add_connection_listener(self, cb: Callable[[bool], None]) -> Callable[[], None]:
        """Register a callback for connection changes; returns a remove function."""
        self._connection_listeners.append(cb)

        def _remove() -> None:
            if cb in self._connection_listeners:
                self._connection_listeners.remove(cb)

        return _remove

    async def start(self) -> None:
        """Start the background connection loop and return immediately."""
        if self._run_task is not None and not self._run_task.done():
            return
        self._run_task = self._create_task(self._run(), f"eiscp_legacy {self.host}:{self.port}")

    async def wait_connected(self, timeout: float) -> bool:  # noqa: ASYNC109
        """Wait until connected; return False on timeout."""
        if self._connected:
            return True
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def stop(self) -> None:
        """Stop the connection loop and release everything. Safe to call repeatedly."""
        task, self._run_task = self._run_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._cancel_refresh()
        self._set_connected(False)
        self._fail_pending()

    def send(self, command: str) -> None:
        """Queue a command such as ``PWR01`` for sending."""
        if not self._connected or self._queue is None:
            raise NotConnectedError(f"Not connected to {self.host}:{self.port}")
        self._queue.put_nowait(command)

    def refresh(self) -> None:
        """Queue a query for each refresh command (no-op when not connected)."""
        if not self._connected or self._queue is None:
            return
        for command in self._refresh_commands:
            self._queue.put_nowait(f"{command}QSTN")

    async def query(self, command: str, timeout: float = 5.0) -> str:  # noqa: ASYNC109
        """Query a 3-letter command and return the value of the next reply."""
        if not self._connected:
            raise NotConnectedError(f"Not connected to {self.host}:{self.port}")
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        futures = self._pending.setdefault(command, [])
        futures.append(future)
        try:
            self.send(f"{command}QSTN")
            return await asyncio.wait_for(future, timeout)
        finally:
            if future in futures:
                futures.remove(future)
            if not futures and self._pending.get(command) is futures:
                del self._pending[command]

    # -- internals ---------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        """Update the connected flag and notify listeners on change."""
        if connected:
            self._connected_event.set()
        else:
            self._connected_event.clear()
        if connected == self._connected:
            return
        self._connected = connected
        for listener in list(self._connection_listeners):
            try:
                listener(connected)
            except Exception:
                _LOGGER.exception("Error in connection listener")

    def _fail_pending(self) -> None:
        """Fail all outstanding queries."""
        pending, self._pending = self._pending, {}
        for futures in pending.values():
            for future in futures:
                if not future.done():
                    future.set_exception(NotConnectedError("Connection lost"))

    def _cancel_refresh(self) -> None:
        """Cancel a scheduled power-on refresh."""
        if self._refresh_handle is not None:
            self._refresh_handle.cancel()
            self._refresh_handle = None

    def _delayed_refresh(self) -> None:
        """Run the scheduled refresh."""
        self._refresh_handle = None
        self.refresh()

    def _record_error(self, err: BaseException) -> None:
        """Remember the last error as text."""
        name = type(err).__name__
        self.stats["last_error"] = f"{name}: {err}" if str(err) else name

    async def _run(self) -> None:
        """Connect, run a session, reconnect; until cancelled."""
        backoff = INITIAL_BACKOFF
        while True:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), self._connect_timeout
                )
            except (OSError, TimeoutError) as err:
                self._record_error(err)
                if not self._unavailable_logged:
                    self._unavailable_logged = True
                    _LOGGER.warning(
                        "Cannot connect to receiver %s:%s: %s", self.host, self.port, err
                    )
                else:
                    _LOGGER.debug("Connect to %s:%s failed: %s", self.host, self.port, err)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

            backoff = INITIAL_BACKOFF
            self.stats["connects"] += 1
            self.stats["last_connected"] = datetime.now(UTC).isoformat()
            if self._unavailable_logged:
                self._unavailable_logged = False
                _LOGGER.info("Connection to receiver %s:%s restored", self.host, self.port)
            try:
                await self._session(reader, writer)
            except Exception as err:
                self._record_error(err)
                _LOGGER.debug("Session with %s:%s ended: %r", self.host, self.port, err)
            self.stats["disconnects"] += 1
            if not self._unavailable_logged:
                self._unavailable_logged = True
                _LOGGER.warning("Connection to receiver %s:%s lost", self.host, self.port)
            await asyncio.sleep(RECONNECT_DELAY)

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Run one connected session until it ends."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._queue = queue
        writer_task = asyncio.create_task(self._writer_loop(writer, queue))
        decoder = make_decoder(self.protocol)
        loop = asyncio.get_running_loop()
        try:
            self._set_connected(True)
            self.refresh()
            missed = 0
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(4096), self._keepalive_interval)
                except TimeoutError:
                    missed += 1
                    if missed >= MAX_MISSED_KEEPALIVES:
                        raise ConnectionError("Receiver stopped responding") from None
                    queue.put_nowait(KEEPALIVE_COMMAND)
                    continue
                if not data:
                    raise ConnectionError("Connection closed by receiver")
                missed = 0
                for message in decoder.feed(data):
                    self._handle_message(message, loop)
        finally:
            self._cancel_refresh()
            self._queue = None
            self._set_connected(False)
            self._fail_pending()
            writer_task.cancel()
            await asyncio.gather(writer_task, return_exceptions=True)
            await _close_writer(writer)

    async def _writer_loop(self, writer: asyncio.StreamWriter, queue: asyncio.Queue[str]) -> None:
        """Send queued commands, pacing them for slow receivers."""
        try:
            while True:
                command = await queue.get()
                try:
                    data = encode(self.protocol, command)
                except UnicodeEncodeError:
                    _LOGGER.warning("Dropping non-ASCII command %r", command)
                    continue
                writer.write(data)
                await writer.drain()
                self.stats["messages_sent"] += 1
                await asyncio.sleep(self._command_interval)
        except OSError as err:
            # Closing makes the reader see EOF so the session ends.
            _LOGGER.debug("Write to %s:%s failed: %r", self.host, self.port, err)
            writer.close()

    def _handle_message(self, message: Message, loop: asyncio.AbstractEventLoop) -> None:
        """Process one received message."""
        previous = self.state.get(message.command)
        self.state[message.command] = message.value
        self.stats["messages_received"] += 1
        for future in self._pending.pop(message.command, []):
            if not future.done():
                future.set_result(message.value)
        for listener in list(self._message_listeners):
            try:
                listener(message)
            except Exception:
                _LOGGER.exception("Error in message listener")
        if message.command == "PWR" and message.value == "01" and previous != "01":
            self._cancel_refresh()
            self._refresh_handle = loop.call_later(
                self._power_on_refresh_delay, self._delayed_refresh
            )
