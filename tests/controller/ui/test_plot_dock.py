from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from h2pcontrol.controller.framework.results import PlotSpec, ResultSpec, result
from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import (
    EntryState,
    RunFinished,
    RunId,
    RunStarted,
    ShotCompleted,
)
from h2pcontrol.controller.ui.engine_bridge import EngineBridge
from h2pcontrol.controller.ui.plot_dock import PlotDock, _PlotPanel


class FakeEngine:
    def __init__(self) -> None:
        self.callbacks: list = []

    def subscribe(self, cb) -> None:
        self.callbacks.append(cb)

    def unsubscribe(self, cb) -> None:
        self.callbacks.remove(cb)

    def emit(self, event) -> None:
        for cb in list(self.callbacks):
            cb(event)


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def dock(qtbot, fake_engine: FakeEngine) -> PlotDock:
    bridge = EngineBridge(cast("RunEngine", fake_engine))
    d = PlotDock(bridge)
    qtbot.addWidget(d)
    return d


def _res(name: str, dtype: type = float, unit: str | None = None) -> ResultSpec:
    spec = result(dtype, unit=unit)
    spec.name = name
    return spec


def _started(run_id: str, plots: tuple[PlotSpec, ...]) -> RunStarted:
    return RunStarted(
        run_id=RunId(run_id),
        total_shots=None,
        result_path=Path("/tmp/run.h5"),
        plots=plots,
    )


def _frame(rows: list[tuple[float, float]]) -> pd.DataFrame:
    cols = pd.MultiIndex.from_tuples([("result", "x"), ("result", "y")])
    return pd.DataFrame(rows, columns=cols)


def test_run_started_builds_tabs_and_shows(dock, fake_engine):
    plots = (
        PlotSpec(ys=(_res("y"),), x=_res("x"), title="First"),
        PlotSpec(ys=(_res("y2"),), title="Second"),
    )
    fake_engine.emit(_started("r1", plots))

    assert dock._tabs.count() == 2
    assert dock._tabs.tabText(0) == "First"
    assert dock._tabs.tabText(1) == "Second"
    assert not dock.isHidden()


def test_run_started_without_plots_hides(dock, fake_engine):
    fake_engine.emit(_started("r1", (PlotSpec(ys=(_res("y"),)),)))
    assert not dock.isHidden()

    fake_engine.emit(_started("r2", ()))
    assert dock.isHidden()
    assert dock._tabs.count() == 0


def test_tab_label_derived_from_channel_when_no_title(dock, fake_engine):
    y = _res("signal")
    y.description = "Signal"
    fake_engine.emit(_started("r1", (PlotSpec(ys=(y,)),)))
    assert dock._tabs.tabText(0) == "Signal"


def test_shot_completed_appends_series_point(dock, fake_engine):
    spec = PlotSpec(ys=(_res("y"),), x=_res("x"))
    fake_engine.emit(_started("r1", (spec,)))

    fake_engine.emit(
        ShotCompleted(run_id=RunId("r1"), shot_idx=0, total_shots=None, frame=_frame([(0.0, 1.0)]))
    )
    xs, ys = dock._panels[0].curves[0].getData()
    assert list(xs) == [0.0]
    assert list(ys) == [1.0]

    fake_engine.emit(
        ShotCompleted(run_id=RunId("r1"), shot_idx=1, total_shots=None, frame=_frame([(1.0, 2.0)]))
    )
    xs, ys = dock._panels[0].curves[0].getData()
    assert list(xs) == [0.0, 1.0]
    assert list(ys) == [1.0, 2.0]


def test_multi_row_shot_appends_all_rows(dock, fake_engine):
    spec = PlotSpec(ys=(_res("y"),), x=_res("x"))
    fake_engine.emit(_started("r1", (spec,)))

    fake_engine.emit(
        ShotCompleted(
            run_id=RunId("r1"),
            shot_idx=0,
            total_shots=None,
            frame=_frame([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]),
        )
    )
    xs, ys = dock._panels[0].curves[0].getData()
    assert list(xs) == [0.0, 1.0, 2.0]
    assert list(ys) == [1.0, 2.0, 3.0]


def test_shot_from_other_run_is_ignored(dock, fake_engine):
    spec = PlotSpec(ys=(_res("y"),), x=_res("x"))
    fake_engine.emit(_started("r1", (spec,)))
    fake_engine.emit(
        ShotCompleted(
            run_id=RunId("other"), shot_idx=0, total_shots=None, frame=_frame([(0.0, 1.0)])
        )
    )
    xs, _ = dock._panels[0].curves[0].getData()
    assert xs is None or len(xs) == 0


def test_run_finished_stops_updating(dock, fake_engine):
    spec = PlotSpec(ys=(_res("y"),), x=_res("x"))
    fake_engine.emit(_started("r1", (spec,)))
    fake_engine.emit(
        RunFinished(run_id=RunId("r1"), outcome=EntryState.COMPLETED, shots_completed=1)
    )

    fake_engine.emit(
        ShotCompleted(run_id=RunId("r1"), shot_idx=9, total_shots=None, frame=_frame([(9.0, 9.0)]))
    )
    xs, _ = dock._panels[0].curves[0].getData()
    assert xs is None or len(xs) == 0


def test_crosshair_label_uses_axis_units(qtbot):
    panel = _PlotPanel(PlotSpec(ys=(_res("sig", float, "V"),), x=_res("t", float, "s")))
    qtbot.addWidget(panel.widget)
    text = panel._format_coord_text(1e-6, 0.5)
    assert "s" in text and "V" in text


def test_crosshair_label_shows_shot_axis_without_x(qtbot):
    panel = _PlotPanel(PlotSpec(ys=(_res("sig", float, "V"),)))
    qtbot.addWidget(panel.widget)
    assert "shot" in panel._format_coord_text(3.0, 0.5)
