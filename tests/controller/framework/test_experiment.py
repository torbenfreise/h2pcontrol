import dataclasses

import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParameterError, ParamSpec, param


class SimpleExperiment(Experiment):
    voltage = param(3.3, min=0.0, max=5.0, unit="V")
    count = param(10, min=1, max=100)

    async def shot(self, ctx: "Context") -> pd.DataFrame:
        return pd.DataFrame({"reading": [1.0, 2.0]})


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
# Shot wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shot_wrapping_adds_params_and_preserves_results():
    exp = SimpleExperiment()
    df = await exp.shot(Context(shot_idx=0))

    # result columns are under "result"
    assert ("result", "reading") in df.columns

    # parameter columns are under "params"
    assert ("params", "voltage") in df.columns
    assert ("params", "count") in df.columns

    # values match
    assert list(df[("result", "reading")]) == [1.0, 2.0]
    assert df[("params", "voltage")].iloc[0] == 3.3
    assert df[("params", "count")].iloc[0] == 10


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

        async def shot(self, ctx: Context) -> pd.DataFrame:
            return pd.DataFrame({"x": [0.0]})

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

        async def shot(self, ctx: Context) -> pd.DataFrame:
            return pd.DataFrame({"x": [0.0]})

    assert Named().logger.name == "experiment.Rabi"


# ---------------------------------------------------------------------------
# ParameterError
# ---------------------------------------------------------------------------


def test_parameter_error_is_value_error():
    assert issubclass(ParameterError, ValueError)
    exc = ParameterError("test message")
    assert str(exc) == "test message"
