from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np


class ViewKind(StrEnum):
    """How a view draws its data."""

    LINE = "line"
    """The curve is replaced with the most recent push (array-valued y)."""

    SERIES = "series"
    """Points accumulate across pushes; each push supplies its own (x, y)."""


@dataclass(frozen=True, eq=False)
class ViewSpec:
    """A live panel declared in ``setup()``."""

    title: str
    kind: ViewKind
    unit: str | None = None
    x: np.ndarray | None = None
    x_unit: str | None = None


class ViewHandle:
    """A typed handle to a declared view, returned by ``Experiment.view()``.

    ``push()`` updates the latest value and marks the panel dirty.
    """

    def __init__(self, spec: ViewSpec) -> None:
        self.spec = spec
        self._line: np.ndarray | None = None
        self._series_x: list[float] = []
        self._series_y: list[float] = []
        self._dirty = False
        self._push_thread: int | None = None

    def push(self, *values: Any) -> None:
        """Update the view.

        LINE views take one array (``push(y)``) and replace the curve; SERIES
        views take a scalar point (``push(x, y)``) appended to the running
        series.
        """
        if self.spec.kind is ViewKind.LINE:
            (y,) = values
            self._line = np.asarray(y, dtype=float)
        else:
            x, y = values
            self._series_x.append(float(x))
            self._series_y.append(float(y))
        self._push_thread = threading.get_ident()
        self._dirty = True

    @property
    def dirty(self) -> bool:
        """True if a value has been pushed since the last :meth:`clear_dirty`."""
        return self._dirty

    def clear_dirty(self) -> None:
        """Mark the panel painted. Called by the UI after reading the buffer."""
        self._dirty = False

    @property
    def push_thread(self) -> int | None:
        """Thread id of the most recent push, or ``None`` if never pushed."""
        return self._push_thread

    @property
    def line(self) -> np.ndarray | None:
        """Latest pushed curve for a LINE view, or ``None`` before the first push."""
        return self._line

    @property
    def series(self) -> tuple[list[float], list[float]]:
        """Accumulated (xs, ys) for a SERIES view."""
        return self._series_x, self._series_y
