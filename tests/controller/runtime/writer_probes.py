"""Picklable sink probes for the writer-process tests.

``ProcessWriter`` builds its sink in a spawned interpreter, so a probe has to be
a module-level class the child can import by name — a fixture-local class or a
closure would not survive the trip.  For the same reason the probes report back
through files under a tmp directory instead of in-memory state.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

_GATE = "open"
_CLOSED = "closed"


class ProbeSink:
    """Records each save as a file named after the shot, holding the writer's pid."""

    def __init__(self, root: Path, *, fail_on_save: bool = False, gated: bool = False) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "probe.h5"
        self._fail_on_save = fail_on_save
        self._gated = gated

    def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None:
        while self._gated and not (self.root / _GATE).exists():
            time.sleep(0.01)
        if self._fail_on_save:
            raise RuntimeError("disk full")
        (self.root / f"shot_{shot_idx:03d}").write_text(str(os.getpid()))

    def close(self) -> None:
        (self.root / _CLOSED).write_text(str(os.getpid()))


@dataclass
class ProbeSinkFactory:
    """Builds a :class:`ProbeSink` reporting into *root*."""

    root: Path
    fail_on_open: bool = False
    fail_on_save: bool = False
    gated: bool = False

    def __call__(self, _request: Any, _run_id: str, _schema: Any) -> ProbeSink:
        if self.fail_on_open:
            raise RuntimeError("no room on device")
        return ProbeSink(self.root, fail_on_save=self.fail_on_save, gated=self.gated)


def saved_shots(root: Path) -> list[int]:
    """Shot indices the probe has written so far, in order."""
    return sorted(int(p.name.removeprefix("shot_")) for p in root.glob("shot_*"))


def writer_pid(root: Path, shot_idx: int) -> int:
    """The pid of whatever wrote *shot_idx*."""
    return int((root / f"shot_{shot_idx:03d}").read_text())


def release(root: Path) -> None:
    """Let a gated probe's pending and future saves through."""
    (root / _GATE).touch()


def was_closed(root: Path) -> bool:
    return (root / _CLOSED).exists()
