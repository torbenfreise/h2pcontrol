from __future__ import annotations

from pathlib import Path

import pytest
import tables

from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import (
    EntryState,
    RunFinished,
    RunStarted,
    ShotCompleted,
)
from h2pcontrol.controller.runtime.session import Session
from h2pcontrol.controller.runtime.spec import LinearAxis, ListAxis, RunRequest, ScanSpec
from h2pcontrol.controller.runtime.store import RunStoreFactory

pytestmark = pytest.mark.asyncio


@pytest.fixture
def experiment_file(experiments_dir: Path) -> Path:
    return experiments_dir / "sine_experiment.py"


def _engine(results_root: str) -> RunEngine:
    """A fully wired engine — real RunStore, real writer process."""
    session = Session(manager_address="localhost:50051")
    return RunEngine(
        client_provider=lambda: session.client,
        sink_factory=RunStoreFactory(results_root),
        loader=session.load_experiment_from_source,
    )


class TestEndToEnd:
    async def test_single_run_produces_hdf5(self, experiment_file: Path, tmp_path: Path, wait_for):
        engine = _engine(str(tmp_path / "results"))
        marker = tmp_path / "teardown.marker"
        source = experiment_file.read_text()
        events: list[object] = []
        engine.subscribe(events.append)

        request = RunRequest(
            experiment_path=experiment_file,
            experiment_name="Sine",
            param_values={"frequency": 2.0, "amplitude": 3.0, "marker": str(marker)},
            source=source,
            repeats_per_point=3,
            scan_repeats=1,
        )
        engine.submit(request)
        finished = await wait_for(engine, RunFinished)
        started = next(e for e in events if isinstance(e, RunStarted))
        await engine.aclose()

        assert finished.outcome == EntryState.COMPLETED
        assert finished.shots_completed == 3
        assert marker.read_text() == "torn down"

        h5_path = Path(started.result_path)
        assert h5_path.exists()

        with tables.open_file(str(h5_path), mode="r") as h5:
            table = h5.root.data
            assert table.nrows == 3
            assert "shot_idx" in table.colnames
            assert "result_peak" in table.colnames

            assert hasattr(h5.root, "traces")
            assert h5.root.traces.shot_00000.result_time.shape == (1, 100)
            assert h5.root.traces.shot_00000.result_signal.shape == (1, 100)

            attrs = h5.root._v_attrs
            assert attrs["experiment_source"] == source
            assert "run_id" in attrs._v_attrnames
            assert "h2pcontrol_version" in attrs._v_attrnames
            # Experiment.metadata() reaches the file's root attributes.
            assert attrs["n_samples"] == "100"

    async def test_scan_run_produces_correct_shots(
        self, experiment_file: Path, tmp_path: Path, wait_for
    ):
        engine = _engine(str(tmp_path / "results"))
        scan = ScanSpec(axes=(LinearAxis(param="frequency", start=1.0, stop=10.0, steps=3),))
        engine.submit(
            RunRequest(
                experiment_path=experiment_file,
                experiment_name="Sine",
                param_values={"amplitude": 2.0},
                source=experiment_file.read_text(),
                scan=scan,
                repeats_per_point=2,
                scan_repeats=1,
            )
        )
        finished = await wait_for(engine, RunFinished)
        await engine.aclose()

        assert finished.outcome == EntryState.COMPLETED
        assert finished.shots_completed == 6  # 3 points x 2 repeats

    async def test_scan_repeats(self, experiment_file: Path, tmp_path: Path, wait_for):
        engine = _engine(str(tmp_path / "results"))
        scan = ScanSpec(axes=(ListAxis(param="amplitude", values=(1.0, 5.0)),))
        engine.submit(
            RunRequest(
                experiment_path=experiment_file,
                experiment_name="Sine",
                param_values={"frequency": 1.0},
                source=experiment_file.read_text(),
                scan=scan,
                repeats_per_point=1,
                scan_repeats=3,
            )
        )
        finished = await wait_for(engine, RunFinished)
        await engine.aclose()

        assert finished.outcome == EntryState.COMPLETED
        assert finished.shots_completed == 6  # 2 points x 1 repeat x 3 scan_repeats

    async def test_stop_mid_scan(self, experiment_file: Path, tmp_path: Path, wait_for):
        engine = _engine(str(tmp_path / "results"))
        scan = ScanSpec(axes=(LinearAxis(param="frequency", start=1.0, stop=10.0, steps=5),))
        engine.submit(
            RunRequest(
                experiment_path=experiment_file,
                experiment_name="Sine",
                param_values={"amplitude": 1.0},
                source=experiment_file.read_text(),
                scan=scan,
                repeats_per_point=1,
                scan_repeats=None,  # infinite
            )
        )
        started = await wait_for(engine, RunStarted)
        await wait_for(engine, ShotCompleted, count=2)
        engine.stop_current()
        finished = await wait_for(engine, RunFinished)
        await engine.aclose()

        assert finished.outcome == EntryState.STOPPED
        assert finished.shots_completed > 0
        assert Path(started.result_path).exists()  # partial HDF5 written
