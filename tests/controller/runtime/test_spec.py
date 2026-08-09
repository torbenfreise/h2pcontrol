import pickle
from pathlib import Path

import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParameterError, param
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.runtime.spec import (
    CenteredAxis,
    ChoicesAxis,
    LinearAxis,
    ListAxis,
    RunRequest,
    ScanSpec,
)


class SpecExperiment(Experiment):
    voltage = param(3.3, min=0.0, max=5.0, unit="V", group="ramp")
    current = param(1.0, min=0.0, max=10.0, unit="A", group="ramp")
    delay = param(0.1, min=0.0, max=5.0, unit="s")
    mode = param("fast", choices=("fast", "slow"))

    class Record(Results):
        x: float = result()

    async def shot(self, ctx: Context) -> list[Record]:
        return [self.Record(x=0.0)]


# ---------------------------------------------------------------------------
# AxisSpec.to_axis round-trips
# ---------------------------------------------------------------------------


class TestAxisSpecLinear:
    def test_resolves_to_axis(self):
        spec = LinearAxis(param="voltage", start=0.0, stop=5.0, steps=6)
        axis = spec.to_axis(SpecExperiment)
        assert len(axis) == 6
        assert axis.values[0] == pytest.approx(0.0)
        assert axis.values[-1] == pytest.approx(5.0)


class TestAxisSpecCentered:
    def test_resolves_to_axis(self):
        spec = CenteredAxis(param="voltage", center=2.5, span=4.0, steps=5)
        axis = spec.to_axis(SpecExperiment)
        assert len(axis) == 5
        assert axis.values[0] == pytest.approx(0.5)
        assert axis.values[-1] == pytest.approx(4.5)


class TestAxisSpecList:
    def test_resolves_to_axis(self):
        spec = ListAxis(param="voltage", values=(1.0, 2.0, 3.0))
        axis = spec.to_axis(SpecExperiment)
        assert len(axis) == 3
        assert list(axis.values) == [1.0, 2.0, 3.0]

    def test_empty_values_raises(self):
        spec = ListAxis(param="voltage", values=())
        with pytest.raises(ParameterError, match="non-empty"):
            spec.to_axis(SpecExperiment)


class TestAxisSpecChoices:
    def test_resolves_to_axis(self):
        spec = ChoicesAxis(param="mode")
        axis = spec.to_axis(SpecExperiment)
        assert list(axis.values) == ["fast", "slow"]


class TestAxisSpecUnknownParam:
    def test_raises_with_alternatives(self):
        spec = LinearAxis(param="nonexistent", start=0.0, stop=1.0, steps=2)
        with pytest.raises(ParameterError, match=r"Unknown parameter.*nonexistent") as exc:
            spec.to_axis(SpecExperiment)
        # Message lists the declared alternatives.
        message = str(exc.value)
        for declared in ("voltage", "current", "delay", "mode"):
            assert declared in message


# ---------------------------------------------------------------------------
# ScanSpec.to_scan
# ---------------------------------------------------------------------------


class TestScanSpec:
    def test_to_scan_with_zip_groups(self):
        axes = (
            LinearAxis(param="voltage", start=0.0, stop=5.0, steps=3),
            LinearAxis(param="current", start=0.0, stop=10.0, steps=3),
        )
        spec = ScanSpec(axes=axes, zipped_groups=frozenset({"ramp"}))
        scan = spec.to_scan(SpecExperiment)
        points = list(scan.points())
        assert len(points) == 3  # zipped, not 9

    def test_to_scan_without_zip(self):
        axes = (
            LinearAxis(param="voltage", start=0.0, stop=5.0, steps=3),
            LinearAxis(param="delay", start=0.0, stop=1.0, steps=2),
        )
        spec = ScanSpec(axes=axes)
        scan = spec.to_scan(SpecExperiment)
        points = list(scan.points())
        assert len(points) == 6  # 3 x 2

    def test_to_scan_rejects_out_of_bounds_list(self):
        # voltage max is 5.0
        spec = ScanSpec(axes=(ListAxis(param="voltage", values=(1.0, 999.0)),))
        with pytest.raises(ParameterError, match="voltage"):
            spec.to_scan(SpecExperiment)

    def test_to_scan_rejects_out_of_bounds_linear(self):
        # A linear sweep whose endpoint exceeds the parameter maximum.
        spec = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=50.0, steps=3),))
        with pytest.raises(ParameterError, match="voltage"):
            spec.to_scan(SpecExperiment)

    def test_to_scan_accepts_in_bounds_list(self):
        spec = ScanSpec(axes=(ListAxis(param="voltage", values=(0.0, 2.5, 5.0)),))
        scan = spec.to_scan(SpecExperiment)
        assert len(list(scan.points())) == 3

    def test_to_scan_rejects_mismatched_zip_lengths(self):
        # voltage and current share group "ramp",  zipped axes must be equal length.
        axes = (
            LinearAxis(param="voltage", start=0.0, stop=5.0, steps=10),
            LinearAxis(param="current", start=0.0, stop=10.0, steps=9),
        )
        spec = ScanSpec(axes=axes, zipped_groups=frozenset({"ramp"}))
        with pytest.raises(ParameterError, match="mismatched"):
            spec.to_scan(SpecExperiment)


# ---------------------------------------------------------------------------
# RunRequest validation
# ---------------------------------------------------------------------------


class TestRunRequest:
    def test_valid_construction(self):
        req = RunRequest(
            experiment_path=Path("/tmp/test.py"),
            experiment_name="Test",
            param_values={"voltage": 3.0},
        )
        assert req.experiment_name == "Test"
        assert req.param_values["voltage"] == 3.0

    def test_param_values_frozen(self):
        original = {"voltage": 3.0}
        req = RunRequest(
            experiment_path=Path("/tmp/test.py"),
            experiment_name="Test",
            param_values=original,
        )
        # Mutation of original dict does not affect the request
        original["voltage"] = 999.0
        assert req.param_values["voltage"] == 3.0
        # Direct mutation raises
        with pytest.raises(TypeError):
            req.param_values["voltage"] = 1.0  # type: ignore[index]

    def test_scan_repeats_without_scan_accepted(self):
        # Without a scan, scan_repeats repeats the single fixed configuration.
        req = RunRequest(
            experiment_path=Path("/tmp/test.py"),
            experiment_name="Test",
            param_values={},
            scan=None,
            scan_repeats=3,
        )
        assert req.scan_repeats == 3
        assert req.scan is None

    def test_infinite_scan_repeats_without_scan_accepted(self):
        req = RunRequest(
            experiment_path=Path("/tmp/test.py"),
            experiment_name="Test",
            param_values={},
            scan=None,
            scan_repeats=None,
        )
        assert req.scan_repeats is None

    def test_scan_repeats_with_scan_accepted(self):
        scan = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=5.0, steps=3),))
        req = RunRequest(
            experiment_path=Path("/tmp/test.py"),
            experiment_name="Test",
            param_values={},
            scan=scan,
            scan_repeats=3,
        )
        assert req.scan_repeats == 3


class TestPickling:
    """A request travels to the writer process, so it has to survive a pickle."""

    def test_round_trips(self):
        scan = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=5.0, steps=3),))
        req = RunRequest(
            experiment_path=Path("/tmp/test.py"),
            experiment_name="Test",
            param_values={"voltage": 3.3, "mode": "fast"},
            source="# source",
            scan=scan,
            repeats_per_point=2,
            scan_repeats=3,
        )

        restored = pickle.loads(pickle.dumps(req))

        assert restored == req
        assert dict(restored.param_values) == {"voltage": 3.3, "mode": "fast"}
        # Still immutable on the far side.
        with pytest.raises(TypeError):
            restored.param_values["voltage"] = 0.0  # type: ignore[index]
