"""Tests for EngineBridge: engine events → Qt signals."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import (
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
from h2pcontrol.controller.runtime.spec import RunRequest
from h2pcontrol.controller.ui.engine_bridge import EngineBridge


class FakeEngine:
    def __init__(self) -> None:
        self.callbacks: list = []

    def subscribe(self, cb) -> None:
        self.callbacks.append(cb)

    def unsubscribe(self, cb) -> None:
        self.callbacks.remove(cb)

    def emit(self, event: EngineEvent) -> None:
        for cb in list(self.callbacks):
            cb(event)


def _request() -> RunRequest:
    return RunRequest(experiment_path=Path("/x.py"), experiment_name="E", param_values={})


def _events() -> list[tuple[str, EngineEvent]]:
    rid = RunId("abc")
    req = _request()
    return [
        ("run_queued", RunQueued(run_id=rid, request=req)),
        ("run_started", RunStarted(run_id=rid, total_shots=3, result_path=Path("/r_0001.h5"))),
        (
            "shot_completed",
            ShotCompleted(run_id=rid, shot_idx=0, total_shots=3, frame=pd.DataFrame()),
        ),
        ("run_finished", RunFinished(run_id=rid, outcome=EntryState.COMPLETED, shots_completed=3)),
        ("queue_changed", QueueChanged(entries=(QueueEntry(rid, req, EntryState.QUEUED),))),
        ("state_changed", StateChanged(state=EngineState.RUNNING)),
    ]


@pytest.mark.parametrize("signal_name,event", _events(), ids=[n for n, _ in _events()])
def test_dispatch_routes_to_signal(qtbot, signal_name: str, event: EngineEvent):
    fake = FakeEngine()
    bridge = EngineBridge(cast("RunEngine", fake))

    received: list[EngineEvent] = []
    getattr(bridge, signal_name).connect(received.append)

    fake.emit(event)

    assert received == [event]
    # Same payload object, not a copy.
    assert received[0] is event


def test_close_unsubscribes(qtbot):
    fake = FakeEngine()
    bridge = EngineBridge(cast("RunEngine", fake))
    assert len(fake.callbacks) == 1

    bridge.close()
    assert fake.callbacks == []
