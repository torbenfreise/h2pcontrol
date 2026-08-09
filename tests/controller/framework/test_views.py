from __future__ import annotations

import threading

import numpy as np
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.views import ViewHandle, ViewKind


class Exp(Experiment):
    name = "Exp"

    class Record(Results):
        x: float = result()

    async def shot(self, ctx: Context) -> list[Record]:
        return [self.Record(x=0.0)]


# ---------------------------------------------------------------------------
# view() declaration + handle identity
# ---------------------------------------------------------------------------


def test_view_returns_handle_and_records_it():
    e = Exp()
    handle = e.view("Trace", x=np.arange(3.0), unit="V")
    assert isinstance(handle, ViewHandle)
    assert e.views() == (handle,)


def test_views_preserve_declaration_order():
    e = Exp()
    first = e.view("First", kind=ViewKind.SERIES)
    second = e.view("Second", x=np.arange(2.0))
    assert e.views() == (first, second)


def test_views_isolated_per_instance():
    e1, e2 = Exp(), Exp()
    e1.view("Trace", kind=ViewKind.SERIES)
    assert len(e1.views()) == 1
    assert e2.views() == ()


def test_kind_inferred_line_when_x_given():
    e = Exp()
    assert e.view("Trace", x=np.arange(3.0)).spec.kind is ViewKind.LINE


def test_kind_inferred_series_without_x():
    e = Exp()
    assert e.view("Points").spec.kind is ViewKind.SERIES


def test_kind_explicit_override():
    e = Exp()
    assert e.view("Points", kind=ViewKind.SERIES).spec.kind is ViewKind.SERIES


def test_view_stores_x_as_array():
    e = Exp()
    spec = e.view("Trace", x=[0.0, 1.0, 2.0], x_unit="us", unit="V").spec
    assert isinstance(spec.x, np.ndarray)
    assert list(spec.x) == [0.0, 1.0, 2.0]
    assert spec.x_unit == "us"
    assert spec.unit == "V"


# ---------------------------------------------------------------------------
# push() — the dirty-buffer contract
# ---------------------------------------------------------------------------


def test_push_line_replaces_curve_and_marks_dirty():
    handle = Exp().view("Trace", x=np.arange(3.0))
    assert not handle.dirty
    handle.push(np.array([1.0, 2.0, 3.0]))
    assert handle.dirty
    assert handle.line is not None
    assert list(handle.line) == [1.0, 2.0, 3.0]

    handle.push(np.array([4.0, 5.0, 6.0]))  # replaces, not appends
    assert handle.line is not None
    assert list(handle.line) == [4.0, 5.0, 6.0]


def test_push_series_accumulates_points():
    handle = Exp().view("Points", kind=ViewKind.SERIES)
    handle.push(0.0, 1.0)
    handle.push(1.0, 2.0)
    xs, ys = handle.series
    assert xs == [0.0, 1.0]
    assert ys == [1.0, 2.0]


def test_push_does_not_repaint_only_sets_dirty():
    """push() is a buffer write + dirty flag; drawing happens elsewhere on a timer.

    The buffer is the only state a push touches, so a caller that never reads it
    (as the UI does only on its repaint tick) sees nothing but the dirty flag.
    """
    handle = Exp().view("Points", kind=ViewKind.SERIES)
    for i in range(50):
        handle.push(float(i), float(i))
    # 50 pushes, still just one pending repaint's worth of state: the dirty flag
    # is set once and all points are buffered, none drawn.
    assert handle.dirty
    assert len(handle.series[0]) == 50


def test_clear_dirty_resets_flag_but_keeps_buffer():
    handle = Exp().view("Trace", x=np.arange(2.0))
    handle.push(np.array([1.0, 2.0]))
    handle.clear_dirty()
    assert not handle.dirty
    assert handle.line is not None
    assert list(handle.line) == [1.0, 2.0]  # buffer survives


def test_push_records_thread():
    handle = Exp().view("Points", kind=ViewKind.SERIES)
    assert handle.push_thread is None
    handle.push(0.0, 1.0)
    assert handle.push_thread == threading.get_ident()


def test_line_push_rejects_two_args():
    handle = Exp().view("Trace", x=np.arange(2.0))
    with pytest.raises(ValueError):
        handle.push(1.0, 2.0)
