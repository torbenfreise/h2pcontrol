import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Experiment
from h2pcontrol.controller.framework.parameters import ParamSpec, param
from h2pcontrol.controller.framework.scan import Axis, Scan


class ScanExperiment(Experiment):
    voltage = param(3.3, min=0.0, max=10.0, unit="V")
    frequency = param(1.0, min=0.0, max=100.0, unit="Hz")
    mode = param("fast", choices=("fast", "slow"))

    async def shot(self, ctx) -> pd.DataFrame:
        return pd.DataFrame({"reading": [1.0]})


class GroupedExperiment(Experiment):
    voltage = param(0.0, min=0.0, max=10.0, group="ramp")
    current = param(0.0, min=0.0, max=1.0, group="ramp")
    frequency = param(1.0, min=0.0, max=100.0)

    async def shot(self, ctx) -> pd.DataFrame:
        return pd.DataFrame({"reading": [1.0]})


class OtherExperiment(Experiment):
    voltage = param(1.0)  # same name, different experiment

    async def shot(self, ctx) -> pd.DataFrame:
        return pd.DataFrame({"reading": [1.0]})


class TestAxis:
    def test_values_linearly_spaced(self):
        ax = Axis(ScanExperiment.voltage, start=0.0, stop=1.0, steps=3)
        vals = list(ax.values)
        assert vals == pytest.approx([0.0, 0.5, 1.0])

    def test_name_resolves_from_spec(self):
        assert Axis(ScanExperiment.voltage, 0, 1, 2).name == "voltage"

    def test_detached_spec_has_no_name(self):
        with pytest.raises(ValueError, match="not attached"):
            _ = Axis(ParamSpec(default=0.0), 0, 1, 2).name

    def test_discrete_axis_values(self):
        ax = Axis(ScanExperiment.mode)
        assert list(ax.values) == ["fast", "slow"]

    def test_discrete_axis_is_discrete(self):
        assert Axis(ScanExperiment.mode).is_discrete

    def test_continuous_axis_is_not_discrete(self):
        assert not Axis(ScanExperiment.voltage, start=0, stop=1, steps=2).is_discrete

    def test_discrete_requires_choices(self):
        with pytest.raises(ValueError, match="no choices"):
            Axis(ScanExperiment.voltage)

    def test_partial_range_raises(self):
        with pytest.raises(ValueError, match="start, stop, and steps"):
            Axis(ScanExperiment.voltage, start=0.0)

    def test_centered_values(self):
        ax = Axis.centered(ScanExperiment.voltage, center=5.0, span=4.0, steps=5)
        vals = list(ax.values)
        assert vals == pytest.approx([3.0, 4.0, 5.0, 6.0, 7.0])

    def test_centered_is_not_discrete(self):
        assert not Axis.centered(ScanExperiment.voltage, 5.0, 4.0, 5).is_discrete

    def test_from_list_values(self):
        ax = Axis.from_list(ScanExperiment.voltage, [1.0, 3.0, 7.0])
        assert list(ax.values) == [1.0, 3.0, 7.0]

    def test_from_list_len(self):
        ax = Axis.from_list(ScanExperiment.voltage, [1.0, 2.0])
        assert len(ax) == 2

    def test_from_list_is_not_discrete(self):
        assert not Axis.from_list(ScanExperiment.voltage, [1.0]).is_discrete

    def test_from_list_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            Axis.from_list(ScanExperiment.voltage, [])

    def test_explicit_values_with_range_raises(self):
        with pytest.raises(ValueError, match="Cannot combine"):
            Axis(ScanExperiment.voltage, start=0, stop=1, steps=2, explicit_values=(1.0,))


class TestScan:
    def test_requires_at_least_one_axis(self):
        with pytest.raises(ValueError):
            Scan()

    def test_single_axis_len(self):
        scan = Scan(Axis(ScanExperiment.voltage, start=0, stop=1, steps=5))
        assert len(scan) == 5

    def test_multi_axis_len(self):
        scan = Scan(
            Axis(ScanExperiment.voltage, start=0, stop=1, steps=3),
            Axis(ScanExperiment.frequency, start=1, stop=10, steps=4),
        )
        assert len(scan) == 12

    def test_single_axis_points(self):
        scan = Scan(Axis(ScanExperiment.voltage, start=0.0, stop=1.0, steps=3))
        points = list(scan.points())
        assert len(points) == 3
        assert points[0] == {"voltage": pytest.approx(0.0)}
        assert points[1] == {"voltage": pytest.approx(0.5)}
        assert points[2] == {"voltage": pytest.approx(1.0)}

    def test_discrete_axis_points(self):
        scan = Scan(Axis(ScanExperiment.mode))
        points = list(scan.points())
        assert points == [{"mode": "fast"}, {"mode": "slow"}]

    def test_mixed_continuous_and_discrete(self):
        scan = Scan(
            Axis(ScanExperiment.voltage, start=0, stop=1, steps=2),
            Axis(ScanExperiment.mode),
        )
        points = list(scan.points())
        assert len(points) == 4
        assert points[0] == {"voltage": pytest.approx(0.0), "mode": "fast"}
        assert points[1] == {"voltage": pytest.approx(0.0), "mode": "slow"}
        assert points[2] == {"voltage": pytest.approx(1.0), "mode": "fast"}
        assert points[3] == {"voltage": pytest.approx(1.0), "mode": "slow"}

    def test_multi_axis_cartesian_product(self):
        scan = Scan(
            Axis(ScanExperiment.voltage, start=0, stop=1, steps=2),
            Axis(ScanExperiment.frequency, start=10, stop=20, steps=2),
        )
        points = list(scan.points())
        assert len(points) == 4
        assert points[0] == {"voltage": pytest.approx(0.0), "frequency": pytest.approx(10.0)}
        assert points[1] == {"voltage": pytest.approx(0.0), "frequency": pytest.approx(20.0)}
        assert points[2] == {"voltage": pytest.approx(1.0), "frequency": pytest.approx(10.0)}
        assert points[3] == {"voltage": pytest.approx(1.0), "frequency": pytest.approx(20.0)}


class TestScanGroups:
    def test_grouped_axes_are_zipped(self):
        scan = Scan(
            Axis(GroupedExperiment.voltage, start=0, stop=10, steps=3),
            Axis(GroupedExperiment.current, start=0, stop=1, steps=3),
        )
        points = list(scan.points())
        assert len(points) == 3
        assert points[0] == {"voltage": pytest.approx(0.0), "current": pytest.approx(0.0)}
        assert points[2] == {"voltage": pytest.approx(10.0), "current": pytest.approx(1.0)}

    def test_grouped_and_ungrouped_crossed(self):
        scan = Scan(
            Axis(GroupedExperiment.voltage, start=0, stop=10, steps=3),
            Axis(GroupedExperiment.current, start=0, stop=1, steps=3),
            Axis(GroupedExperiment.frequency, start=1, stop=10, steps=2),
        )
        points = list(scan.points())
        assert len(points) == 6  # 3 zipped x 2 ungrouped
        assert len(scan) == 6

    def test_mismatched_group_lengths_raises(self):
        scan = Scan(
            Axis(GroupedExperiment.voltage, start=0, stop=10, steps=3),
            Axis(GroupedExperiment.current, start=0, stop=1, steps=5),
        )
        with pytest.raises(ValueError, match="mismatched lengths"):
            list(scan.points())

    def test_mismatched_group_len_raises(self):
        scan = Scan(
            Axis(GroupedExperiment.voltage, start=0, stop=10, steps=3),
            Axis(GroupedExperiment.current, start=0, stop=1, steps=5),
        )
        with pytest.raises(ValueError, match="mismatched lengths"):
            len(scan)

    def test_ungrouped_axes_still_crossed(self):
        """Axes without a group are crossed."""
        scan = Scan(
            Axis(ScanExperiment.voltage, start=0, stop=1, steps=2),
            Axis(ScanExperiment.frequency, start=10, stop=20, steps=2),
        )
        points = list(scan.points())
        assert len(points) == 4


class TestScanValidation:
    def test_validate_for_accepts_declared_params(self):
        Scan(Axis(ScanExperiment.voltage, 0, 1, 2)).validate_for(ScanExperiment)

    def test_validate_for_accepts_inherited_params(self):
        class ChildExperiment(ScanExperiment):
            pass

        Scan(Axis(ScanExperiment.voltage, 0, 1, 2)).validate_for(ChildExperiment)

    def test_validate_for_rejects_foreign_spec(self):
        # same parameter name, but declared on a different experiment class
        with pytest.raises(ValueError, match="not parameters of"):
            Scan(Axis(OtherExperiment.voltage, 0, 1, 2)).validate_for(ScanExperiment)
