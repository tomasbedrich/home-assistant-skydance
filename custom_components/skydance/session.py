"""Serialized, self-healing transport to the Skydance Wi-Fi relay."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from skydance.protocol import HEAD, TAIL, Command, PingCommand, State

from .const import (
    CLOSE_TIMEOUT,
    COMMAND_ATTEMPTS,
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    PAUSE_BETWEEN_WRITES,
    RETRY_PAUSE,
)

_LOGGER = logging.getLogger(__name__)

READ_LIMIT = 4096
"""Maximum size of a single frame read from the relay."""


class SkydanceError(Exception):
    """Raised when the relay is unreachable or does not answer."""


class SkydanceClient:
    """A connection to a relay which serializes request/response exchanges.

    A relay answers every command with a frame carrying the same frame number.
    It is however a cheap Wi-Fi controller: it may silently drop a TCP session,
    stall in the middle of an exchange or answer late. Therefore every
    transaction is bounded by a timeout and any failure drops the socket, so
    that the next transaction reconnects. This way the integration recovers on
    its own instead of hanging until it is reloaded by hand.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_timeout: float = CONNECT_TIMEOUT,
        command_timeout: float = COMMAND_TIMEOUT,
        pause_between_writes: float = PAUSE_BETWEEN_WRITES,
        attempts: int = COMMAND_ATTEMPTS,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout
        self._pause_between_writes = pause_between_writes
        self._attempts = attempts

        self._state = State()
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def async_ping(self) -> None:
        """Check that the relay answers commands."""
        await self.async_request(PingCommand)

    async def async_request(self, factory: Callable[[State], Command]) -> bytes:
        """Send a command and return the raw frame it was answered with.

        `factory` is called under the lock with the connection state, so frame
        numbers of concurrent callers can never collide and the command is
        re-created (with a fresh frame number) when a retry is needed.
        """
        async with self._lock:
            return await self._async_transaction(factory)

    async def async_close(self) -> None:
        """Close the connection, if any."""
        async with self._lock:
            await self._async_close()

    async def _async_transaction(self, factory: Callable[[State], Command]) -> bytes:
        last_error: Exception | None = None

        for attempt in range(1, self._attempts + 1):
            try:
                return await self._async_transaction_once(factory)
            except (
                TimeoutError,
                OSError,
                EOFError,
                asyncio.LimitOverrunError,
            ) as err:
                last_error = err
                _LOGGER.debug(
                    "Communication with %s:%s failed (attempt %d/%d): %r",
                    self._host,
                    self._port,
                    attempt,
                    self._attempts,
                    err,
                )
                # The session cannot be trusted anymore, start from scratch.
                await self._async_close()
                if attempt < self._attempts:
                    await asyncio.sleep(RETRY_PAUSE)

        raise SkydanceError(
            f"no answer from {self._host}:{self._port} ({last_error!r})"
        ) from last_error

    async def _async_transaction_once(
        self, factory: Callable[[State], Command]
    ) -> bytes:
        await self._async_ensure_connection()

        command = factory(self._state)
        frame = command.raw
        expected_frame = self._state.frame_number

        _LOGGER.debug("Sending: %s", frame.hex(" "))
        async with asyncio.timeout(self._command_timeout):
            self._writer.write(frame)  # type: ignore[union-attr]
            await self._writer.drain()  # type: ignore[union-attr]
            self._state.increment_frame_number()
            response = await self._async_read_frame(expected_frame)

        await asyncio.sleep(self._pause_between_writes)
        return response

    async def _async_read_frame(self, expected_frame: bytes) -> bytes:
        """Read frames until the one answering `expected_frame` arrives."""
        while True:
            raw = await self._reader.readuntil(TAIL)  # type: ignore[union-attr]
            _LOGGER.debug("Received: %s", raw.hex(" "))

            if len(raw) < len(HEAD) + 2 or not raw.startswith(HEAD):
                _LOGGER.debug("Discarding malformed frame: %s", raw.hex(" "))
                continue

            if raw[len(HEAD) : len(HEAD) + 1] != expected_frame:
                # The relay broadcasts answers to every connected client, so a
                # late or foreign frame may show up here. It is not ours.
                _LOGGER.debug("Discarding frame of another request: %s", raw.hex(" "))
                continue

            return raw

    async def _async_ensure_connection(self) -> None:
        if (
            self._writer is not None
            and not self._writer.is_closing()
            and self._reader is not None
            and not self._reader.at_eof()
        ):
            return

        await self._async_close()

        _LOGGER.debug("Opening connection to %s:%s", self._host, self._port)
        async with asyncio.timeout(self._connect_timeout):
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port, limit=READ_LIMIT
            )

    async def _async_close(self) -> None:
        writer, self._writer = self._writer, None
        self._reader = None

        if writer is None:
            return

        _LOGGER.debug("Closing connection to %s:%s", self._host, self._port)
        writer.close()
        with contextlib.suppress(Exception):
            async with asyncio.timeout(CLOSE_TIMEOUT):
                await writer.wait_closed()
