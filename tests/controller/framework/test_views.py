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
)


class Exp(Experiment):
    name = "Exp"

    class Record(Results):
        x: float = result()

    async def shot(self, ctx: Context) -> list[Record]:
        return [self.Record(x=0.0)]


def drawn(handle: ViewHandle) -> tuple[list[float], list[float]]:
    """The (x, y) the UI would draw, as plain lists."""
    data = handle.plot_data()
    assert data is not None, "nothing pushed yet"
    x, y = data
    return list(x), list(y)


# ---------------------------------------------------------------------------
# view() declaration + handle identity
# ---------------------------------------------------------------------------


def test_view_returns_handle_and_records_it():
    e = Exp()
    handle = e.view("Trace", ViewKind.LINE, y_unit="V")
    assert isinstance(handle, LineViewHandle)
    assert e.views() == (handle,)


def test_views_preserve_declaration_order():
    e = Exp()
    first = e.view("First", ViewKind.SERIES)
    second = e.view("Second", ViewKind.LINE)
    assert e.views() == (first, second)


def test_views_isolated_per_instance():
    e1, e2 = Exp(), Exp()
    e1.view("Trace", ViewKind.SERIES)
    assert len(e1.views()) == 1
    assert e2.views() == ()


def test_kind_selects_the_handle_class():
    e = Exp()
    assert isinstance(e.view("Trace", ViewKind.LINE), LineViewHandle)
    assert isinstance(e.view("Points", ViewKind.SERIES), SeriesViewHandle)


def test_view_keeps_units():
    spec = Exp().view("Trace", ViewKind.LINE, x_unit="us", y_unit="V").spec
    assert spec.title == "Trace"
    assert spec.x_unit == "us"
    assert spec.y_unit == "V"


def test_series_view_keeps_x_unit():
    """A series may run against a measured quantity, not just the shot index."""
    spec = Exp().view("Points", ViewKind.SERIES, x_unit="V", y_unit="V").spec
    assert spec.x_unit == "V"
    assert spec.y_unit == "V"


# ---------------------------------------------------------------------------
# push() — the dirty-buffer contract
# ---------------------------------------------------------------------------


def test_push_line_replaces_curve_and_marks_dirty():
    handle = Exp().view("Trace", ViewKind.LINE)
    assert not handle.dirty
    assert handle.plot_data() is None  # nothing to draw before the first push

    handle.push(np.arange(3.0), np.array([1.0, 2.0, 3.0]))
    assert handle.dirty
    assert drawn(handle) == ([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])

    handle.push(np.arange(3.0), np.array([4.0, 5.0, 6.0]))  # replaces, not appends
    assert drawn(handle)[1] == [4.0, 5.0, 6.0]


def test_push_series_accumulates_points():
    handle = Exp().view("Points", ViewKind.SERIES)
    assert handle.plot_data() is None
    handle.push(0.0, 1.0)
    handle.push(1.0, 2.0)
    assert drawn(handle) == ([0.0, 1.0], [1.0, 2.0])


def test_push_does_not_repaint_only_sets_dirty():
    """push() is a buffer write + dirty flag; drawing happens elsewhere on a timer.

    The buffer is the only state a push touches, so a caller that never reads it
    (as the UI does only on its repaint tick) sees nothing but the dirty flag.
    """
    handle = Exp().view("Points", ViewKind.SERIES)
    for i in range(50):
        handle.push(float(i), float(i))
    # 50 pushes, still just one pending repaint's worth of state: the dirty flag
    # is set once and all points are buffered, none drawn.
    assert handle.dirty
    assert len(drawn(handle)[0]) == 50


def test_clear_dirty_resets_flag_but_keeps_buffer():
    handle = Exp().view("Trace", ViewKind.LINE)
    handle.push(np.arange(2.0), np.array([1.0, 2.0]))
    handle.clear_dirty()
    assert not handle.dirty
    assert drawn(handle)[1] == [1.0, 2.0]  # buffer survives


def test_push_records_thread():
    handle = Exp().view("Points", ViewKind.SERIES)
    assert handle.push_thread is None
    handle.push(0.0, 1.0)
    assert handle.push_thread == threading.get_ident()


def test_line_push_replaces_the_x_axis_too():
    handle = Exp().view("Trace", ViewKind.LINE)
    handle.push(np.array([0.0, 1.0]), np.array([1.0, 2.0]))
    handle.push(np.array([0.0, 5.0]), np.array([3.0, 4.0]))
    assert drawn(handle) == ([0.0, 5.0], [3.0, 4.0])


def test_line_push_accepts_a_different_length_each_push():
    """Sample count may vary shot to shot, so nothing pins the curve's length."""
    handle = Exp().view("Trace", ViewKind.LINE)
    handle.push(np.arange(3.0), np.arange(3.0))
    handle.push(np.arange(5.0), np.arange(5.0))
    assert len(drawn(handle)[1]) == 5


def test_line_push_coerces_sequences_to_arrays():
    handle = Exp().view("Trace", ViewKind.LINE)
    handle.push([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    data = handle.plot_data()
    assert data is not None
    assert isinstance(data[0], np.ndarray) and isinstance(data[1], np.ndarray)
    assert drawn(handle)[0] == [0.0, 1.0, 2.0]


def test_line_push_rejects_mismatched_x_and_y():
    handle = Exp().view("Trace", ViewKind.LINE)
    with pytest.raises(ValueError, match="different shapes"):
        handle.push(np.arange(3.0), np.arange(4.0))


def test_line_push_rejects_mismatch_before_buffering_it():
    """A bad push must not leave a half-updated buffer for the UI to draw."""
    handle = Exp().view("Trace", ViewKind.LINE)
    handle.push(np.arange(2.0), np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        handle.push(np.arange(3.0), np.arange(4.0))
    assert drawn(handle) == ([0.0, 1.0], [1.0, 2.0])
