from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, overload

import numpy as np
import numpy.typing as npt

XY = npt.NDArray[np.float64] | list[float]
"""What a handle hands the UI to draw: an array for a curve, a list for a series."""


class ViewKind(StrEnum):
    """How a view draws its data. Selects the handle a declared view resolves to."""

    LINE = "line"
    """The curve is replaced with the most recent push (array-valued x and y)."""

    SERIES = "series"
    """Points accumulate across pushes; each push supplies one scalar (x, y)."""


@dataclass(eq=False)
class ViewSpec:
    """A live panel, declared in the class body by :func:`view`."""

    title: str
    kind: ViewKind
    x_unit: str | None = None
    y_unit: str | None = None

    # Inferred from attribute declaration
    name: str | None = field(default=None, init=False)

    # descriptor interface

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> ViewSpec: ...

    @overload
    def __get__(self, obj: object, objtype: type | None = None) -> ViewHandle: ...

    def __get__(self, obj: object | None, objtype: type | None = None) -> ViewSpec | ViewHandle:
        if obj is None:
            return self  # class-level access: the spec itself
        assert self.name is not None, "ViewSpec not attached to a class"
        key = f"_view_{self.name}"
        handle = obj.__dict__.get(key)
        if handle is None:
            handle = self._make_handle()
            obj.__dict__[key] = handle
        return handle

    def __set__(self, obj: object, value: Any) -> None:
        raise AttributeError(f"view {self.name!r} is not assignable; push to it instead")

    def _make_handle(self) -> ViewHandle:
        return LineViewHandle(self) if self.kind is ViewKind.LINE else SeriesViewHandle(self)


class ViewHandle(ABC):
    """An instance's handle to a view declared by :func:`view`.

    ``push()`` updates the latest value and marks the panel dirty.
    """

    def __init__(self, spec: ViewSpec) -> None:
        self.spec = spec
        self._dirty = False
        self._push_thread: int | None = None

    @abstractmethod
    def push(self, x: Any, y: Any) -> None:
        """Update the view with a new (x, y). Subclasses fix the argument types."""

    @abstractmethod
    def plot_data(self) -> tuple[XY, XY] | None:
        """The (x, y) to draw, or ``None`` before the first push."""

    def _mark_pushed(self) -> None:
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


class LineViewHandle(ViewHandle):
    """A curve replaced by every push."""

    def __init__(self, spec: ViewSpec) -> None:
        super().__init__(spec)
        self._x: np.ndarray | None = None
        self._y: np.ndarray | None = None

    def push(self, x: npt.ArrayLike, y: npt.ArrayLike) -> None:
        """Replace the curve with ``(x, y)``, two arrays of equal length."""
        xs = np.asarray(x, dtype=float)
        ys = np.asarray(y, dtype=float)
        if xs.shape != ys.shape:
            raise ValueError(
                f"line view {self.spec.title!r}: x and y have different shapes, "
                f"{xs.shape} and {ys.shape}"
            )
        self._x, self._y = xs, ys
        self._mark_pushed()

    def plot_data(self) -> tuple[np.ndarray, np.ndarray] | None:
        if self._x is None or self._y is None:
            return None
        return self._x, self._y


class SeriesViewHandle(ViewHandle):
    """Scalar points accumulated across pushes."""

    def __init__(self, spec: ViewSpec) -> None:
        super().__init__(spec)
        self._x: list[float] = []
        self._y: list[float] = []

    def push(self, x: float, y: float) -> None:
        """Append one scalar point to the running series."""
        self._x.append(float(x))
        self._y.append(float(y))
        self._mark_pushed()

    def plot_data(self) -> tuple[list[float], list[float]] | None:
        if not self._x:
            return None
        return self._x, self._y


@overload
def view(
    title: str,
    kind: Literal[ViewKind.LINE],
    *,
    x_unit: str | None = None,
    y_unit: str | None = None,
) -> LineViewHandle: ...


@overload
def view(
    title: str,
    kind: Literal[ViewKind.SERIES],
    *,
    x_unit: str | None = None,
    y_unit: str | None = None,
) -> SeriesViewHandle: ...


def view(
    title: str,
    kind: ViewKind,
    *,
    x_unit: str | None = None,
    y_unit: str | None = None,
) -> Any:
    """Declare a live view on an Experiment class, next to ``param()``.

    Examples::

        trace = view("Sine", ViewKind.LINE, y_unit="V")
        means = view("Mean vs voltage", ViewKind.SERIES, x_unit="V", y_unit="V")

    Panels are drawn in declaration order. Push to ``self.<name>`` inside ``shot()``to
    update the panel.
    """
    return ViewSpec(title=title, kind=kind, x_unit=x_unit, y_unit=y_unit)
