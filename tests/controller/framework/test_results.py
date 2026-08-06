from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import (
    PlotError,
    PlotKind,
    PlotSpec,
    ResultSpec,
    result,
)


class ExpA(Experiment):
    name = "A"
    volts = param(1.0, min=0.0, max=5.0, unit="V")
    a = result(float, unit="V", description="amp")
    b = result(np.ndarray)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame({"a": [0.0], "b": [np.zeros(3)]})


class ExpChild(ExpA):
    c = result(int)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame({"a": [0.0], "b": [np.zeros(3)], "c": [1]})


class Other(Experiment):
    name = "Other"
    z = result(float)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame({"z": [0.0]})


# ---------------------------------------------------------------------------
# result() factory + collection
# ---------------------------------------------------------------------------


def test_result_returns_spec_with_fields():
    r = result(float, unit="V", description="amp")
    assert isinstance(r, ResultSpec)
    assert r.dtype is float
    assert r.unit == "V"
    assert r.description == "amp"


def test_results_collected_with_names():
    assert set(ExpA.results()) == {"a", "b"}
    assert ExpA.results()["a"].name == "a"
    assert ExpA.results()["a"].unit == "V"


def test_results_inherited():
    assert set(ExpChild.results()) == {"a", "b", "c"}
    # parent is untouched
    assert set(ExpA.results()) == {"a", "b"}


def test_result_view_is_read_only():
    with pytest.raises(TypeError):
        ExpA.results()["a"] = result(float)  # type: ignore[index]


# ---------------------------------------------------------------------------
# plot()
# ---------------------------------------------------------------------------


def test_plot_appends_spec():
    e = ExpA()
    e.plot(e.a, x=e.b, title="T")
    plots = e.plots()
    assert len(plots) == 1
    assert plots[0].ys == (ExpA.a,)
    assert plots[0].x is ExpA.b
    assert plots[0].title == "T"


def test_plot_accepts_param_as_x_via_class_access():
    e = ExpA()
    e.plot(e.a, x=ExpA.volts)
    assert e.plots()[0].x is ExpA.volts


def test_plots_isolated_per_instance():
    e1, e2 = ExpA(), ExpA()
    e1.plot(e1.a)
    assert len(e1.plots()) == 1
    assert e2.plots() == ()


def test_plot_requires_a_y():
    with pytest.raises(PlotError):
        ExpA().plot()


def test_plot_rejects_foreign_result_as_y():
    with pytest.raises(PlotError):
        ExpA().plot(Other.z)


def test_plot_rejects_foreign_spec_as_x():
    with pytest.raises(PlotError):
        ExpA().plot(ExpA.a, x=Other.z)


# ---------------------------------------------------------------------------
# PlotSpec.resolve_kind
# ---------------------------------------------------------------------------


def test_resolve_kind_series_for_scalar():
    assert PlotSpec(ys=(ExpA.a,)).resolve_kind() is PlotKind.SERIES


def test_resolve_kind_line_for_array():
    assert PlotSpec(ys=(ExpA.b,)).resolve_kind() is PlotKind.LINE


def test_resolve_kind_explicit_override():
    assert PlotSpec(ys=(ExpA.b,), kind=PlotKind.SERIES).resolve_kind() is PlotKind.SERIES
