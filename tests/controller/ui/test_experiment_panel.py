import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.ui.experiment_panel import ExperimentPanel, _ParamApplyError


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class Exp(Experiment):
    voltage: float = param(3.3, min=0.0, max=5.0, unit="V")
    count: int = param(10, min=1, max=100)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame()


@pytest.fixture
def panel(qapp):
    p = ExperimentPanel()
    p.load_experiment(Exp)
    return p


def test_initialise_uses_defaults(panel):
    exp = panel.initialise_experiment()
    assert exp.voltage == 3.3
    assert exp.count == 10


def test_initialise_applies_edited_values(panel):
    panel._rows["voltage"]._single.setText("4.0")
    panel._rows["count"]._single.setText("50")
    exp = panel.initialise_experiment()
    assert exp.voltage == 4.0
    assert exp.count == 50


def test_initialise_raises_on_invalid_value(panel):
    panel._rows["voltage"]._single.setText("999")
    with pytest.raises(_ParamApplyError, match="voltage"):
        panel.initialise_experiment()


def test_initialise_raises_when_no_experiment_loaded(qapp):
    panel = ExperimentPanel()
    with pytest.raises(RuntimeError, match="No experiment loaded"):
        panel.initialise_experiment()