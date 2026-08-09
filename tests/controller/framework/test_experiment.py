import dataclasses

import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParameterError, ParamSpec, param
from h2pcontrol.controller.framework.results import Results, result


class SimpleExperiment(Experiment):
    voltage = param(3.3, min=0.0, max=5.0, unit="V")
    count = param(10, min=1, max=100)

    class Record(Results):
        reading: float = result()

    async def shot(self, ctx: "Context") -> list[Record]:
        return [self.Record(reading=1.0), self.Record(reading=2.0)]


# ---------------------------------------------------------------------------
# Basic parameter registration
# ---------------------------------------------------------------------------


def test_parameters_registered():
    assert "voltage" in SimpleExperiment.parameters()
    assert "count" in SimpleExperiment.parameters()


def test_dtype_inferred_from_default():
    assert SimpleExperiment.parameters()["voltage"].dtype is float
    assert SimpleExperiment.parameters()["count"].dtype is int


def test_class_access_returns_spec():
    # descriptor protocol: class access yields the ParamSpec (typed axis refs)
    assert isinstance(SimpleExperiment.voltage, ParamSpec)
    assert SimpleExperiment.voltage.default == 3.3
    assert SimpleExperiment.voltage.name == "voltage"
    assert SimpleExperiment.count.default == 10


def test_instance_has_default():
    exp = SimpleExperiment()
    assert exp.voltage == 3.3
    assert exp.count == 10


def test_instance_value_does_not_leak_between_instances():
    a, b = SimpleExperiment(), SimpleExperiment()
    a.voltage = 1.5
    assert b.voltage == 3.3


# ---------------------------------------------------------------------------
# descriptor __set__ validation
# ---------------------------------------------------------------------------


def test_setattr_coerces_type():
    exp = SimpleExperiment()
    exp.voltage = 1  # int assigned to float param
    assert isinstance(exp.voltage, float)
    assert exp.voltage == 1.0


def test_setattr_rejects_out_of_bounds():
    exp = SimpleExperiment()
    with pytest.raises(ValueError):
        exp.voltage = 6.0


# ---------------------------------------------------------------------------
# Record assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_adds_params_and_preserves_results():
    exp = SimpleExperiment()
    df = await exp.record(Context(shot_idx=0))

    # result columns are under "result"
    assert ("result", "reading") in df.columns

    # parameter columns are under "params"
    assert ("params", "voltage") in df.columns
    assert ("params", "count") in df.columns

    # values match
    assert list(df[("result", "reading")]) == [1.0, 2.0]
    assert df[("params", "voltage")].iloc[0] == 3.3
    assert df[("params", "count")].iloc[0] == 10


@pytest.mark.asyncio
async def test_record_broadcasts_params_over_all_rows():
    # A shot may return one row per hardware trigger; every row must carry
    # the full parameter set (no NaN padding on rows past the first).
    class BatchedExperiment(Experiment):
        voltage = param(3.3, min=0.0, max=5.0, unit="V")

        class Record(Results):
            rep: int = result()
            reading: float = result()

        async def shot(self, ctx: Context) -> list[Record]:
            return [self.Record(rep=i, reading=r) for i, r in enumerate([0.1, 0.2, 0.3, 0.4, 0.5])]

    df = await BatchedExperiment().record(Context(shot_idx=0))

    assert len(df) == 5
    assert list(df[("params", "voltage")]) == [3.3] * 5
    assert not df.isna().any().any()


@pytest.mark.asyncio
async def test_record_every_row_carries_every_column():
    # A record row always carries all declared columns, so a shot cannot produce
    # a ragged frame — the row-count / column-set mismatch failure mode is gone.
    class BatchedExperiment(Experiment):
        class Record(Results):
            a: float = result()
            b: float = result()

        async def shot(self, ctx: Context) -> list[Record]:
            return [self.Record(a=1.0, b=1.0), self.Record(a=2.0, b=2.0)]

    df = await BatchedExperiment().record(Context(shot_idx=0))
    assert len(df) == 2
    assert list(df[("result", "a")]) == [1.0, 2.0]
    assert list(df[("result", "b")]) == [1.0, 2.0]


@pytest.mark.asyncio
async def test_record_view_only_shot_is_empty():
    # An experiment that declares no record and returns [] records zero rows.
    class ViewOnly(Experiment):
        voltage = param(1.0)

        async def shot(self, ctx: Context) -> list[Results]:
            return []

    df = await ViewOnly().record(Context(shot_idx=0))
    assert len(df) == 0


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def test_context_is_frozen():
    ctx = Context(shot_idx=0, run_id="abc", total_shots=5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.shot_idx = 1  # type: ignore[misc]


def test_context_defaults():
    ctx = Context(shot_idx=3)
    assert ctx.run_id == ""
    assert ctx.total_shots is None


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teardown_is_awaitable_noop():
    exp = SimpleExperiment()
    result = await exp.teardown()
    assert result is None


# ---------------------------------------------------------------------------
# metadata hook
# ---------------------------------------------------------------------------


def test_metadata_default_is_empty():
    assert SimpleExperiment().metadata() == {}


def test_metadata_override_is_returned():
    class WithMeta(Experiment):
        def metadata(self):
            return {"sample_interval_ns": "8.0"}

        async def shot(self, ctx: Context) -> list[Results]:
            return []

    assert WithMeta().metadata() == {"sample_interval_ns": "8.0"}


# ---------------------------------------------------------------------------
# parameters() classmethod
# ---------------------------------------------------------------------------


def test_parameters_returns_readonly_mapping():
    params = SimpleExperiment.parameters()
    assert "voltage" in params
    assert "count" in params
    with pytest.raises(TypeError):
        params["voltage"] = None  # type: ignore[index]


def test_parameters_includes_inherited():
    class Child(SimpleExperiment):
        extra = param(0.0, min=-1.0, max=1.0)
        # inherits SimpleExperiment.shot / Record

    child_params = Child.parameters()
    assert "voltage" in child_params
    assert "count" in child_params
    assert "extra" in child_params


# ---------------------------------------------------------------------------
# logger property
# ---------------------------------------------------------------------------


def test_logger_uses_class_name_when_name_unset():
    exp = SimpleExperiment()
    assert exp.logger.name == "experiment.SimpleExperiment"


def test_logger_uses_name_when_set():
    class Named(Experiment):
        name = "Rabi"

        class Record(Results):
            x: float = result()

        async def shot(self, ctx: Context) -> list[Record]:
            return [self.Record(x=0.0)]

    assert Named().logger.name == "experiment.Rabi"


# ---------------------------------------------------------------------------
# ParameterError
# ---------------------------------------------------------------------------


def test_parameter_error_is_value_error():
    assert issubclass(ParameterError, ValueError)
    exc = ParameterError("test message")
    assert str(exc) == "test message"
