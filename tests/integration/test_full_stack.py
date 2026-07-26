"""Full-stack integration test requiring a running h2pmanager on localhost:50051.

Starts a fake ExampleService device server (using the SDK Server class),
registers it with the manager, then runs an experiment that connects to it
through the standard SDK client path.

Skip with: pytest -m "not integration"
"""

import logging
from pathlib import Path

import pytest

from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import EngineEvent, EntryState, RunFinished, RunStarted
from h2pcontrol.controller.runtime.run_metadata import run_metadata
from h2pcontrol.controller.runtime.session import Session
from h2pcontrol.controller.runtime.spec import RunRequest
from h2pcontrol.controller.runtime.store import RunStore

logger = logging.getLogger(__name__)

MANAGER_ADDRESS = "localhost:50051"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def experiment_file(experiments_dir: Path) -> Path:
    """The ExampleService experiment source (tests/resources/experiments/)."""
    return experiments_dir / "greeting_experiment.py"


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_stack_single_run(fake_device, experiment_file: Path, tmp_path: Path, wait_for):
    """Full path: load experiment -> connect to device via manager -> run shots -> HDF5."""
    session = Session(manager_address=MANAGER_ADDRESS)
    results_root = str(tmp_path / "results")

    def make_sink(request: RunRequest, run_id: str) -> RunStore:
        metadata = run_metadata(request) | {"run_id": run_id}
        return RunStore.create(results_root, request.experiment_name, attrs=metadata)

    engine = RunEngine(
        client_provider=lambda: session.client,
        sink_factory=make_sink,
        loader=session.load_experiment_from_source,
    )

    events: list[EngineEvent] = []
    engine.subscribe(events.append)

    request = RunRequest(
        experiment_path=experiment_file,
        experiment_name="Greeting",
        param_values={"sender": "Integration Test"},
        source=experiment_file.read_text(),
        scan=None,
        repeats_per_point=3,
        scan_repeats=1,
    )

    engine.submit(request)
    await wait_for(engine, RunFinished)
    await engine.aclose()

    # Verify run completed
    finished = next(e for e in events if isinstance(e, RunFinished))
    assert finished.outcome == EntryState.COMPLETED
    assert finished.shots_completed == 3

    # Verify device was called
    assert fake_device.call_count == 3

    # Verify HDF5 output
    import tables

    started = next(e for e in events if isinstance(e, RunStarted))
    h5_path = Path(started.result_path)
    assert h5_path.exists()

    with tables.open_file(str(h5_path), mode="r") as h5:
        table = h5.root.data
        assert table.nrows == 3
        for row in table.iterrows():
            assert b"Hello, Integration Test!" in row["result_greeting"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_stack_with_param_override(
    fake_device, experiment_file: Path, tmp_path: Path, wait_for
):
    """Verify parameter overrides reach the device call."""
    session = Session(manager_address=MANAGER_ADDRESS)
    results_root = str(tmp_path / "results")

    def make_sink(request: RunRequest, run_id: str) -> RunStore:
        metadata = run_metadata(request) | {"run_id": run_id}
        return RunStore.create(results_root, request.experiment_name, attrs=metadata)

    engine = RunEngine(
        client_provider=lambda: session.client,
        sink_factory=make_sink,
        loader=session.load_experiment_from_source,
    )

    events: list[EngineEvent] = []
    engine.subscribe(events.append)

    request = RunRequest(
        experiment_path=experiment_file,
        experiment_name="Greeting",
        param_values={"sender": "Claude"},
        source=experiment_file.read_text(),
        scan=None,
        repeats_per_point=1,
        scan_repeats=1,
    )

    engine.submit(request)
    await wait_for(engine, RunFinished)
    await engine.aclose()

    finished = next(e for e in events if isinstance(e, RunFinished))
    assert finished.outcome == EntryState.COMPLETED

    # Verify the response contains the overridden name
    import tables

    started = next(e for e in events if isinstance(e, RunStarted))
    with tables.open_file(str(started.result_path), mode="r") as h5:
        row = h5.root.data[0]
        assert b"Hello, Claude!" in row["result_greeting"]
