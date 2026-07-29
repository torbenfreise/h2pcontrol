"""Typed engine events and state enums.

Event ordering contract (subscribers rely on this, tests assert it):

Per submit: RunQueued → QueueChanged.
Per run: StateChanged(RUNNING) → QueueChanged → RunStarted → ShotCompleted* →
         RunFinished → QueueChanged → StateChanged(IDLE | next run starts).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NewType

import pandas as pd

if TYPE_CHECKING:
    from .spec import RunRequest


class EngineState(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"


class EntryState(enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    CANCELLED = "cancelled"


RunId = NewType("RunId", str)


@dataclass(frozen=True)
class QueueEntry:
    run_id: RunId
    request: RunRequest
    state: EntryState


@dataclass(frozen=True)
class RunQueued:
    run_id: RunId
    request: RunRequest


@dataclass(frozen=True)
class RunStarted:
    run_id: RunId
    total_shots: int | None
    result_path: Path


@dataclass(frozen=True)
class ShotCompleted:
    run_id: RunId
    shot_idx: int
    total_shots: int | None
    frame: pd.DataFrame


@dataclass(frozen=True)
class RunFinished:
    run_id: RunId
    outcome: EntryState
    shots_completed: int
    error: str | None = None


@dataclass(frozen=True)
class QueueChanged:
    entries: tuple[QueueEntry, ...]


@dataclass(frozen=True)
class StateChanged:
    state: EngineState


EngineEvent = RunQueued | RunStarted | ShotCompleted | RunFinished | QueueChanged | StateChanged
