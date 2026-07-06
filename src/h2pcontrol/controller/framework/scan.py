import itertools
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .parameters import ParamSpec


@dataclass(frozen=True)
class Axis:
    """One scan dimension over a declared experiment parameter.

    Continuous scan (start/stop/steps)::

        Axis(MyExperiment.voltage, start=0.0, stop=5.0, steps=11)

    Discrete scan over all choices declared on the parameter::

        Axis(MyExperiment.mode)
    """

    param: ParamSpec[Any]
    start: float | None = None
    stop: float | None = None
    steps: int | None = None

    def __post_init__(self) -> None:
        has_range = self.start is not None or self.stop is not None or self.steps is not None
        if has_range:
            if self.start is None or self.stop is None or self.steps is None:
                raise ValueError("Continuous axis requires all of start, stop, and steps")
        else:
            if self.param.choices is None:
                raise ValueError(
                    f"Parameter {self.param.name!r} has no choices; "
                    "provide start/stop/steps for a continuous scan"
                )

    @property
    def is_discrete(self) -> bool:
        return self.start is None

    def __len__(self) -> int:
        if self.is_discrete:
            return len(self.param.choices)  # type: ignore[arg-type]
        return self.steps  # type: ignore[return-value]

    @property
    def name(self) -> str:
        """The experiment parameter name this axis scans."""
        if self.param.name is None:
            raise ValueError("ParamSpec is not attached to an Experiment class")
        return self.param.name

    @property
    def values(self) -> Sequence[Any]:
        if self.start is None:
            return self.param.choices  # type: ignore[return-value]
        return np.linspace(self.start, self.stop, self.steps)  # type: ignore[arg-type]


class Scan:
    """Grid scan (cartesian product) over one or more Axis objects."""

    def __init__(self, *axes: Axis):
        if not axes:
            raise ValueError("Scan requires at least one Axis")
        self.axes = list(axes)

    def __len__(self) -> int:
        return math.prod(len(ax) for ax in self.axes)

    def validate_for(self, experiment_cls: type) -> None:
        """Raise ValueError if any axis references a parameter that is not
        declared on ``experiment_cls`` (identity check, inheritance-aware)."""
        known = getattr(experiment_cls, "_parameters", {})
        foreign = [ax.name for ax in self.axes if known.get(ax.name) is not ax.param]
        if foreign:
            raise ValueError(
                f"Scan axes {foreign} are not parameters of {experiment_cls.__name__} "
                f"(declared: {sorted(known)})"
            )

    def points(self) -> Iterator[dict[str, Any]]:
        for combo in itertools.product(*[ax.values for ax in self.axes]):
            yield {
                ax.name: v if ax.is_discrete else float(v)
                for ax, v in zip(self.axes, combo, strict=False)
            }
