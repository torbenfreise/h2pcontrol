"""Shot persistence, decoupled from the run loop.

Saving used to block acquisition: the engine awaited ``sink.save_shot`` before
starting the next shot, so every millisecond of HDF5 append and flush was dead
time in the shot period.  A :class:`ShotWriter` breaks that coupling — the
engine hands a frame off and moves on, and the write overlaps the next shot's
acquisition.

Two implementations share the interface:

``ProcessWriter``
    The sink lives in a separate process.  Frames cross a bounded
    ``multiprocessing`` queue and the child owns the HDF5 handle end to end, so
    pytables' GIL-bound append leaves this interpreter entirely.  The cost is
    pickling each frame.  This is what the engine uses.

``InProcessWriter``
    One writer task drains a bounded ``asyncio`` queue into a thread executor.
    It overlaps the write with acquisition without a process boundary, so a
    sink that cannot be pickled (tests, in-memory sinks) still works — but a
    large write still steals the GIL from the run loop.

Both preserve the guarantees the serial save had:

* **One writer, in order.** The sink is a stateful single-writer HDF5 handle
  whose ``/data`` schema freezes on the first shot; concurrent or out-of-order
  writes would corrupt it.
* **Bounded buffer.** ``save`` blocks once ``maxsize`` shots are still
  unwritten, so a slow disk throttles acquisition instead of growing memory
  without limit.
* **The first error surfaces.** It is re-raised from ``save``/``flush`` so a
  failed write fails the run, and the sink is closed either way.
* **Flush before close.** ``flush`` returns only once the writer is idle, so
  ``aclose`` closes the sink without racing a write.

One consequence of the hand-off: a write error surfaces up to one shot later
than it did serially, because the next ``save`` (or the closing ``flush``) is
what sees it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing as mp
import queue
import signal
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import connection as mp_connection
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import pandas as pd

from .events import RunId
from .spec import RunRequest
from .store import RunSchema

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess
    from multiprocessing.queues import Queue

logger = logging.getLogger(__name__)


class ResultSink(Protocol):
    path: Path

    def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None: ...
    def close(self) -> None: ...


# type aliases so the engine's function signatures stay readable
type SinkFactory = Callable[[RunRequest, RunId, RunSchema], ResultSink]


class WriterError(RuntimeError):
    """A shot could not be persisted."""


class ShotWriter(Protocol):
    """Owns one run's sink and persists shots off the run loop."""

    path: Path | None

    async def open(self) -> Path:
        """Create the sink and start the writer; returns the result file path."""
        ...

    async def save(self, shot_idx: int, frame: pd.DataFrame) -> None:
        """Hand a shot to the writer, blocking while the buffer is full."""
        ...

    async def flush(self) -> None:
        """Wait for queued writes to land, re-raising the first write error."""
        ...

    async def aclose(self) -> None:
        """Close the sink and release the writer's resources."""
        ...


type WriterFactory = Callable[[SinkFactory, RunRequest, RunId, RunSchema], ShotWriter]


class InProcessWriter:
    """Writes shots from a background task in this process.

    Useful where the sink cannot cross a process boundary — it is constructed
    here and stays reachable to the caller.
    """

    def __init__(
        self,
        sink_factory: SinkFactory,
        request: RunRequest,
        run_id: RunId,
        schema: RunSchema,
        *,
        maxsize: int = 4,
    ) -> None:
        self._sink_factory = sink_factory
        self._args = (request, run_id, schema)
        self._maxsize = maxsize
        self.path: Path | None = None
        self._sink: ResultSink | None = None
        self._queue: asyncio.Queue[tuple[int, pd.DataFrame]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._error: BaseException | None = None

    async def open(self) -> Path:
        loop = asyncio.get_running_loop()
        sink = await loop.run_in_executor(None, self._sink_factory, *self._args)
        shots: asyncio.Queue[tuple[int, pd.DataFrame]] = asyncio.Queue(self._maxsize)
        self._sink = sink
        self._queue = shots
        self._task = loop.create_task(self._drain(loop, sink, shots))
        self.path = sink.path
        return sink.path

    async def _drain(
        self,
        loop: asyncio.AbstractEventLoop,
        sink: ResultSink,
        shots: asyncio.Queue[tuple[int, pd.DataFrame]],
    ) -> None:
        while True:
            shot_idx, frame = await shots.get()
            try:
                # Once a write has failed, keep draining without saving so the
                # queue empties (producers unblock) and flush() can join.
                if self._error is None:
                    await loop.run_in_executor(None, sink.save_shot, shot_idx, frame)
            except Exception as exc:  # surfaced to the run via save()/flush()
                self._error = exc
            finally:
                shots.task_done()

    async def save(self, shot_idx: int, frame: pd.DataFrame) -> None:
        if self._error is not None:
            raise self._error
        assert self._queue is not None, "save() before open()"
        await self._queue.put((shot_idx, frame))

    async def flush(self) -> None:
        if self._queue is None:
            return
        await self._queue.join()  # all queued writes done; writer idle on get()
        if self._error is not None:
            raise self._error

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._sink is not None:
            sink, self._sink = self._sink, None
            await asyncio.get_running_loop().run_in_executor(None, sink.close)


# Parent -> child, on the shot queue.
_SHOT = "shot"
_FLUSH = "flush"
_CLOSE = "close"

# Child -> parent, on the status pipe.
_READY = "ready"
_FLUSHED = "flushed"
_CLOSED = "closed"
_ERROR = "error"

# Which step of the child's life an error came from, so the parent can tell a
# failed write (fails the run) from a failed close (logged).
_OPEN_STAGE = "open"
_SAVE_STAGE = "save"
_CLOSE_STAGE = "close"

# How often a blocked enqueue re-checks that the child is still alive.
_PUT_POLL_S = 0.5
# How long to wait for the child to acknowledge close / exit before killing it.
_SHUTDOWN_S = 30.0


def _send_error(status: mp_connection.Connection, stage: str, exc: BaseException) -> None:
    # Exceptions are sent as text: an arbitrary sink's exception type need not
    # be picklable, and the traceback never is.
    status.send((_ERROR, (stage, f"{type(exc).__name__}: {exc}", traceback.format_exc())))


def _writer_main(
    status: mp_connection.Connection,
    shots: Queue[tuple[str, Any]],
    sink_factory: SinkFactory,
    request: RunRequest,
    run_id: RunId,
    schema: RunSchema,
) -> None:
    """Entry point of the writer process: own the sink, drain shots, reply.

    This runs in a fresh interpreter, so everything it needs arrives by pickle —
    which is why ``sink_factory`` has to be a module-level picklable callable
    rather than a closure or a bound method.
    """
    # The parent drives this process's lifecycle. A Ctrl-C in the shared
    # terminal must not kill the writer mid-run and truncate the file.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        sink = sink_factory(request, run_id, schema)
    except BaseException as exc:
        _send_error(status, _OPEN_STAGE, exc)
        status.close()
        return

    status.send((_READY, str(sink.path)))
    failed = False
    try:
        while True:
            kind, payload = shots.get()
            if kind == _SHOT:
                # After a failure keep draining without writing, so the parent's
                # bounded put() never wedges and the flush barrier still answers.
                if failed:
                    continue
                shot_idx, frame = payload
                try:
                    sink.save_shot(shot_idx, frame)
                except Exception as exc:
                    failed = True
                    _send_error(status, _SAVE_STAGE, exc)
            elif kind == _FLUSH:
                # The queue is FIFO, so reaching this marker means every shot
                # queued before it has been written.
                status.send((_FLUSHED, None))
            elif kind == _CLOSE:
                try:
                    sink.close()
                except Exception as exc:
                    _send_error(status, _CLOSE_STAGE, exc)
                status.send((_CLOSED, None))
                return
    finally:
        status.close()


class ProcessWriter:
    """Writes shots in a separate process.

    The sink is built in the child, so the whole HDF5 stack runs off this
    interpreter's GIL; frames cross as pickles over a bounded queue and the
    child answers on a status pipe.  A background thread pumps that pipe onto
    the event loop, watching the process sentinel alongside it so a child that
    dies without a word still wakes whoever is waiting.
    """

    def __init__(
        self,
        sink_factory: SinkFactory,
        request: RunRequest,
        run_id: RunId,
        schema: RunSchema,
        *,
        maxsize: int = 4,
    ) -> None:
        self._ctx = mp.get_context("spawn")
        self._args = (sink_factory, request, run_id, schema)
        self._maxsize = maxsize
        self.path: Path | None = None

        self._proc: BaseProcess | None = None
        self._shots: Queue[tuple[str, Any]] | None = None
        self._status: mp_connection.Connection | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pump: threading.Thread | None = None
        # A single thread serialises the blocking queue puts, so shots reach the
        # child in the order the run loop produced them.
        self._io = ThreadPoolExecutor(1, thread_name_prefix="shot-writer")

        self._waiters: dict[str, asyncio.Future[None]] = {}
        self._arrived: set[str] = set()
        self._errors: dict[str, WriterError] = {}
        self._exited = False
        self._closed = False

    async def open(self) -> Path:
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._shots = self._ctx.Queue(self._maxsize)
        status, child_status = self._ctx.Pipe(duplex=False)
        self._status = status
        self._proc = self._ctx.Process(
            target=_writer_main,
            args=(child_status, self._shots, *self._args),
            name="h2p-shot-writer",
            daemon=True,
        )
        try:
            # Spawning boots a fresh interpreter; keep that off the event loop.
            await loop.run_in_executor(self._io, self._proc.start)
        finally:
            child_status.close()  # from here on only the child holds the write end

        ready = self._expect(_READY)
        self._pump = threading.Thread(
            target=self._pump_status, name="h2p-shot-writer-status", daemon=True
        )
        self._pump.start()
        await ready

        assert self.path is not None, "child reported ready without a path"
        return self.path

    async def save(self, shot_idx: int, frame: pd.DataFrame) -> None:
        self._raise_pending()
        await self._enqueue((_SHOT, (shot_idx, frame)))

    async def flush(self) -> None:
        if self._proc is None:
            return
        if not self._exited:
            flushed = self._expect(_FLUSHED)
            await self._enqueue((_FLUSH, None))
            await flushed
        self._raise_pending()

    async def aclose(self) -> None:
        if self._proc is None:
            self._io.shutdown(wait=False)
            return
        if not self._exited:
            closed = self._expect(_CLOSED)
            try:
                await self._enqueue((_CLOSE, None))
                await asyncio.wait_for(closed, _SHUTDOWN_S)
            except (WriterError, TimeoutError):
                logger.warning("writer process did not confirm close; terminating it")
        assert self._loop is not None
        await self._loop.run_in_executor(self._io, self._reap)
        self._io.shutdown(wait=False)
        error = self._errors.get(_CLOSE_STAGE)
        if error is not None:
            raise error

    # -- parent-side plumbing -------------------------------------------------

    async def _enqueue(self, item: tuple[str, Any]) -> None:
        assert self._loop is not None, "writer not open"
        await self._loop.run_in_executor(self._io, self._put, item)

    def _put(self, item: tuple[str, Any]) -> None:
        """Blocking enqueue with backpressure, giving up if the child is gone.

        The bounded queue is what throttles acquisition when the disk falls
        behind; the liveness poll is what stops that throttle from becoming a
        deadlock once nothing is draining the queue any more.
        """
        assert self._shots is not None and self._proc is not None
        while True:
            try:
                self._shots.put(item, timeout=_PUT_POLL_S)
                return
            except queue.Full:
                if not self._proc.is_alive():
                    raise WriterError("writer process exited; the shot was not queued") from None

    def _raise_pending(self) -> None:
        """Re-raise a write/open failure, or an unexplained death of the child."""
        error = self._errors.get(_SAVE_STAGE) or self._errors.get(_OPEN_STAGE)
        if error is not None:
            raise error
        if self._exited and not self._closed:
            assert self._proc is not None
            raise WriterError(
                f"writer process exited unexpectedly (exit code {self._proc.exitcode})"
            )

    def _pump_status(self) -> None:
        """Forward the child's replies onto the event loop until it is gone."""
        assert self._proc is not None and self._status is not None
        while True:
            ready = mp_connection.wait([self._status, self._proc.sentinel])
            if self._status not in ready:
                break  # the process is gone and left nothing to read
            try:
                message = self._status.recv()
            except (EOFError, OSError):
                break
            self._post(self._on_status, message)
        self._post(self._on_exited)

    def _post(self, fn: Callable[..., None], *args: Any) -> None:
        assert self._loop is not None
        # A closed loop means the run is over either way.
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(fn, *args)

    def _on_status(self, message: tuple[str, Any]) -> None:
        kind, payload = message
        if kind == _ERROR:
            stage, detail, tb = payload
            logger.error("shot writer failed during %s:\n%s", stage, tb)
            error = self._errors.setdefault(stage, WriterError(detail))
            if stage == _OPEN_STAGE:
                self._fail(_READY, error)  # the sink was never created
            return
        if kind == _READY:
            self.path = Path(payload)
        elif kind == _CLOSED:
            self._closed = True
        self._resolve(kind)

    def _on_exited(self) -> None:
        assert self._proc is not None
        self._exited = True
        error = WriterError(f"writer process exited unexpectedly (exit code {self._proc.exitcode})")
        for kind in list(self._waiters):
            self._fail(kind, error)

    def _expect(self, kind: str) -> asyncio.Future[None]:
        """A future resolved by the child's next *kind* reply (or its death)."""
        assert self._loop is not None
        future: asyncio.Future[None] = self._loop.create_future()
        if kind in self._arrived:
            self._arrived.discard(kind)
            future.set_result(None)
        else:
            self._waiters[kind] = future
        return future

    def _resolve(self, kind: str) -> None:
        future = self._waiters.pop(kind, None)
        if future is None:
            self._arrived.add(kind)  # replied before anyone asked
        elif not future.done():
            future.set_result(None)

    def _fail(self, kind: str, error: WriterError) -> None:
        future = self._waiters.pop(kind, None)
        if future is not None and not future.done():
            future.set_exception(error)

    def _reap(self) -> None:
        """Join the child and tear down the queue, pipe and pump thread."""
        assert self._proc is not None and self._shots is not None and self._status is not None
        self._proc.join(_SHUTDOWN_S)
        if self._proc.is_alive():
            logger.warning("writer process still running after close; terminating it")
            self._proc.terminate()
            self._proc.join(_SHUTDOWN_S)
        # Anything still buffered is undeliverable — the child either drained
        # everything before acknowledging close, or is dead.
        self._shots.cancel_join_thread()
        self._shots.close()
        if self._pump is not None:
            self._pump.join(_SHUTDOWN_S)
        self._status.close()
