"""
The engine manages a FIFO queue of RunRequests.  A lazy worker task drains
the queue one entry at a time.  Each entry runs as its own asyncio.Task so
that runs can be canceled independently of the worker.

Experiments are compile from ``request.source`` at dequeue. Imports from
the source resolve at execution time so are susceptible to enviroment changes
from queue time to execution time.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pandas as pd

from ..framework.experiment import Context, Experiment
from .events import (
    EngineEvent,
    EngineState,
    EntryState,
    QueueChanged,
    QueueEntry,
    RunFinished,
    RunId,
    RunQueued,
    RunStarted,
    ShotCompleted,
    StateChanged,
)
from .session import ClientProvider
from .spec import RunRequest

logger = logging.getLogger(__name__)

_TERMINAL = (
    EntryState.COMPLETED,
    EntryState.FAILED,
    EntryState.STOPPED,
    EntryState.CANCELLED,
)


class ResultSink(Protocol):
    path: Path

    def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None: ...
    def close(self) -> None: ...


# type aliases so Engine.__init__() has a nicer function signature
type SinkFactory = Callable[[RunRequest, RunId], ResultSink]
type Loader = Callable[[str, Path], type[Experiment]]


class _Entry:
    __slots__ = ("request", "run_id", "state")

    def __init__(self, run_id: RunId, request: RunRequest) -> None:
        self.run_id = run_id
        self.request = request
        self.state: EntryState = EntryState.QUEUED


class RunEngine:
    def __init__(
        self,
        client_provider: ClientProvider,
        sink_factory: SinkFactory,
        loader: Loader,
    ) -> None:
        self._client_provider = client_provider
        self._sink_factory = sink_factory
        self._loader = loader

        self._state = EngineState.IDLE
        self._entries: dict[RunId, _Entry] = {}
        self._pending: asyncio.Queue[RunId] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._current_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._subscribers: list[Callable[[EngineEvent], None]] = []

    def submit(self, request: RunRequest) -> RunId:
        """Enqueue a run request, returning the assigned RunId"""
        run_id = RunId(uuid.uuid4().hex)
        entry = _Entry(run_id, request)
        self._entries[run_id] = entry
        self._pending.put_nowait(run_id)

        self._emit(RunQueued(run_id=run_id, request=request))
        self._emit(self._queue_changed())

        # Start worker on first submit
        if self._worker is None:
            loop = asyncio.get_running_loop()
            self._worker = loop.create_task(self._worker_loop())

        return run_id

    def cancel(self, run_id: RunId) -> None:
        """Cancel a queued or running entry."""
        entry = self._entries.get(run_id)
        if entry is None:
            return
        if entry.state == EntryState.QUEUED:
            entry.state = EntryState.CANCELLED
            self._emit(self._queue_changed())
        elif entry.state == EntryState.RUNNING:
            self.stop_current()

    def stop_current(self, *, hard: bool = False) -> None:
        """Stop the currently running entry."""
        if self._current_task is None or self._current_task.done():
            return
        if hard:
            self._current_task.cancel()
        else:
            self._stop_event.set()
            self._set_state(EngineState.STOPPING)

    def clear_finished(self) -> None:
        """Remove terminal entries (completed/failed/stopped/cancelled) from history."""
        terminal = [rid for rid, e in self._entries.items() if e.state in _TERMINAL]
        if not terminal:
            return
        for rid in terminal:
            del self._entries[rid]
        self._emit(self._queue_changed())

    async def aclose(self) -> None:
        """Shut down the engine. Stops current run, cancels worker."""
        if self._worker is None:
            return
        # Stop current run
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._current_task
        # Cancel worker
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def queue(self) -> tuple[QueueEntry, ...]:
        return tuple(
            QueueEntry(run_id=e.run_id, request=e.request, state=e.state)
            for e in self._entries.values()
        )

    def subscribe(self, callback: Callable[[EngineEvent], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[EngineEvent], None]) -> None:
        self._subscribers.remove(callback)

    def _emit(self, event: EngineEvent) -> None:
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:
                logger.exception("Subscriber raised during callback")

    def _set_state(self, state: EngineState) -> None:
        self._state = state
        self._emit(StateChanged(state=state))

    def _queue_changed(self) -> QueueChanged:
        return QueueChanged(entries=self.queue)

    def _has_active_entries(self) -> bool:
        """True if any entry is still queued or running."""
        return any(
            e.state in (EntryState.QUEUED, EntryState.RUNNING) for e in self._entries.values()
        )

    async def _worker_loop(self) -> None:
        """Drain the pending queue forever."""
        while True:
            run_id = await self._pending.get()
            entry = self._entries.get(run_id)
            if entry is None or entry.state != EntryState.QUEUED:
                continue  # cancelled before dequeue

            self._stop_event.clear()
            # Run entry in its own task to allow hard-cancelling.
            self._current_task = asyncio.ensure_future(self._run_entry(entry))
            await self._current_task

    async def _run_entry(self, entry: _Entry) -> None:
        """Execute a single run entry."""
        run_id = entry.run_id
        request = entry.request
        entry.state = EntryState.RUNNING
        self._set_state(EngineState.RUNNING)
        self._emit(self._queue_changed())

        sink: ResultSink | None = None
        experiment: Experiment | None = None
        shots_completed = 0
        outcome = EntryState.COMPLETED
        error_msg: str | None = None
        stage = "load failed"
        loop = asyncio.get_running_loop()

        try:
            # Stage 1: Compile the source snapshot into an Experiment class
            cls = await loop.run_in_executor(
                None, self._loader, request.source, request.experiment_path
            )

            # Stage 2: Instantiate the class with the requested parameters
            stage = "invalid parameters"
            experiment = cls()
            declared = cls.parameters()
            for name, value in request.param_values.items():
                assert name in declared, f"param_values key {name!r} not in declared params"
                setattr(experiment, name, value)

            # Resolve scan (to_scan resolves each axis against cls)
            scan = request.scan.to_scan(cls) if request.scan else None

            # Stage 3: Connect to service stubs
            stage = "connect failed"
            await experiment.connect(self._client_provider())

            # Stage 4: Run user-defined setup
            stage = "setup failed"
            await experiment.setup()
            plots = experiment.plots()

            # Stage 5: Create data sink
            stage = "data sink failed"
            new_sink = await loop.run_in_executor(None, self._sink_factory, request, run_id)
            sink = new_sink

            # Stage 6: Compute shots and emit RunStarted
            points = list(scan.points()) if scan else [{}]
            repeats = request.repeats_per_point
            scan_repeats = request.scan_repeats

            if scan_repeats is not None:
                total_shots: int | None = len(points) * repeats * scan_repeats
            else:
                total_shots = None

            self._emit(
                RunStarted(
                    run_id=run_id,
                    total_shots=total_shots,
                    result_path=sink.path,
                    plots=plots,
                )
            )

            # Stage 7: Shot loop
            shot_idx = 0
            passes = itertools.count() if scan_repeats is None else range(scan_repeats)
            for _pass in passes:
                for point in points:
                    for param_name, value in point.items():
                        setattr(experiment, param_name, value)
                    for _ in range(repeats):
                        ctx = Context(shot_idx=shot_idx, run_id=run_id, total_shots=total_shots)
                        stage = "shot failed"
                        frame = await experiment.shot(ctx)
                        stage = "saving shot failed"
                        await loop.run_in_executor(None, sink.save_shot, shot_idx, frame)
                        shots_completed += 1
                        self._emit(
                            ShotCompleted(
                                run_id=run_id,
                                shot_idx=shot_idx,
                                total_shots=total_shots,
                                frame=frame,
                            )
                        )
                        shot_idx += 1

                        # Check if stop is requested
                        if self._stop_event.is_set():
                            outcome = EntryState.STOPPED
                            return

        except asyncio.CancelledError:
            outcome = EntryState.STOPPED
        except Exception as exc:
            outcome = EntryState.FAILED
            error_msg = f"{stage}: {exc}"
            logger.exception("Run failed (%s)", stage, extra={"run_id": run_id})
        finally:
            if experiment is not None:
                try:
                    await asyncio.shield(
                        experiment.teardown()
                    )  # shield from double-cancel (i.e. cancel run then close h2pcontrol)
                except asyncio.CancelledError:
                    logger.warning("teardown interrupted by shutdown", extra={"run_id": run_id})
                except Exception:
                    logger.exception("teardown() raised", extra={"run_id": run_id})

            if sink is not None:
                try:
                    await asyncio.shield(loop.run_in_executor(None, sink.close))
                except asyncio.CancelledError:
                    logger.warning("sink close interrupted by shutdown", extra={"run_id": run_id})
                except Exception:
                    logger.exception("sink.close() raised", extra={"run_id": run_id})

            entry.state = outcome
            self._emit(
                RunFinished(
                    run_id=run_id,
                    outcome=outcome,
                    shots_completed=shots_completed,
                    error=error_msg,
                )
            )
            self._emit(self._queue_changed())
            self._current_task = None
            if not self._has_active_entries():
                self._set_state(EngineState.IDLE)
