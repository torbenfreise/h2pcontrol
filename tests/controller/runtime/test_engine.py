"""Tests for the RunEngine.

Fixtures live in conftest.py: ``experiment_factory`` builds a fresh Experiment
subclass per test, ``make_engine`` wires and auto-closes engines, ``sinks`` /
``sink_factory`` record saved shots, ``make_request`` builds RunRequests, and
``wait_for`` replaces sleep-based ordering.
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.views import SeriesViewHandle, ViewKind
from h2pcontrol.controller.runtime.events import (
    EngineEvent,
    EngineState,
    EntryState,
    QueueChanged,
    RunFinished,
    RunQueued,
    RunStarted,
    ShotCompleted,
    StateChanged,
)
from h2pcontrol.controller.runtime.session import Session
from h2pcontrol.controller.runtime.spec import LinearAxis, RunRequest, ScanSpec

pytestmark = pytest.mark.asyncio


def _marker(frame: pd.DataFrame) -> int:
    return int(frame[("result", "marker")].iloc[0])


def _snap_source(marker: int) -> str:
    return textwrap.dedent(f"""
        from h2pcontrol.controller.framework.experiment import Context, Experiment
        from h2pcontrol.controller.framework.parameters import param
        from h2pcontrol.controller.framework.results import Results, result

        class SnapExp(Experiment):
            name = "Snap"
            dummy = param(0)

            class Record(Results):
                marker: int = result()

            async def shot(self, ctx: Context) -> list[Record]:
                return [self.Record(marker={marker})]
    """)


# ---------------------------------------------------------------------------
# Single run
# ---------------------------------------------------------------------------


class TestSingleRun:
    async def test_single_run_3_repeats(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        run_id = engine.submit(make_request(repeats=3))
        finished = await wait_for(engine, RunFinished)
        # IDLE is emitted synchronously right after RunFinished, so it is already
        # set by the time this await resumes.
        assert engine.state == EngineState.IDLE

        assert events[0].__class__ is RunQueued
        assert events[1].__class__ is QueueChanged
        assert sum(isinstance(e, ShotCompleted) for e in events) == 3
        assert finished.run_id == run_id
        assert finished.outcome == EntryState.COMPLETED
        assert finished.shots_completed == 3
        assert finished.error is None

        assert len(sinks) == 1
        assert len(sinks[0].shots) == 3
        assert sinks[0].closed
        assert engine.state == EngineState.IDLE

    async def test_contexts_have_run_id_and_total(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)

        run_id = engine.submit(make_request(repeats=3))
        await wait_for(engine, RunFinished)

        exp = probe.instances[0]
        contexts = exp.contexts  # type: ignore[attr-defined]
        assert len(contexts) == 3
        for i, ctx in enumerate(contexts):
            assert ctx.run_id == run_id
            assert ctx.shot_idx == i
            assert ctx.total_shots == 3

    async def test_full_event_ordering(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        engine.submit(make_request(repeats=1))
        await wait_for(engine, StateChanged, predicate=lambda e: e.state is EngineState.IDLE)

        def describe(e: EngineEvent) -> object:
            return (type(e).__name__, e.state) if isinstance(e, StateChanged) else type(e).__name__

        assert [describe(e) for e in events] == [
            "RunQueued",
            "QueueChanged",
            ("StateChanged", EngineState.RUNNING),
            "QueueChanged",
            "RunStarted",
            "ShotCompleted",
            "RunFinished",
            "QueueChanged",
            ("StateChanged", EngineState.IDLE),
        ]


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------


class TestScanRun:
    async def test_scan_2x2_with_repeats(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        scan = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=5.0, steps=2),))
        engine.submit(make_request(repeats=2, scan=scan))
        await wait_for(engine, RunFinished)
        assert len(sinks[0].shots) == 4  # 2 points x 2 repeats

    async def test_scan_repeats_multiplies(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        scan = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=5.0, steps=2),))
        engine.submit(make_request(repeats=1, scan=scan, scan_repeats=3))
        await wait_for(engine, RunFinished)
        assert len(sinks[0].shots) == 6  # 2 points x 1 repeat x 3 scan_repeats


class TestInfiniteScanRepeats:
    async def test_infinite_runs_until_stop(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        scan = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=5.0, steps=2),))
        engine.submit(make_request(repeats=1, scan=scan, scan_repeats=None))

        started = await wait_for(engine, RunStarted)
        assert started.total_shots is None
        await wait_for(engine, ShotCompleted, count=2)
        engine.stop_current()
        finished = await wait_for(engine, RunFinished)

        assert finished.outcome == EntryState.STOPPED
        assert all(e.total_shots is None for e in events if isinstance(e, ShotCompleted))
        assert len(sinks[0].shots) > 0
        assert sinks[0].closed
        # History row survives (never auto-removed).
        assert len(engine.queue) == 1
        assert engine.queue[0].state == EntryState.STOPPED


# ---------------------------------------------------------------------------
# FIFO + queue history
# ---------------------------------------------------------------------------


class TestFIFO:
    async def test_two_submits_run_in_order(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        id1 = engine.submit(make_request(repeats=1))
        id2 = engine.submit(make_request(repeats=1))

        await wait_for(engine, RunStarted)
        q = engine.queue
        assert q[0].run_id == id1
        assert q[0].state == EntryState.RUNNING
        assert q[1].run_id == id2
        assert q[1].state == EntryState.QUEUED

        block.set()
        await wait_for(engine, RunFinished, count=2)

        finished = [e for e in events if isinstance(e, RunFinished)]
        assert [f.run_id for f in finished] == [id1, id2]
        # Both remain as COMPLETED history rows.
        assert [e.state for e in engine.queue] == [EntryState.COMPLETED, EntryState.COMPLETED]


class TestQueueHistory:
    async def test_completed_entry_is_kept(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        run_id = engine.submit(make_request(repeats=1))
        await wait_for(engine, RunFinished)

        assert len(engine.queue) == 1
        assert engine.queue[0].run_id == run_id
        assert engine.queue[0].state == EntryState.COMPLETED

    async def test_clear_finished_removes_only_terminal(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []

        engine.submit(make_request(repeats=1))  # will run + block
        engine.submit(make_request(repeats=1))  # stays QUEUED
        await wait_for(engine, RunStarted)

        engine.subscribe(events.append)
        engine.clear_finished()  # nothing terminal yet → no QueueChanged
        assert not any(isinstance(e, QueueChanged) for e in events)
        assert len(engine.queue) == 2

        # Cancel the queued one so it becomes terminal, then clear.
        queued_id = engine.queue[1].run_id
        engine.cancel(queued_id)
        engine.clear_finished()
        # RUNNING entry survives; CANCELLED one removed.
        assert [e.state for e in engine.queue] == [EntryState.RUNNING]

        block.set()
        await wait_for(engine, RunFinished)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    async def test_cancel_queued_leaves_cancelled_entry(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        engine.submit(make_request(repeats=1))
        id2 = engine.submit(make_request(repeats=1))
        await wait_for(engine, RunStarted)

        engine.cancel(id2)
        assert engine.queue[1].state == EntryState.CANCELLED
        last_qc = [e for e in events if isinstance(e, QueueChanged)][-1]
        assert last_qc.entries[1].state == EntryState.CANCELLED

        block.set()
        await wait_for(engine, RunFinished)
        # Cancelled entry never ran -> only one sink created.
        assert len(sinks) == 1
        assert engine.queue[1].state == EntryState.CANCELLED

        # The cancelled run is still in _pending,
        # assert that engine returns to idle.
        assert engine.state == EngineState.IDLE
        state_seq = [e.state for e in events if isinstance(e, StateChanged)]
        assert state_seq == [EngineState.RUNNING, EngineState.IDLE]

    async def test_cancel_finished_entry_is_noop(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        run_id = engine.submit(make_request(repeats=1))
        await wait_for(engine, RunFinished)

        # Must not raise, must not change the terminal state.
        engine.cancel(run_id)
        assert engine.queue[0].state == EntryState.COMPLETED

    async def test_cancel_unknown_is_noop(self, experiment_factory, make_engine):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        # Unknown run_id: no-op, does not raise.
        engine.cancel("nope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


class TestSoftStop:
    async def test_soft_stop_is_deterministic(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        # The 3rd shot (idx 2) blocks; after release it completes as the last
        # saved shot, then the stop flag ends the run → exactly 3 saved shots.
        block = asyncio.Event()
        probe = experiment_factory(block_event=block, block_at=2)
        engine = make_engine(probe.loader)

        engine.submit(make_request(repeats=100))
        await wait_for(engine, ShotCompleted, count=2)  # shots 0, 1 saved; blocked at 2

        engine.stop_current()
        block.set()
        finished = await wait_for(engine, RunFinished)

        assert finished.outcome == EntryState.STOPPED
        assert len(sinks[0].shots) == 3
        assert probe.instances[0].teardown_called  # type: ignore[attr-defined]
        assert sinks[0].closed


class TestHardStop:
    async def test_hard_stop_unblocks(
        self, experiment_factory, make_engine, make_request, sinks, wait_for
    ):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)

        engine.submit(make_request(repeats=5))
        await wait_for(engine, RunStarted)
        engine.stop_current(hard=True)
        finished = await wait_for(engine, RunFinished)

        assert finished.outcome == EntryState.STOPPED
        assert probe.instances[0].teardown_called  # type: ignore[attr-defined]
        assert sinks[0].closed

    async def test_hard_stop_worker_survives(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        engine.submit(make_request(repeats=1))
        engine.submit(make_request(repeats=1))
        await wait_for(engine, RunStarted)

        engine.stop_current(hard=True)
        block.set()  # second run won't block (event stays set)
        await wait_for(engine, RunFinished, count=2)

        finished = [e for e in events if isinstance(e, RunFinished)]
        assert finished[0].outcome == EntryState.STOPPED
        assert finished[1].outcome == EntryState.COMPLETED


# ---------------------------------------------------------------------------
# Error taxonomy (F6)
# ---------------------------------------------------------------------------


class TestErrorTaxonomy:
    async def test_load_failure_prefixed(self, make_engine, make_request, wait_for):
        def failing_loader(_source: str, _path: Path) -> type[Experiment]:
            raise ImportError("file not found")

        engine = make_engine(failing_loader)
        engine.submit(make_request(repeats=1))
        finished = await wait_for(engine, RunFinished)
        assert finished.outcome == EntryState.FAILED
        assert finished.error is not None and finished.error.startswith("load failed:")

    async def test_bad_param_prefixed(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        engine.submit(make_request(repeats=1, param_values={"voltage": 999.0}))
        finished = await wait_for(engine, RunFinished)
        assert finished.outcome == EntryState.FAILED
        assert finished.error is not None and finished.error.startswith("invalid parameters:")

    async def test_shot_exception_prefixed(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        probe = experiment_factory(raise_on_shot=RuntimeError("device exploded"))
        engine = make_engine(probe.loader)
        engine.submit(make_request(repeats=1))
        finished = await wait_for(engine, RunFinished)
        assert finished.outcome == EntryState.FAILED
        assert finished.error == "shot failed: device exploded"

    async def test_storage_failure_prefixed(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        class FailingSink:
            path = Path("/tmp/failing.h5")

            def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None:
                raise OSError("disk full")

            def close(self) -> None:
                pass

        probe = experiment_factory()
        engine = make_engine(probe.loader, sink=lambda _req, _rid, _schema: FailingSink())
        engine.submit(make_request(repeats=1))
        finished = await wait_for(engine, RunFinished)
        assert finished.outcome == EntryState.FAILED
        assert finished.error is not None and finished.error.startswith("saving shot failed:")


# ---------------------------------------------------------------------------
# Invalid params / unknown-param guard (F3)
# ---------------------------------------------------------------------------


class TestInvalidParams:
    async def test_bad_param_fails_before_connect(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        client_called = False

        def client_provider():
            nonlocal client_called
            client_called = True
            return None  # never reached

        probe = experiment_factory()
        engine = make_engine(probe.loader, client_provider=client_provider)  # type: ignore[arg-type]
        engine.submit(make_request(repeats=1, param_values={"voltage": 999.0}))
        finished = await wait_for(engine, RunFinished)

        assert finished.outcome == EntryState.FAILED
        assert not client_called

    async def test_unknown_param_guard(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        client_called = False

        def client_provider():
            nonlocal client_called
            client_called = True
            return None

        probe = experiment_factory()
        engine = make_engine(probe.loader, client_provider=client_provider)  # type: ignore[arg-type]

        engine.submit(make_request(repeats=1, param_values={"nonexistent": 1.0}))
        finished = await wait_for(engine, RunFinished)
        assert finished.outcome == EntryState.FAILED
        assert finished.error is not None and "nonexistent" in finished.error
        assert not client_called

        # Worker survives — a valid subsequent run still completes.  (Fresh
        # wait_for subscription, so this is the next RunFinished, count=1.)
        engine.submit(make_request(repeats=1))
        ok = await wait_for(engine, RunFinished)
        assert ok.outcome == EntryState.COMPLETED


# ---------------------------------------------------------------------------
# Source-snapshot binding (F3)
# ---------------------------------------------------------------------------


class TestSourceSnapshot:
    async def test_snapshot_executes_not_disk(self, make_engine, sinks, wait_for, tmp_path: Path):
        path = tmp_path / "snap.py"
        v1 = _snap_source(1)
        path.write_text(v1)
        # Overwrite the file on disk with a different version.
        path.write_text(_snap_source(2))

        session = Session()
        engine = make_engine(session.load_experiment_from_source)
        engine.submit(
            RunRequest(
                experiment_path=path,
                experiment_name="Snap",
                param_values={},
                source=v1,  # the captured v1 snapshot
                repeats_per_point=1,
                scan_repeats=1,
            )
        )
        await wait_for(engine, RunFinished)
        # Executed the captured v1, not the v2 now on disk.
        assert _marker(sinks[0].shots[0][1]) == 1

    async def test_deleted_file_still_runs(self, make_engine, sinks, wait_for, tmp_path: Path):
        path = tmp_path / "gone.py"
        source = _snap_source(7)
        path.write_text(source)
        path.unlink()  # file no longer exists

        session = Session()
        engine = make_engine(session.load_experiment_from_source)
        engine.submit(
            RunRequest(
                experiment_path=path,
                experiment_name="Snap",
                param_values={},
                source=source,
                repeats_per_point=1,
                scan_repeats=1,
            )
        )
        finished = await wait_for(engine, RunFinished)
        assert finished.outcome == EntryState.COMPLETED
        assert _marker(sinks[0].shots[0][1]) == 7

    async def test_per_entry_snapshots(self, make_engine, sinks, wait_for, tmp_path: Path):
        path = tmp_path / "snap.py"
        session = Session()
        engine = make_engine(session.load_experiment_from_source)

        for marker in (1, 2):
            engine.submit(
                RunRequest(
                    experiment_path=path,
                    experiment_name="Snap",
                    param_values={},
                    source=_snap_source(marker),
                    repeats_per_point=1,
                    scan_repeats=1,
                )
            )
        await wait_for(engine, RunFinished, count=2)

        assert _marker(sinks[0].shots[0][1]) == 1
        assert _marker(sinks[1].shots[0][1]) == 2


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestSubscriberError:
    async def test_bad_subscriber_does_not_kill_run(
        self, experiment_factory, make_engine, make_request, wait_for, caplog
    ):
        probe = experiment_factory()
        engine = make_engine(probe.loader)

        def bad_sub(event: EngineEvent) -> None:
            raise ValueError("subscriber exploded")

        engine.subscribe(bad_sub)
        engine.submit(make_request(repeats=2))
        finished = await wait_for(engine, RunFinished)

        assert finished.outcome == EntryState.COMPLETED
        assert "subscriber exploded" in caplog.text


class TestTeardownError:
    async def test_teardown_raising_does_not_change_outcome(
        self, experiment_factory, make_engine, make_request, wait_for, caplog
    ):
        probe = experiment_factory(raise_on_teardown=True)
        engine = make_engine(probe.loader)
        engine.submit(make_request(repeats=2))
        finished = await wait_for(engine, RunFinished)

        assert finished.outcome == EntryState.COMPLETED
        assert "teardown" in caplog.text


class TestAclose:
    async def test_aclose_mid_run(self, experiment_factory, make_engine, make_request, wait_for):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        engine.submit(make_request(repeats=5))
        await wait_for(engine, RunStarted)
        await engine.aclose()

        finished = next(e for e in events if isinstance(e, RunFinished))
        assert finished.outcome == EntryState.STOPPED

    async def test_aclose_with_pending_entries_does_not_deadlock(
        self, experiment_factory, make_engine, make_request, wait_for
    ):
        block = asyncio.Event()
        probe = experiment_factory(block_event=block)
        engine = make_engine(probe.loader)
        events: list[EngineEvent] = []
        engine.subscribe(events.append)

        engine.submit(make_request(repeats=1))  # runs + blocks
        engine.submit(make_request(repeats=1))  # pending
        engine.submit(make_request(repeats=1))  # pending
        await wait_for(engine, RunStarted)

        # Must return promptly; pending entries must never start.
        await asyncio.wait_for(engine.aclose(), timeout=5)
        assert len(probe.instances) == 1  # only the running entry was built
        finished = [e for e in events if isinstance(e, RunFinished)]
        assert finished[0].outcome == EntryState.STOPPED

        await engine.aclose()  # second close is a no-op

    async def test_aclose_is_idempotent(self, experiment_factory, make_engine):
        probe = experiment_factory()
        engine = make_engine(probe.loader)
        await engine.aclose()
        await engine.aclose()


class TestViews:
    async def test_run_started_carries_declared_views(self, make_engine, make_request, wait_for):
        class ViewExp(Experiment):
            name = "ViewExp"

            class Record(Results):
                yr: float = result(unit="V")

            async def setup(self) -> None:
                self.series = self.view("P", ViewKind.SERIES, y_unit="V")

            async def shot(self, ctx: Context) -> list[Record]:
                self.series.push(ctx.shot_idx, 1.0)
                return [self.Record(yr=1.0)]

        def loader(_source: str, _path: Path) -> type[Experiment]:
            return ViewExp

        engine = make_engine(loader)
        engine.submit(make_request(repeats=1))
        started = await wait_for(engine, RunStarted)

        assert len(started.views) == 1
        handle = started.views[0]
        assert handle.spec.title == "P"
        assert handle.spec.y_unit == "V"
        assert isinstance(handle, SeriesViewHandle)
