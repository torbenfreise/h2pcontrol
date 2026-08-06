from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from .parameters import ParamSpec


class PlotError(ValueError):
    """A plot declaration references something that is not a declared result/parameter."""


class PlotKind(StrEnum):
    """How a plot draws its curves."""

    LINE = "line"
    """A trace redrawn per shot (array-valued y)."""

    SERIES = "series"
    """Points accumulated across shots (scalar y)."""


@dataclass
class ResultSpec:
    """Typed experiment result column.

    Declared as a class attribute (``signal = result(float, unit="V")``) and referenced
    from ``setup()`` to build plots (``self.plot(self.signal, ...)``).
    """

    dtype: type
    unit: str | None = None
    description: str | None = None

    # Inferred from attribute declaration
    name: str | None = field(default=None, init=False)

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name


def result(dtype: type, *, unit: str | None = None, description: str | None = None) -> ResultSpec:
    """Declare an experiment result column.

    Examples::

        signal = result(float, unit="V")
        trace = result(np.ndarray, unit="V", description="MCP anode trace")

    The declared ``name`` is the column ``shot()`` must return.
    """
    return ResultSpec(dtype=dtype, unit=unit, description=description)


@dataclass
class PlotSpec:
    """A relation between declared results: which curves share a plot, and the x axis.

    Built by ``Experiment.plot(*ys, x=..., ...)``.
    """

    ys: tuple[ResultSpec, ...]
    x: ResultSpec | ParamSpec | None = None
    kind: PlotKind | None = None
    title: str | None = None

    def resolve_kind(self) -> PlotKind:
        if self.kind is not None:
            return self.kind
        if any(y.dtype is np.ndarray for y in self.ys):
            return PlotKind.LINE
        return PlotKind.SERIES
