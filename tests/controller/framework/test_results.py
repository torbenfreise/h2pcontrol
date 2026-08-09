from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import Results, ResultSpec, result


class ExpA(Experiment):
    name = "A"
    volts = param(1.0, min=0.0, max=5.0, unit="V")

    class Record(Results):
        a: float = result(unit="V", description="amp")
        b: np.ndarray = result()

    async def shot(self, ctx: Context) -> list[Record]:
        return [self.Record(a=0.0, b=np.zeros(3))]


class ExpChild(ExpA):
    # extends the parent record with an extra column; inherits shot()
    class Record(ExpA.Record):
        c: int = result()


# ---------------------------------------------------------------------------
# result() factory
# ---------------------------------------------------------------------------


def test_result_returns_dataclass_field_with_metadata():
    f = result(unit="V", description="amp")
    assert isinstance(f, dataclasses.Field)
    assert f.metadata["unit"] == "V"
    assert f.metadata["description"] == "amp"


def test_result_metadata_defaults_to_none():
    f = result()
    assert f.metadata["unit"] is None
    assert f.metadata["description"] is None


# ---------------------------------------------------------------------------
# a Results subclass is a dataclass whose fields are the columns
# ---------------------------------------------------------------------------


def test_record_is_dataclass_and_constructs_from_fields():
    assert dataclasses.is_dataclass(ExpA.Record)
    r = ExpA.Record(a=1.5, b=np.zeros(2))
    assert r.a == 1.5
    assert r.b.shape == (2,)


# ---------------------------------------------------------------------------
# specs(): storage schema resolved from annotations + result() metadata
# ---------------------------------------------------------------------------


def test_specs_carry_dtype_unit_description():
    specs = ExpA.Record.specs()
    assert set(specs) == {"a", "b"}
    assert specs["a"] == ResultSpec(float, "V", "amp", name="a")
    assert specs["b"].dtype is np.ndarray


def test_specs_is_array_only_for_ndarray():
    specs = ExpA.Record.specs()
    assert specs["a"].is_array is False
    assert specs["b"].is_array is True


# ---------------------------------------------------------------------------
# to_frame(): one column per field, in declaration order; empty stays columned
# ---------------------------------------------------------------------------


def test_to_frame_builds_columns_in_field_order():
    rows = [ExpA.Record(a=1.0, b=np.zeros(3)), ExpA.Record(a=2.0, b=np.ones(3))]
    df = ExpA.Record.to_frame(rows)
    assert list(df.columns) == ["a", "b"]
    assert list(df["a"]) == [1.0, 2.0]
    assert len(df) == 2
    assert df["b"].iloc[0].shape == (3,)


def test_to_frame_empty_keeps_declared_columns():
    df = ExpA.Record.to_frame([])
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 0


# ---------------------------------------------------------------------------
# collection on the experiment
# ---------------------------------------------------------------------------


def test_results_collected_with_names():
    assert set(ExpA.results()) == {"a", "b"}
    assert ExpA.results()["a"].name == "a"
    assert ExpA.results()["a"].unit == "V"


def test_results_inherited_via_record_subclass():
    assert set(ExpChild.results()) == {"a", "b", "c"}
    # parent is untouched
    assert set(ExpA.results()) == {"a", "b"}


def test_result_view_is_read_only():
    with pytest.raises(TypeError):
        ExpA.results()["a"] = ResultSpec(float)  # type: ignore[index]


def test_experiment_without_record_has_no_results():
    class ViewOnly(Experiment):
        name = "view-only"

        async def shot(self, ctx: Context) -> list[Results]:
            return []

    assert dict(ViewOnly.results()) == {}
