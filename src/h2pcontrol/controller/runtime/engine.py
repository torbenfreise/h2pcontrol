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
import importlib.metadata
import itertools
import json
import logging
import platform
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..framework.experiment import Context, Experiment
from ..framework.timing import ShotTimings
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
from .rpc_instrumentation import InstrumentedClient, RpcLog
from .session import ClientProvider
from .spec import RunRequest
from .store import RunSchema
from .writer import ProcessWriter, ShotWriter, SinkFactory, WriterFactory

logger = logging.getLogger(__name__)


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def _run_metadata() -> dict[str, Any]:
    """Provenance for a run's timing logs: interpreter, OS, host, git state."""
    meta: dict[str, Any] = {
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
    }
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        meta["h2pcontrol_version"] = importlib.metadata.version("h2pcontrol")
    root = _repo_root()
    if root is not None:
        try:
            git = ["git", "-C", str(root)]
            meta["git_commit"] = subprocess.run(
                [*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
            meta["git_dirty"] = bool(
                subprocess.run(
                    [*git, "status", "--porcelain"], capture_output=True, text=True, check=True
                ).stdout.strip()
            )
        except (OSError, subprocess.CalledProcessError):
            logger.warning("could not record git state for timing logs")
    return meta


def _write_timing_logs(
    result_path: Path,
    timing_rows: list[dict[str, float]],
    rpc_records: list[dict[str, Any]],
) -> None:
    """Write per-shot timings, the RPC log, and a provenance sidecar next to the result file."""
    stem = result_path.with_suffix("")
    if timing_rows:
        pd.DataFrame(timing_rows).to_csv(f"{stem}_timings.csv", index=False)
    if rpc_records:
        pd.DataFrame(rpc_records).to_csv(f"{stem}_rpc.csv", index=False)
    with open(f"{stem}_meta.json", "w", encoding="utf-8") as f:
        json.dump(_run_metadata(), f, indent=2)


_TERMINAL = (
    EntryState.COMPLETED,
    EntryState.FAILED,
    EntryState.STOPPED,
    EntryState.CANCELLED,
)


# type alias so Engine.__init__() has a nicer function signature
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
        writer_factory: WriterFactory = ProcessWriter,
    ) -> None:
        self._client_provider = client_provider
        self._sink_factory = sink_factory
        self._loader = loader
        self._writer_factory = writer_factory

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

        writer: ShotWriter | None = None
        result_path: Path | None = None
        experiment: Experiment | None = None
        shots_completed = 0
        outcome = EntryState.COMPLETED
        error_msg: str | None = None
        stage = "load failed"
        loop = asyncio.get_running_loop()

        # Per-run instrumentation: phase spans per shot + a log of every RPC.
        # Both are written as CSVs next to the result file when the run ends.
        rpc_log = RpcLog()
        timing_rows: list[dict[str, float]] = []

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

            # Stage 3: Connect to service stubs (wrapped so every RPC is timed)
            stage = "connect failed"
            await experiment.connect(InstrumentedClient(self._client_provider(), rpc_log))

            # Stage 4: Run user-defined setup
            stage = "setup failed"
            await experiment.setup()
            views = experiment.views()

            # Stage 5: Create data sink, described by the experiment's declared specs.
            # The writer owns the sink from here on — by default in its own
            # process, so persisting a shot costs the run loop only a hand-off.
            stage = "data sink failed"
            schema = RunSchema(
                results=cls.results(),
                params=cls.parameters(),
                metadata=experiment.metadata(),
            )
            writer = self._writer_factory(self._sink_factory, request, run_id, schema)
            result_path = await writer.open()

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
                    result_path=result_path,
                    views=views,
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
                        timings = ShotTimings()
                        rpc_log.shot_idx = shot_idx
                        ctx = Context(
                            shot_idx=shot_idx,
                            run_id=run_id,
                            total_shots=total_shots,
                            timings=timings,
                        )
                        stage = "shot failed"
                        with timings.span("shot"):
                            frame = await experiment.record(ctx)
                        stage = "saving shot failed"
                        # Hand the frame to the writer and move on; the actual
                        # write overlaps the next shot. This span now measures
                        # only the hand-off (pickle + enqueue) — a large value
                        # means backpressure, not write cost.
                        with timings.span("save"):
                            await writer.save(shot_idx, frame)
                        shots_completed += 1
                        # Subscribers run synchronously, so with direct Qt
                        # connections this span includes UI/plot updates.
                        with timings.span("emit"):
                            self._emit(
                                ShotCompleted(
                                    run_id=run_id,
                                    shot_idx=shot_idx,
                                    total_shots=total_shots,
                                    frame=frame,
                                )
                            )
                        timing_rows.append(
                            {
                                "shot_idx": shot_idx,
                                # Monotonic timestamp; shot periods are diffs
                                # of t_mono. Absolute time is in _meta.json.
                                "t_mono": time.perf_counter(),
                                **timings.as_row(),
                            }
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
            rpc_log.shot_idx = -1  # teardown RPCs are not part of any shot
            if experiment is not None:
                try:
                    await asyncio.shield(
                        experiment.teardown()
                    )  # shield from double-cancel (i.e. cancel run then close h2pcontrol)
                except asyncio.CancelledError:
                    logger.warning("teardown interrupted by shutdown", extra={"run_id": run_id})
                except Exception:
                    logger.exception("teardown() raised", extra={"run_id": run_id})

            # Flush queued writes before closing: the writer and the sink's
            # close share one HDF5 handle and must not overlap.
            if writer is not None:
                try:
                    await asyncio.shield(writer.flush())
                except asyncio.CancelledError:
                    logger.warning("shot flush interrupted by shutdown", extra={"run_id": run_id})
                except Exception as exc:
                    logger.exception("flushing pending shots failed", extra={"run_id": run_id})
                    if outcome == EntryState.COMPLETED:
                        outcome = EntryState.FAILED
                        error_msg = f"saving shot failed: {exc}"

                try:
                    await asyncio.shield(writer.aclose())
                except asyncio.CancelledError:
                    logger.warning("sink close interrupted by shutdown", extra={"run_id": run_id})
                except Exception:
                    logger.exception("closing the shot writer raised", extra={"run_id": run_id})

            if result_path is not None and (timing_rows or rpc_log.records):
                try:
                    await asyncio.shield(
                        loop.run_in_executor(
                            None, _write_timing_logs, result_path, timing_rows, rpc_log.records
                        )
                    )
                except asyncio.CancelledError:
                    logger.warning(
                        "timing log write interrupted by shutdown", extra={"run_id": run_id}
                    )
                except Exception:
                    logger.exception("writing timing logs failed", extra={"run_id": run_id})

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
