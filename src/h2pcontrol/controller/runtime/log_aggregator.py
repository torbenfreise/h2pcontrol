"""Aggregates logs from the manager and the h2pcontrol process into one subscriber stream."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from h2pcontrol.manager.v1.manager_pb2 import AttrValue, LogEntry

    from .session import ClientProvider

logger = logging.getLogger(__name__)

_PROTO_LEVELS = {100: logging.DEBUG, 200: logging.INFO, 300: logging.WARNING, 400: logging.ERROR}

_EXPERIMENT_PREFIX = "experiment."

_RECONNECT_BACKOFF = 5.0


@dataclass(frozen=True)
class LogLine:
    source: str  # "h2pcontrol" | experiment name | service name
    level: int
    timestamp: datetime
    message: str


def _attr_value_str(value: AttrValue) -> str:
    """Convert the set value of a 'oneof' as a string."""
    field = value.WhichOneof("value")
    return "" if field is None else str(getattr(value, field))


def line_from_entry(entry: LogEntry) -> LogLine:
    """Map a manager ``LogEntry`` to a ``LogLine``.
    Attrs are appended to the message as ``key=value`` pairs.
    """
    level = _PROTO_LEVELS.get(entry.level, logging.INFO)
    message = entry.message
    if entry.attrs:
        pairs = " ".join(f"{a.key}={_attr_value_str(a.value)}" for a in entry.attrs)
        message = f"{message} {pairs}" if message else pairs
    timestamp = entry.timestamp.ToDatetime(tzinfo=UTC)
    return LogLine(
        source=entry.service_name,
        level=level,
        timestamp=timestamp,
        message=message,
    )


def line_from_record(record: logging.LogRecord) -> LogLine:
    """Map a python ``logging.LogRecord`` to a ``LogLine``.

    If the logger name matches ``experiment.<name>``, source=<name>,
    else source=h2pcontrol.
    """
    if record.name.startswith(_EXPERIMENT_PREFIX):
        source = record.name[len(_EXPERIMENT_PREFIX) :]
    else:
        source = "h2pcontrol"
    message = record.getMessage()
    if record.exc_info:
        message = f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
    return LogLine(
        source=source,
        level=record.levelno,
        timestamp=datetime.fromtimestamp(record.created, tz=UTC),
        message=message,
    )


class _LocalLogHandler(logging.Handler):
    """Root-logger handler that forwards logs to the aggregator."""

    def __init__(self, loop: asyncio.AbstractEventLoop, sink: Callable[[LogLine], None]) -> None:
        super().__init__()
        self._loop = loop
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        # Ignore this module's own logs to prevent a loop
        if record.name == __name__:
            return
        try:
            mapped = line_from_record(record)
        except Exception:
            self.handleError(record)
            return
        self._loop.call_soon_threadsafe(self._sink, mapped)


class LogAggregator:
    """Merges the manager and local log feeds into one ``subscribe`` stream."""

    def __init__(
        self,
        client_provider: ClientProvider,
        *,
        backoff: float = _RECONNECT_BACKOFF,
    ) -> None:
        self._client_provider = client_provider
        self._backoff = backoff
        self._subscribers: list[Callable[[LogLine], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handler: _LocalLogHandler | None = None
        self._task: asyncio.Task[None] | None = None

    def subscribe(self, callback: Callable[[LogLine], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[LogLine], None]) -> None:
        self._subscribers.remove(callback)

    def _emit(self, record: LogLine) -> None:
        for cb in list(self._subscribers):
            try:
                cb(record)
            except Exception:
                logger.exception("Subscriber raised during log callback")

    def start(self) -> None:
        """Spawn the manager task and install the local handler."""
        self._loop = asyncio.get_running_loop()
        self._handler = _LocalLogHandler(self._loop, self._emit)
        logging.getLogger().addHandler(self._handler)
        self._task = self._loop.create_task(self._manager_loop())

    async def aclose(self) -> None:
        """Cancel the manager task and remove the local handler."""
        if self._handler is not None:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _manager_loop(self) -> None:
        """Stream manager logs, retrying on error.

        ``tail=0`` on every (re)connect so no history.
        """
        while True:
            try:
                client = self._client_provider()
                async for entry in client.stream_logs(follow=True, tail=0):
                    self._emit(line_from_entry(entry))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Manager log stream error; retrying", exc_info=True)
                await asyncio.sleep(self._backoff)
