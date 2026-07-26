from pathlib import Path

import pandas as pd
import pytest

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParameterError, param
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

    async def shot(self, ctx: Context) -> pd.DataFrame:
        return pd.DataFrame({"x": [0.0]})


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
