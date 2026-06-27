from typing import Literal

import pytest
import pandas as pd

from h2pcontrol.controller.framework.experiment import Experiment, Context
from h2pcontrol.controller.framework.parameters import param


class SimpleExperiment(Experiment):
    voltage: float = param(3.3, min=0.0, max=5.0, unit="V")
    count: int = param(10, min=1, max=100)

    async def shot(self, ctx: "Context") -> pd.DataFrame:
        return pd.DataFrame({"reading": [1.0, 2.0]})


# ---------------------------------------------------------------------------
# Basic parameter registration
# ---------------------------------------------------------------------------


def test_parameters_registered():
    assert "voltage" in SimpleExperiment._parameters
    assert "count" in SimpleExperiment._parameters


def test_dtype_inferred_from_annotation():
    assert SimpleExperiment._parameters["voltage"].dtype is float
    assert SimpleExperiment._parameters["count"].dtype is int


def test_class_attribute_set_to_default():
    assert SimpleExperiment.voltage == 3.3
    assert SimpleExperiment.count == 10


def test_instance_has_default():
    exp = SimpleExperiment()
    assert exp.voltage == 3.3
    assert exp.count == 10

# ---------------------------------------------------------------------------
# __setattr__ validation
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
