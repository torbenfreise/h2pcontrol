from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pytest

from h2pcontrol.controller.framework.views import (
    LineViewHandle,
    SeriesViewHandle,
    ViewHandle,
    ViewKind,
    ViewSpec,
)
from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import (
    EntryState,
    RunFinished,
    RunId,
    RunStarted,
)
from h2pcontrol.controller.ui.engine_bridge import EngineBridge
from h2pcontrol.controller.ui.plot_dock import PlotDock, _ViewPanel


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


def _series(
    title: str = "V", y_unit: str | None = None, x_unit: str | None = None
) -> SeriesViewHandle:
    return SeriesViewHandle(
        ViewSpec(title=title, kind=ViewKind.SERIES, y_unit=y_unit, x_unit=x_unit)
    )


def _line(
    title: str = "V",
    y_unit: str | None = None,
    x_unit: str | None = None,
) -> LineViewHandle:
    return LineViewHandle(ViewSpec(title=title, kind=ViewKind.LINE, y_unit=y_unit, x_unit=x_unit))


def _started(run_id: str, views: tuple[ViewHandle, ...]) -> RunStarted:
    return RunStarted(
        run_id=RunId(run_id),
        total_shots=None,
        result_path=Path("/tmp/run.h5"),
        views=views,
    )


# ---------------------------------------------------------------------------
# run lifecycle
# ---------------------------------------------------------------------------


def test_run_started_builds_tabs_and_shows(dock, fake_engine):
    fake_engine.emit(_started("r1", (_series("First"), _series("Second"))))
    assert dock._tabs.count() == 2
    assert dock._tabs.tabText(0) == "First"
    assert dock._tabs.tabText(1) == "Second"
    assert not dock.isHidden()
    assert dock._timer.isActive()


def test_run_started_without_views_hides(dock, fake_engine):
    fake_engine.emit(_started("r1", (_series("Only"),)))
    assert not dock.isHidden()

    fake_engine.emit(_started("r2", ()))
    assert dock.isHidden()
    assert dock._tabs.count() == 0
    assert not dock._timer.isActive()


# ---------------------------------------------------------------------------
# the dirty-buffer contract: pushes are drawn only by the repaint tick
# ---------------------------------------------------------------------------


def test_push_is_not_drawn_until_tick(dock, fake_engine):
    view = _series()
    fake_engine.emit(_started("r1", (view,)))

    view.push(0.0, 1.0)  # buffered + dirty, but not drawn
    xs, _ = dock._panels[0].curve.getData()
    assert xs is None or len(xs) == 0

    dock._tick()  # the timer's work — now it draws
    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [0.0]
    assert list(ys) == [1.0]


def test_series_accumulates_across_ticks(dock, fake_engine):
    view = _series()
    fake_engine.emit(_started("r1", (view,)))

    view.push(0.0, 1.0)
    dock._tick()
    view.push(1.0, 2.0)
    dock._tick()

    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [0.0, 1.0]
    assert list(ys) == [1.0, 2.0]


def test_multiple_pushes_coalesce_into_one_tick(dock, fake_engine):
    view = _series()
    fake_engine.emit(_started("r1", (view,)))

    for i in range(3):
        view.push(float(i), float(i))
    dock._tick()  # one repaint draws all buffered points

    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [0.0, 1.0, 2.0]
    assert list(ys) == [0.0, 1.0, 2.0]


def test_line_push_replaces_curve(dock, fake_engine):
    view = _line()
    fake_engine.emit(_started("r1", (view,)))

    view.push(np.arange(3.0), np.array([1.0, 2.0, 3.0]))
    dock._tick()
    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [0.0, 1.0, 2.0]
    assert list(ys) == [1.0, 2.0, 3.0]

    view.push(np.arange(3.0), np.array([4.0, 5.0, 6.0]))  # replaces, not appends
    dock._tick()
    _, ys = dock._panels[0].curve.getData()
    assert list(ys) == [4.0, 5.0, 6.0]


def test_line_push_moves_and_resizes_the_x_axis(dock, fake_engine):
    """Each push carries its own grid, so x may shift and change length."""
    view = _line()
    fake_engine.emit(_started("r1", (view,)))

    view.push(np.array([10.0, 20.0, 30.0]), np.array([1.0, 2.0, 3.0]))
    dock._tick()
    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [10.0, 20.0, 30.0]
    assert list(ys) == [1.0, 2.0, 3.0]

    view.push(np.array([0.0, 5.0]), np.array([4.0, 5.0]))
    dock._tick()
    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [0.0, 5.0]
    assert list(ys) == [4.0, 5.0]


def test_clean_panel_is_not_redrawn(dock, fake_engine):
    view = _series()
    fake_engine.emit(_started("r1", (view,)))
    view.push(0.0, 1.0)
    dock._tick()
    assert not view.dirty  # tick cleared it
    # A tick with nothing pushed leaves the flag clear and the curve unchanged.
    dock._tick()
    assert not view.dirty


def test_run_finished_flushes_and_stops(dock, fake_engine):
    view = _series()
    fake_engine.emit(_started("r1", (view,)))
    view.push(0.0, 1.0)  # pushed but not yet ticked

    fake_engine.emit(
        RunFinished(run_id=RunId("r1"), outcome=EntryState.COMPLETED, shots_completed=1)
    )
    # The final flush draws the last push, then the timer stops.
    xs, ys = dock._panels[0].curve.getData()
    assert list(xs) == [0.0]
    assert list(ys) == [1.0]
    assert not dock._timer.isActive()


# ---------------------------------------------------------------------------
# crosshair
# ---------------------------------------------------------------------------


def test_crosshair_label_uses_axis_units(qtbot):
    panel = _ViewPanel(_line(y_unit="V", x_unit="s"))
    qtbot.addWidget(panel.widget)
    text = panel._format_coord_text(1e-6, 0.5)
    assert "s" in text and "V" in text


def test_crosshair_label_shows_shot_axis_for_bare_series(qtbot):
    panel = _ViewPanel(_series(y_unit="V"))
    qtbot.addWidget(panel.widget)
    assert "shot" in panel._format_coord_text(3.0, 0.5)


def test_series_with_x_unit_labels_the_axis_by_unit(qtbot):
    """A series against a measured quantity is not a shot axis."""
    panel = _ViewPanel(_series(y_unit="V", x_unit="V"))
    qtbot.addWidget(panel.widget)
    assert "shot" not in panel._format_coord_text(3.0, 0.5)
    assert "V" in panel.widget.getAxis("bottom").labelString()
