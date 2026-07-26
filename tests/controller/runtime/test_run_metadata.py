"""Tests for run metadata."""

from __future__ import annotations

from pathlib import Path

from h2pcontrol.controller.runtime.run_metadata import run_metadata
from h2pcontrol.controller.runtime.spec import RunRequest

_SOURCE = "x = 1\n"


def _request(path: Path) -> RunRequest:
    return RunRequest(
        experiment_path=path,
        experiment_name="E",
        param_values={},
        source=_SOURCE,
    )


def test_captures_experiment_source(tmp_path: Path):
    exp = tmp_path / "exp.py"
    exp.write_text(_SOURCE)
    meta = run_metadata(_request(exp))
    # experiment_source is the captured snapshot, byte-identical to request.source.
    assert meta["experiment_source"] == _SOURCE


def test_includes_version_attrs(tmp_path: Path):
    meta = run_metadata(_request(tmp_path / "exp.py"))
    assert "h2pcontrol_version" in meta
    assert "python_version" in meta


def test_omits_source_when_empty():
    request = RunRequest(experiment_path=Path("/x.py"), experiment_name="E", param_values={})
    assert "experiment_source" not in run_metadata(request)
