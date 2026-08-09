"""Tests for the shot writers.

``InProcessWriter`` is exercised through the engine (``TestBackgroundSave`` in
test_engine.py); these tests focus on ``ProcessWriter``, the default, whose
sink lives in a spawned interpreter and can only be observed indirectly.
Probes live in writer_probes.py because the child imports them by name.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pandas as pd
import pytest
import tables
from writer_probes import (
    ProbeSinkFactory,
    release,
    saved_shots,
    was_closed,
    writer_pid,
)

from h2pcontrol.controller.framework.results import ResultSpec
from h2pcontrol.controller.runtime.events import RunId
from h2pcontrol.controller.runtime.spec import RunRequest
from h2pcontrol.controller.runtime.store import RunSchema, RunStoreFactory
from h2pcontrol.controller.runtime.writer import ProcessWriter, WriterError

pytestmark = pytest.mark.asyncio

RUN_ID = RunId("0123456789abcdef")


def _request() -> RunRequest:
    return RunRequest(
        experiment_path=Path("/tmp/probe.py"),
        experiment_name="Probe",
        param_values={"voltage": 3.3},
    )


def _schema() -> RunSchema:
    return RunSchema(results={"value": ResultSpec(dtype=float)}, params={})


def _frame(shot_idx: int) -> pd.DataFrame:
    return pd.DataFrame({"result_value": [float(shot_idx)]})


async def _writer(factory, **kwargs) -> ProcessWriter:
    writer = ProcessWriter(factory, _request(), RUN_ID, _schema(), **kwargs)
    await writer.open()
    return writer


class TestProcessWriter:
    async def test_shots_land_in_the_file_in_order(self, tmp_path: Path):
        """The child owns a real RunStore end to end and writes every shot."""
        writer = await _writer(RunStoreFactory(str(tmp_path)))
        try:
            for shot_idx in range(3):
                await writer.save(shot_idx, _frame(shot_idx))
            await writer.flush()
        finally:
            await writer.aclose()

        assert writer.path is not None and writer.path.exists()
        with tables.open_file(str(writer.path)) as h5:
            assert [int(row["shot_idx"]) for row in h5.root.data.iterrows()] == [0, 1, 2]

    async def test_writes_run_in_another_process(self, tmp_path: Path):
        """The point of the exercise: the save does not happen on this interpreter."""
        writer = await _writer(ProbeSinkFactory(tmp_path))
        try:
            await writer.save(0, _frame(0))
            await writer.flush()
        finally:
            await writer.aclose()

        assert writer_pid(tmp_path, 0) != os.getpid()

    async def test_saves_overlap_the_caller(self, tmp_path: Path):
        """save() returns while the child is still parked in an earlier write."""
        writer = await _writer(ProbeSinkFactory(tmp_path, gated=True))
        try:
            for shot_idx in range(3):
                await writer.save(shot_idx, _frame(shot_idx))
            assert saved_shots(tmp_path) == []  # nothing written; the gate holds shot 0

            release(tmp_path)
            await writer.flush()
            assert saved_shots(tmp_path) == [0, 1, 2]
        finally:
            release(tmp_path)
            await writer.aclose()

    async def test_full_queue_blocks_the_caller(self, tmp_path: Path):
        """Backpressure: a stalled writer throttles the producer rather than buffering."""
        writer = await _writer(ProbeSinkFactory(tmp_path, gated=True), maxsize=1)
        try:
            # One shot in the child's hands, one in the queue; the next has
            # nowhere to go until the gate opens.
            for shot_idx in range(2):
                await writer.save(shot_idx, _frame(shot_idx))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(writer.save(2, _frame(2)), timeout=0.5)
        finally:
            release(tmp_path)
            await writer.aclose()

    async def test_write_error_surfaces_and_sink_still_closes(self, tmp_path: Path):
        """A failed write fails the run at the next hand-off or the closing flush."""
        writer = await _writer(ProbeSinkFactory(tmp_path, fail_on_save=True))
        try:
            with pytest.raises(WriterError, match="disk full"):
                for shot_idx in range(5):
                    await writer.save(shot_idx, _frame(shot_idx))
                    await asyncio.sleep(0.05)  # let the failure make its way back
                await writer.flush()
        finally:
            await writer.aclose()

        assert was_closed(tmp_path)

    async def test_flush_reports_a_write_error(self, tmp_path: Path):
        """Even a single shot's failure is caught, by the flush on the way out."""
        writer = await _writer(ProbeSinkFactory(tmp_path, fail_on_save=True))
        try:
            await writer.save(0, _frame(0))
            with pytest.raises(WriterError, match="disk full"):
                await writer.flush()
        finally:
            await writer.aclose()

    async def test_sink_creation_failure_surfaces_from_open(self, tmp_path: Path):
        """A sink that cannot be created fails the run before any shot is taken."""
        writer = ProcessWriter(
            ProbeSinkFactory(tmp_path, fail_on_open=True), _request(), RUN_ID, _schema()
        )
        try:
            with pytest.raises(WriterError, match="no room on device"):
                await writer.open()
        finally:
            await writer.aclose()

    async def test_aclose_without_open_is_harmless(self, tmp_path: Path):
        """The engine closes the writer on every exit path, including a failed setup."""
        writer = ProcessWriter(ProbeSinkFactory(tmp_path), _request(), RUN_ID, _schema())
        await writer.aclose()
        assert writer.path is None
