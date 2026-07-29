import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParameterError, param
from h2pcontrol.controller.runtime.spec import CenteredAxis, LinearAxis, ListAxis
from h2pcontrol.controller.ui.experiment_panel import ExperimentPanel


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


# ------------------------------------------------------------------
# scan-change notification (drives the adaptive run controls)
# ------------------------------------------------------------------


def test_has_scan_axis_tracks_row_mode(panel):
    assert not panel.has_scan_axis()
    panel._rows["voltage"]._mode.setCurrentText("Linear")
    assert panel.has_scan_axis()
    panel._rows["voltage"]._mode.setCurrentText("Fixed")
    assert not panel.has_scan_axis()


def test_scan_changed_emitted_on_mode_toggle(qtbot, panel):
    with qtbot.waitSignal(panel.scan_changed, timeout=1000):
        panel._rows["voltage"]._mode.setCurrentText("Linear")


def test_scan_changed_emitted_on_load(qtbot):
    p = ExperimentPanel()
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.scan_changed, timeout=1000):
        p.load_experiment(Exp)


# ------------------------------------------------------------------
# current_values
# ------------------------------------------------------------------


def test_current_values_uses_defaults(panel):
    values = panel.current_values()
    assert values["voltage"] == 3.3
    assert values["count"] == 10


def test_current_values_applies_edited_values(panel):
    panel._rows["voltage"]._single.setText("4.0")
    panel._rows["count"]._single.setText("50")
    values = panel.current_values()
    assert values["voltage"] == 4.0
    assert values["count"] == 50


def test_current_values_raises_on_invalid_value(panel):
    panel._rows["voltage"]._single.setText("999")
    with pytest.raises(ParameterError, match="voltage"):
        panel.current_values()


def test_row_value_validates_bounds(panel):
    """row.value() must itself enforce parameter bounds (raise ParameterError),
    not merely coerce the type."""
    panel._rows["voltage"]._single.setText("999")
    with pytest.raises(ParameterError, match="voltage"):
        panel._rows["voltage"].value()


def test_current_values_raises_when_no_experiment_loaded(qtbot):
    panel = ExperimentPanel()
    qtbot.addWidget(panel)
    with pytest.raises(RuntimeError, match="No experiment loaded"):
        panel.current_values()


def test_current_values_excludes_scan_axes(panel):
    panel._rows["voltage"]._mode.setCurrentText("Linear")
    values = panel.current_values()
    assert "voltage" not in values
    assert "count" in values


# ------------------------------------------------------------------
# Scan mode dropdown
# ------------------------------------------------------------------


def test_default_mode_is_fixed(panel):
    row = panel._rows["voltage"]
    assert row._mode.currentText() == "Fixed"
    assert not row.is_scan_axis()


def test_linear_mode_produces_axis_spec(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("Linear")
    assert row.is_scan_axis()
    spec = row.get_axis_spec()
    assert isinstance(spec, LinearAxis)
    assert spec.param == "voltage"


def test_centered_mode_produces_axis_spec(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("Centered")
    row._center.setValue(2.5)
    row._span.setValue(2.0)
    row._center_steps.setValue(5)
    spec = row.get_axis_spec()
    assert isinstance(spec, CenteredAxis)
    assert spec.center == 2.5
    assert spec.span == 2.0
    assert spec.steps == 5


def test_list_mode_produces_axis_spec(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("List")
    row._list_edit.setText("1.0, 2.5, 4.0")
    spec = row.get_axis_spec()
    assert isinstance(spec, ListAxis)
    assert spec.values == pytest.approx((1.0, 2.5, 4.0))


def test_list_mode_invalid_text_raises_parameter_error(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("List")
    row._list_edit.setText("1, 2, foo")
    with pytest.raises(ParameterError, match="voltage"):
        panel.current_scan_spec()


def test_get_axis_spec_invalid_list_raises_parameter_error(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("List")
    row._list_edit.setText("1, 2, foo")
    with pytest.raises(ParameterError, match="voltage"):
        row.get_axis_spec()


def test_current_scan_spec_rejects_out_of_bounds_list(panel):
    row = panel._rows["voltage"]
    row._mode.setCurrentText("List")
    row._list_edit.setText("1, 999")
    with pytest.raises(ParameterError, match="voltage"):
        panel.current_scan_spec()


def test_linear_spinboxes_clamped_to_param_bounds(panel):
    row = panel._rows["voltage"]  # voltage: min=0.0, max=5.0
    assert row._start.minimum() == pytest.approx(0.0)
    assert row._start.maximum() == pytest.approx(5.0)
    assert row._stop.minimum() == pytest.approx(0.0)
    assert row._stop.maximum() == pytest.approx(5.0)
    assert row._center.minimum() == pytest.approx(0.0)
    assert row._center.maximum() == pytest.approx(5.0)


# ------------------------------------------------------------------
# Live field validation
# ------------------------------------------------------------------


def test_fixed_field_live_validation(panel):
    row = panel._rows["voltage"]  # min 0, max 5
    row._single.setText("999")  # out of bounds
    assert "red" in row._single.styleSheet()
    row._single.setText("3.0")  # valid
    assert row._single.styleSheet() == ""


def test_list_field_live_validation(panel):
    row = panel._rows["voltage"]  # min 0, max 5
    row._mode.setCurrentText("List")
    row._list_edit.setText("1, foo")  # unparseable
    assert "red" in row._list_edit.styleSheet()
    row._list_edit.setText("1, 2, 3")  # valid
    assert row._list_edit.styleSheet() == ""
    row._list_edit.setText("999")  # out of bounds
    assert "red" in row._list_edit.styleSheet()
    row._list_edit.setText("")  # empty list is not a valid scan
    assert "red" in row._list_edit.styleSheet()


def test_centered_field_live_validation(panel):
    row = panel._rows["voltage"]  # min 0, max 5
    row._mode.setCurrentText("Centered")
    row._center.setValue(4.0)
    row._span.setValue(4.0)  # 4 ± 2 = [2, 6] → 6 > 5
    assert "red" in row._span.styleSheet()
    row._span.setValue(2.0)  # 4 ± 1 = [3, 5] → in bounds
    assert row._span.styleSheet() == ""


def test_centered_default_is_schedulable(panel):
    panel._rows["voltage"]._mode.setCurrentText("Centered")
    assert panel.current_scan_spec() is not None


def test_no_scan_when_all_fixed(panel):
    assert panel.current_scan_spec() is None


def test_scan_returned_when_axis_active(panel):
    panel._rows["voltage"]._mode.setCurrentText("Linear")
    scan_spec = panel.current_scan_spec()
    assert scan_spec is not None
    assert len(scan_spec.axes) == 1


# ------------------------------------------------------------------
# Group validation
# ------------------------------------------------------------------


def test_partial_group_without_zip_is_ok(grouped_panel):
    """Without zip checked, partial group scanning is allowed (crossed)."""
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    scan_spec = grouped_panel.current_scan_spec()
    assert scan_spec is not None


def test_partial_group_with_zip_raises(grouped_panel):
    """With zip checked, all params in the group must be scanned."""
    grouped_panel._zip_checks["ramp"].setChecked(True)
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    with pytest.raises(ParameterError, match="ramp"):
        grouped_panel.current_scan_spec()


def test_current_scan_spec_rejects_mismatched_zip_lengths(grouped_panel):
    """Zipped axes of unequal length must be rejected at schedule time."""
    grouped_panel._zip_checks["ramp"].setChecked(True)
    for name, steps in (("voltage", 10), ("current", 9)):
        grouped_panel._rows[name]._mode.setCurrentText("Linear")
        grouped_panel._rows[name]._steps.setValue(steps)
    with pytest.raises(ParameterError, match="mismatched"):
        grouped_panel.current_scan_spec()


def test_full_group_zipped(grouped_panel):
    grouped_panel._zip_checks["ramp"].setChecked(True)
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    grouped_panel._rows["current"]._mode.setCurrentText("Linear")
    scan_spec = grouped_panel.current_scan_spec()
    assert scan_spec is not None
    assert len(scan_spec.axes) == 2


def test_zipped_group_produces_fewer_shots(grouped_panel):
    """Zipped: 10 shots (lockstep). Crossed: 10*10 = 100 shots."""
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    grouped_panel._rows["current"]._mode.setCurrentText("Linear")

    # Without zip: crossed → 10 * 10 = 100
    scan_spec = grouped_panel.current_scan_spec()
    scan_crossed = scan_spec.to_scan(GroupedExp)
    assert len(scan_crossed) == 100

    # With zip: lockstep → 10
    grouped_panel._zip_checks["ramp"].setChecked(True)
    scan_spec = grouped_panel.current_scan_spec()
    scan_zipped = scan_spec.to_scan(GroupedExp)
    assert len(scan_zipped) == 10


def test_zipped_group_points_are_lockstep(grouped_panel):
    """Zipped axes should step together, not form a cartesian product."""
    grouped_panel._zip_checks["ramp"].setChecked(True)
    grouped_panel._rows["voltage"]._mode.setCurrentText("Linear")
    grouped_panel._rows["voltage"]._steps.setValue(3)
    grouped_panel._rows["current"]._mode.setCurrentText("Linear")
    grouped_panel._rows["current"]._steps.setValue(3)
    scan_spec = grouped_panel.current_scan_spec()
    scan = scan_spec.to_scan(GroupedExp)
    points = list(scan.points())
    assert len(points) == 3
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
    scan_spec = multi_group_panel.current_scan_spec()
    scan = scan_spec.to_scan(MultiGroupExp)
    assert len(scan) == 100


def test_multi_group_one_zipped_one_not(multi_group_panel):
    """One group zipped, the other crossed: 10 * 10 * 10 = 1000."""
    multi_group_panel._zip_checks["ramp"].setChecked(True)
    multi_group_panel._rows["voltage"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["current"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["freq"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["power"]._mode.setCurrentText("Linear")
    scan_spec = multi_group_panel.current_scan_spec()
    scan = scan_spec.to_scan(MultiGroupExp)
    assert len(scan) == 1000


def test_multi_group_with_ungrouped(multi_group_panel):
    """Zipped group + ungrouped param: crossed."""
    multi_group_panel._zip_checks["ramp"].setChecked(True)
    multi_group_panel._rows["voltage"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["current"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["gain"]._mode.setCurrentText("Linear")
    multi_group_panel._rows["gain"]._steps.setValue(5)
    scan_spec = multi_group_panel.current_scan_spec()
    scan = scan_spec.to_scan(MultiGroupExp)
    assert len(scan) == 50
