from __future__ import annotations

import threading

import numpy as np
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.views import (
    LineViewHandle,
    SeriesViewHandle,
    ViewHandle,
    ViewKind,
    ViewSpec,
    view,
)


class Exp(Experiment):
    name = "Exp"

    trace = view("Trace", ViewKind.LINE, x_unit="us", y_unit="V")
    points = view("Points", ViewKind.SERIES, x_unit="V", y_unit="V")

    class Record(Results):
        x: float = result()

    async def shot(self, ctx: Context) -> list[Record]:
        return [self.Record(x=0.0)]


def line() -> LineViewHandle:
    """A bare line handle, for tests about push() rather than declaration."""
    return LineViewHandle(ViewSpec("Trace", ViewKind.LINE))


def series() -> SeriesViewHandle:
    """A bare series handle, for tests about push() rather than declaration."""
    return SeriesViewHandle(ViewSpec("Points", ViewKind.SERIES))


def drawn(handle: ViewHandle) -> tuple[list[float], list[float]]:
    """The (x, y) the UI would draw, as plain lists."""
    data = handle.plot_data()
    assert data is not None, "nothing pushed yet"
    x, y = data
    return list(x), list(y)


# ---------------------------------------------------------------------------
# view() declaration + handle identity
# ---------------------------------------------------------------------------


def test_kind_selects_the_handle_class():
    e = Exp()
    assert isinstance(e.trace, LineViewHandle)
    assert isinstance(e.points, SeriesViewHandle)


def test_class_access_yields_the_spec():
    assert isinstance(Exp.trace, ViewSpec)
    assert Exp.trace.title == "Trace"


def test_instance_access_is_stable():
    """Repeated access hands back the same handle, so pushes accumulate in one buffer."""
    e = Exp()
    assert e.trace is e.trace


def test_views_preserve_declaration_order():
    e = Exp()
    assert e.views() == (e.trace, e.points)


def test_views_isolated_per_instance():
    """Handles hold per-run buffers, so one run must never see another's."""
    e1, e2 = Exp(), Exp()
    e1.points.push(0.0, 1.0)
    assert e1.points is not e2.points
    assert e2.points.plot_data() is None


def test_views_include_panels_never_pushed_to():
    assert len(Exp().views()) == 2


def test_views_are_inherited():
    class Derived(Exp):
        extra = view("Extra", ViewKind.SERIES)

    d = Derived()
    assert [h.spec.title for h in d.views()] == ["Trace", "Points", "Extra"]
    assert len(Exp().views()) == 2  # the base class keeps its own set


def test_view_is_not_assignable():
    e = Exp()
    with pytest.raises(AttributeError, match="not assignable"):
        e.trace = line()  # type: ignore[misc]


def test_view_keeps_units():
    spec = Exp().trace.spec
    assert spec.title == "Trace"
    assert spec.x_unit == "us"
    assert spec.y_unit == "V"


def test_series_view_keeps_x_unit():
    """A series may run against a measured quantity, not just the shot index."""
    spec = Exp().points.spec
    assert spec.x_unit == "V"
    assert spec.y_unit == "V"


# ---------------------------------------------------------------------------
# push() — the dirty-buffer contract
# ---------------------------------------------------------------------------


def test_push_line_replaces_curve_and_marks_dirty():
    handle = line()
    assert not handle.dirty
    assert handle.plot_data() is None  # nothing to draw before the first push

    handle.push(np.arange(3.0), np.array([1.0, 2.0, 3.0]))
    assert handle.dirty
    assert drawn(handle) == ([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])

    handle.push(np.arange(3.0), np.array([4.0, 5.0, 6.0]))  # replaces, not appends
    assert drawn(handle)[1] == [4.0, 5.0, 6.0]


def test_push_series_accumulates_points():
    handle = series()
    assert handle.plot_data() is None
    handle.push(0.0, 1.0)
    handle.push(1.0, 2.0)
    assert drawn(handle) == ([0.0, 1.0], [1.0, 2.0])


def test_push_does_not_repaint_only_sets_dirty():
    """push() is a buffer write + dirty flag; drawing happens elsewhere on a timer.

    The buffer is the only state a push touches, so a caller that never reads it
    (as the UI does only on its repaint tick) sees nothing but the dirty flag.
    """
    handle = series()
    for i in range(50):
        handle.push(float(i), float(i))
    # 50 pushes, still just one pending repaint's worth of state: the dirty flag
    # is set once and all points are buffered, none drawn.
    assert handle.dirty
    assert len(drawn(handle)[0]) == 50


def test_clear_dirty_resets_flag_but_keeps_buffer():
    handle = line()
    handle.push(np.arange(2.0), np.array([1.0, 2.0]))
    handle.clear_dirty()
    assert not handle.dirty
    assert drawn(handle)[1] == [1.0, 2.0]  # buffer survives


def test_push_records_thread():
    handle = series()
    assert handle.push_thread is None
    handle.push(0.0, 1.0)
    assert handle.push_thread == threading.get_ident()


def test_line_push_replaces_the_x_axis_too():
    handle = line()
    handle.push(np.array([0.0, 1.0]), np.array([1.0, 2.0]))
    handle.push(np.array([0.0, 5.0]), np.array([3.0, 4.0]))
    assert drawn(handle) == ([0.0, 5.0], [3.0, 4.0])


def test_line_push_accepts_a_different_length_each_push():
    """Sample count may vary shot to shot, so nothing pins the curve's length."""
    handle = line()
    handle.push(np.arange(3.0), np.arange(3.0))
    handle.push(np.arange(5.0), np.arange(5.0))
    assert len(drawn(handle)[1]) == 5


def test_line_push_coerces_sequences_to_arrays():
    handle = line()
    handle.push([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    data = handle.plot_data()
    assert data is not None
    assert isinstance(data[0], np.ndarray) and isinstance(data[1], np.ndarray)
    assert drawn(handle)[0] == [0.0, 1.0, 2.0]


def test_line_push_rejects_mismatched_x_and_y():
    handle = line()
    with pytest.raises(ValueError, match="different shapes"):
        handle.push(np.arange(3.0), np.arange(4.0))


def test_line_push_rejects_mismatch_before_buffering_it():
    """A bad push must not leave a half-updated buffer for the UI to draw."""
    handle = line()
    handle.push(np.arange(2.0), np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        handle.push(np.arange(3.0), np.arange(4.0))
    assert drawn(handle) == ([0.0, 1.0], [1.0, 2.0])
