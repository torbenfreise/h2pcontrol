import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.ui.experiment_panel import ExperimentPanel, _ParamApplyError


class Exp(Experiment):
    voltage = param(3.3, min=0.0, max=5.0, unit="V")
    count = param(10, min=1, max=100)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame()


class GroupedExp(Experiment):
    voltage = param(0.0, min=0.0, max=10.0, group="ramp")
    current = param(0.0, min=0.0, max=1.0, group="ramp")
    frequency = param(1.0, min=0.0, max=100.0)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame()


class MultiGroupExp(Experiment):
    voltage = param(0.0, min=0.0, max=10.0, group="ramp")
    current = param(0.0, min=0.0, max=1.0, group="ramp")
    freq = param(1.0, min=0.0, max=100.0, group="rf")
    power = param(0.0, min=-10.0, max=10.0, group="rf")
    gain = param(1.0, min=0.0, max=10.0)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame()


@pytest.fixture
def panel(qtbot):
    p = ExperimentPanel()
    qtbot.addWidget(p)
    p.load_experiment(Exp)
    return p


@pytest.fixture
def grouped_panel(qtbot):
    p = ExperimentPanel()
    qtbot.addWidget(p)
    p.load_experiment(GroupedExp)
    return p


@pytest.fixture
def multi_group_panel(qtbot):
    p = ExperimentPanel()
    qtbot.addWidget(p)
    p.load_experiment(MultiGroupExp)
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


def test_initialise_raises_when_no_experiment_loaded(qtbot):
    panel = ExperimentPanel()
    qtbot.addWidget(panel)
    with pytest.raises(RuntimeError, match="No experiment loaded"):
        panel.initialise_experiment()


# ------------------------------------------------------------------
# Scan mode dropdown
# ------------------------------------------------------------------


def test_default_mode_is_fixed(panel):
    row = panel._rows["voltage"]
    assert row._mode.currentText() == "Fixed"
    assert not row.is_scan_axis()


def test_linear_mode_produces_axis(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("Linear")
    assert row.is_scan_axis()
    ax = row.get_axis()
    assert ax.start is not None and ax.stop is not None and ax.steps is not None


def test_centered_mode_produces_axis(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("Centered")
    row._center.setValue(2.5)
    row._span.setValue(2.0)
    row._center_steps.setValue(5)
    ax = row.get_axis()
    vals = list(ax.values)
    assert vals == pytest.approx([1.5, 2.0, 2.5, 3.0, 3.5])


def test_list_mode_produces_axis(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("List")
    row._list_edit.setText("1.0, 2.5, 4.0")
    ax = row.get_axis()
    assert list(ax.values) == pytest.approx([1.0, 2.5, 4.0])


def test_no_scan_when_all_fixed(panel):
    assert panel.get_scan() is None


def test_scan_returned_when_axis_active(panel):
    panel._rows["voltage"]._mode.setCurrentText("Linear")
    scan = panel.get_scan()
    assert scan is not None
    assert len(scan.axes) == 1


# ------------------------------------------------------------------
# Group validation
# ------------------------------------------------------------------


def test_partial_group_without_zip_is_ok(grouped_panel):
    """Without zip checked, partial group scanning is allowed (crossed)."""
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    scan = grouped_panel.get_scan()
    assert scan is not None


def test_partial_group_with_zip_raises(grouped_panel):
    """With zip checked, all params in the group must be scanned."""
    grouped_panel._zip_checks["ramp"].setChecked(True)
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    # current is still Fixed
    with pytest.raises(_ParamApplyError, match="ramp"):
        grouped_panel.get_scan()


def test_full_group_zipped(grouped_panel):
    grouped_panel._zip_checks["ramp"].setChecked(True)
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    grouped_panel._rows["current"]._mode.setCurrentText("Linear")
    scan = grouped_panel.get_scan()
    assert scan is not None
    assert len(scan.axes) == 2


def test_zipped_group_produces_fewer_shots(grouped_panel):
    """Zipped: 10 shots (lockstep). Crossed: 10*10 = 100 shots."""
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    grouped_panel._rows["current"]._mode.setCurrentText("Linear")

    # Without zip: crossed → 10 * 10 = 100
    scan_crossed = grouped_panel.get_scan()
    assert len(scan_crossed) == 100

    # With zip: lockstep → 10
    grouped_panel._zip_checks["ramp"].setChecked(True)
    scan_zipped = grouped_panel.get_scan()
    assert len(scan_zipped) == 10


def test_zipped_group_points_are_lockstep(grouped_panel):
    """Zipped axes should step together, not form a cartesian product."""
    grouped_panel._zip_checks["ramp"].setChecked(True)
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    grouped_panel._rows["voltage"]._steps.setValue(3)
    grouped_panel._rows["current"]._mode.setCurrentText("Linear")
    grouped_panel._rows["current"]._steps.setValue(3)
    scan = grouped_panel.get_scan()
    points = list(scan.points())
    assert len(points) == 3
    # Each point should have both voltage and current set together
    for pt in points:
        assert "voltage" in pt
        assert "current" in pt


# ------------------------------------------------------------------
# Multiple groups
# ------------------------------------------------------------------


def test_multi_group_both_zipped(multi_group_panel):
    """Two zipped groups crossed with each other: 10 * 10 = 100."""
    multi_group_panel._zip_checks["ramp"].setChecked(True)
    multi_group_panel._zip_checks["rf"].setChecked(True)
    multi_group_panel._rows["voltage"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["current"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["freq"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["power"]._mode.setCurrentText("Linear")
    scan = multi_group_panel.get_scan()
    # ramp zipped: 10, rf zipped: 10, crossed: 10 * 10 = 100
    assert len(scan) == 100


def test_multi_group_one_zipped_one_not(multi_group_panel):
    """One group zipped, the other crossed: 10 * 10 * 10 = 1000."""
    multi_group_panel._zip_checks["ramp"].setChecked(True)
    # rf NOT zipped → freq and power are independent
    multi_group_panel._rows["voltage"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["current"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["freq"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["power"]._mode.setCurrentText("Linear")
    scan = multi_group_panel.get_scan()
    # ramp zipped: 10, freq: 10, power: 10, crossed: 10 * 10 * 10 = 1000
    assert len(scan) == 1000


def test_multi_group_with_ungrouped(multi_group_panel):
    """Zipped group + ungrouped param: crossed."""
    multi_group_panel._zip_checks["ramp"].setChecked(True)
    multi_group_panel._rows["voltage"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["current"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["gain"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["gain"]._steps.setValue(5)
    scan = multi_group_panel.get_scan()
    # ramp zipped: 10, gain: 5, crossed: 10 * 5 = 50
    assert len(scan) == 50
