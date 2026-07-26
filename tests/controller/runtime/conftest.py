"""Fixtures for RunEngine tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
import pytest_asyncio
from h2pcontrol.sdk.client import Client

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.runtime.engine import Loader, RunEngine, SinkFactory
from h2pcontrol.controller.runtime.events import RunId
from h2pcontrol.controller.runtime.spec import RunRequest


def no_client() -> Client:
    """Mock client for non-integration tests."""
    return cast("Client", None)


class FakeSink:
    """Mock data sink for non-integration tests."""

    def __init__(self) -> None:
        self.path = Path("/tmp/fake_run.h5")
        self.shots: list[tuple[int, pd.DataFrame]] = []
        self.closed = False

    def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None:
        self.shots.append((shot_idx, frame))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def sinks() -> list[FakeSink]:
    return []


@pytest.fixture
def sink_factory(sinks: list[FakeSink]) -> SinkFactory:
    def factory(_request: RunRequest, _run_id: RunId) -> FakeSink:
        sink = FakeSink()
        sinks.append(sink)
        return sink

    return factory


class ExperimentProbe:
    """A  Experiment subclass that tracks test state."""

    def __init__(
        self,
        *,
        block_event: asyncio.Event | None = None,
        block_at: int | None = None,
        raise_on_shot: Exception | None = None,
        raise_on_teardown: bool = False,
    ) -> None:
        self.instances: list[Experiment] = []
        probe = self

        class _Exp(Experiment):
            voltage = param(3.3, min=0.0, max=5.0, unit="V")

            def __init__(self) -> None:
                super().__init__()
                self.contexts: list[Context] = []
                self.teardown_called = False
                probe.instances.append(self)

            async def shot(self, ctx: Context) -> pd.DataFrame:
                if raise_on_shot is not None:
                    raise raise_on_shot
                if block_event is not None and (block_at is None or ctx.shot_idx == block_at):
                    await block_event.wait()
                self.contexts.append(ctx)
                return pd.DataFrame({"value": [ctx.shot_idx * 1.0]})

            async def teardown(self) -> None:
                self.teardown_called = True
                if raise_on_teardown:
                    raise RuntimeError("teardown exploded")

        self.cls: type[Experiment] = _Exp

    def loader(self, _source: str, _path: Path) -> type[Experiment]:
        return self.cls


@pytest.fixture
def experiment_factory() -> Callable[..., ExperimentProbe]:
    def make(**behavior: object) -> ExperimentProbe:
        return ExperimentProbe(**behavior)  # type: ignore[arg-type]

    return make


@pytest_asyncio.fixture
async def make_engine(sink_factory: SinkFactory):
    engines: list[RunEngine] = []

    def _make(
        loader: Loader,
        *,
        client_provider: Callable[[], Client] = no_client,
        sink: SinkFactory | None = None,
    ) -> RunEngine:
        engine = RunEngine(
            client_provider=client_provider,
            sink_factory=sink or sink_factory,
            loader=loader,
        )
        engines.append(engine)
        return engine

    yield _make

    for engine in engines:
        await engine.aclose()


@pytest.fixture
def make_request() -> Callable[..., RunRequest]:
    def _make(
        *,
        repeats: int = 3,
        scan=None,
        scan_repeats: int | None = 1,
        param_values: dict | None = None,
        source: str = "",
    ) -> RunRequest:
        return RunRequest(
            experiment_path=Path("/tmp/fake_experiment.py"),
            experiment_name="Fake",
            param_values=param_values or {},
            source=source,
            scan=scan,
            repeats_per_point=repeats,
            scan_repeats=scan_repeats,
        )

    return _make
