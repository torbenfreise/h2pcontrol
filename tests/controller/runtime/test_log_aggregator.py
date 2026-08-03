from __future__ import annotations

import asyncio
import logging
import sys
import threading
from collections.abc import AsyncIterator, Callable
from typing import cast

import pytest
from h2pcontrol.manager.v1.manager_pb2 import LogEntry
from h2pcontrol.sdk.client import Client

from h2pcontrol.controller.runtime import log_aggregator as agg_mod
from h2pcontrol.controller.runtime.log_aggregator import (
    LogAggregator,
    LogLine,
    line_from_entry,
    line_from_record,
)


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Snapshot/restore root logger handlers between tests."""
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _entry(
    *,
    service: str = "svc",
    level: int = 200,
    message: str = "hello",
    attrs: dict[str, str] | None = None,
) -> LogEntry:
    entry = LogEntry(service_name=service, message=message)
    entry.level = level  # type: ignore[assignment]
    entry.timestamp.GetCurrentTime()
    for key, value in (attrs or {}).items():
        pair = entry.attrs.add()
        pair.key = key
        pair.value.string_value = value
    return entry


def _provider(client: FakeClient) -> Callable[[], Client]:
    return cast("Callable[[], Client]", lambda: client)


class TestMapping:
    @pytest.mark.parametrize(
        ("proto_level", "expected"),
        [(100, logging.DEBUG), (200, logging.INFO), (300, logging.WARNING), (400, logging.ERROR)],
    )
    def test_known_levels(self, proto_level: int, expected: int):
        rec = line_from_entry(_entry(level=proto_level))
        assert rec.level == expected

    def test_unknown_level_falls_back_to_info(self):
        rec = line_from_entry(_entry(level=999))
        assert rec.level == logging.INFO

    def test_service_name_becomes_source(self):
        rec = line_from_entry(_entry(service="picoscope"))
        assert rec.source == "picoscope"

    def test_attrs_appended_to_message(self):
        rec = line_from_entry(_entry(message="connected", attrs={"port": "5000"}))
        assert rec.message == "connected port=5000"

    def test_attrs_only_when_message_empty(self):
        rec = line_from_entry(_entry(message="", attrs={"port": "5000"}))
        assert rec.message == "port=5000"

    def test_timestamp_is_aware_utc(self):
        rec = line_from_entry(_entry())
        assert rec.timestamp.tzinfo is not None
        assert rec.timestamp.utcoffset() is not None


class TestAttribution:
    def test_experiment_logger_maps_to_name(self):
        record = logging.LogRecord("experiment.Rabi", logging.INFO, "f", 1, "msg", None, None)
        assert line_from_record(record).source == "Rabi"

    def test_module_logger_maps_to_h2pcontrol(self):
        record = logging.LogRecord(
            "h2pcontrol.controller.foo", logging.WARNING, "f", 1, "msg", None, None
        )
        mapped = line_from_record(record)
        assert mapped.source == "h2pcontrol"
        assert mapped.level == logging.WARNING

    def test_exc_info_appended_to_message(self):
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                "experiment.Foo", logging.ERROR, "f", 1, "failed", None, sys.exc_info()
            )
        message = line_from_record(record).message
        assert message.startswith("failed")
        assert "ValueError: boom" in message
        assert "Traceback" in message


class FakeClient:
    """Fake SDK client whose stream_logs is a controllable async generator."""

    def __init__(self, batches: list[list[LogEntry]], *, fail_first: bool = False) -> None:
        self._batches = batches
        self._fail_first = fail_first
        self.calls: list[dict] = []

    async def stream_logs(self, follow: bool = True, tail: int = -1) -> AsyncIterator[LogEntry]:
        call_no = len(self.calls)
        self.calls.append({"follow": follow, "tail": tail})
        if self._fail_first and call_no == 0:
            raise RuntimeError("stream boom")
        batch = self._batches[min(call_no, len(self._batches) - 1)]
        for entry in batch:
            yield entry
        # keep the stream open so the loop does not spin reconnecting
        await asyncio.Event().wait()


async def _collect(agg: LogAggregator, n: int, timeout: float = 2.0) -> list[LogLine]:
    got: list[LogLine] = []
    done = asyncio.get_running_loop().create_future()

    def cb(rec: LogLine) -> None:
        got.append(rec)
        if len(got) >= n and not done.done():
            done.set_result(None)

    agg.subscribe(cb)
    agg.start()
    try:
        await asyncio.wait_for(done, timeout)
    finally:
        await agg.aclose()
    return got


@pytest.mark.asyncio
class TestManagerStream:
    async def test_delivers_entries(self):
        client = FakeClient([[_entry(message="a"), _entry(message="b")]])
        agg = LogAggregator(client_provider=_provider(client))
        got = await _collect(agg, 2)
        assert [r.message for r in got] == ["a", "b"]
        assert client.calls[0] == {"follow": True, "tail": 0}

    async def test_retries_after_error(self):
        client = FakeClient([[], [_entry(message="after-retry")]], fail_first=True)
        agg = LogAggregator(client_provider=_provider(client), backoff=0)
        got = await _collect(agg, 1)
        assert got[0].message == "after-retry"
        # first call failed, second call streamed → two connect attempts
        assert len(client.calls) == 2
        assert all(c["tail"] == 0 for c in client.calls)


@pytest.mark.asyncio
class TestLocalFeed:
    async def test_marshals_from_executor_thread_to_loop_thread(self):
        loop = asyncio.get_running_loop()
        client = FakeClient([[]])  # empty, then blocks
        agg = LogAggregator(client_provider=_provider(client))

        loop_thread = threading.get_ident()
        seen: dict[str, int] = {}
        done = loop.create_future()

        def cb(rec: LogLine) -> None:
            seen["thread"] = threading.get_ident()
            seen["level"] = rec.level
            if not done.done():
                done.set_result(None)

        agg.subscribe(cb)
        agg.start()
        try:
            # log from a worker thread, as save_shot does
            await loop.run_in_executor(
                None, logging.getLogger("experiment.Foo").warning, "from thread"
            )
            await asyncio.wait_for(done, 2.0)
        finally:
            await agg.aclose()

        assert seen["thread"] == loop_thread
        assert seen["level"] == logging.WARNING


@pytest.mark.asyncio
class TestLifecycle:
    async def test_aclose_removes_handler_and_cancels_task(self):
        root = logging.getLogger()
        before = len(root.handlers)
        client = FakeClient([[]])
        agg = LogAggregator(client_provider=_provider(client))
        agg.start()
        assert len(root.handlers) == before + 1
        assert agg._task is not None
        task = agg._task
        await agg.aclose()
        assert len(root.handlers) == before
        assert task.cancelled() or task.done()


@pytest.mark.asyncio
class TestLocalDebug:
    async def test_debug_reaches_subscribers_when_root_enables_it(self):
        # app.py runs the root logger at DEBUG, so  experiment DEBUG
        # records  should reach the dock
        logging.getLogger().setLevel(logging.DEBUG)
        agg = LogAggregator(client_provider=_provider(FakeClient([[]])))
        got: list[LogLine] = []
        done = asyncio.get_running_loop().create_future()

        def cb(rec: LogLine) -> None:
            got.append(rec)
            if not done.done():
                done.set_result(None)

        agg.subscribe(cb)
        agg.start()
        try:
            logging.getLogger("experiment.Foo").debug("dbg")
            await asyncio.wait_for(done, 2.0)
        finally:
            await agg.aclose()
        assert got[0].level == logging.DEBUG

    async def test_own_module_logs_are_not_delivered(self):
        # A subscriber error is logged by _emit; that log must not feed back in.
        agg = LogAggregator(client_provider=_provider(FakeClient([[]])))
        got: list[LogLine] = []
        agg.subscribe(got.append)
        agg.start()
        try:
            logging.getLogger(agg_mod.__name__).error("internal")
            await asyncio.sleep(0.05)
        finally:
            await agg.aclose()
        assert got == []
