import itertools
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .parameters import ParameterError, ParamSpec


@dataclass(frozen=True)
class Axis:
    """One scan dimension over a declared experiment parameter.

    Continuous scan (start/stop/steps)::

        Axis(MyExperiment.voltage, start=0.0, stop=5.0, steps=11)

    Centered scan (center ± span/2)::

        Axis.centered(MyExperiment.voltage, center=2.5, span=5.0, steps=11)

    Explicit value list::

        Axis.from_list(MyExperiment.voltage, [1.0, 2.0, 5.0])

    Discrete scan over all choices declared on the parameter::

        Axis(MyExperiment.mode)
    """

    param: ParamSpec[Any]
    start: float | None = None
    stop: float | None = None
    steps: int | None = None
    explicit_values: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        has_range = self.start is not None or self.stop is not None or self.steps is not None
        if self.explicit_values is not None:
            if len(self.explicit_values) == 0:
                raise ValueError("explicit_values must not be empty")
        elif has_range:
            if self.start is None or self.stop is None or self.steps is None:
                raise ValueError("Continuous axis requires all of start, stop, and steps")
        else:
            if self.param.choices is None:
                raise ValueError(
                    f"Parameter {self.param.name!r} has no choices; "
                    "provide start/stop/steps for a continuous scan"
                )

    @classmethod
    def centered(cls, param: ParamSpec[Any], center: float, span: float, steps: int) -> "Axis":
        """Centered scan: *center* ± *span*/2."""
        return cls(param, start=center - span / 2, stop=center + span / 2, steps=steps)

    @classmethod
    def from_list(cls, param: ParamSpec[Any], values: Sequence[Any]) -> "Axis":
        """Scan over an explicit list of values."""
        return cls(param, explicit_values=tuple(values))

    @property
    def is_discrete(self) -> bool:
        return self.start is None and self.explicit_values is None

    def __len__(self) -> int:
        if self.explicit_values is not None:
            return len(self.explicit_values)
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
        if self.explicit_values is not None:
            return self.explicit_values
        if self.start is None:
            return self.param.choices  # type: ignore[return-value]
        return np.linspace(self.start, self.stop, self.steps)  # type: ignore[arg-type]

    def validate_values(self) -> None:
        """Validate every value this axis produces against the parameter spec.
        Raises ``ParameterError`` on the first out-of-range or invalid value.
        """
        if self.explicit_values is None and self.start is not None:
            values = (self.start, self.stop)  # only check high / low for linear sweep
        else:
            values = self.values
        for value in values:
            self.param.validate(value)


class Scan:
    """N-dimensional scan with support for zipped groups.

    Axes whose parameters share the same ``group`` are zipped (stepped
    together).  Ungrouped axes and distinct groups are crossed (cartesian
    product).
    """

    def __init__(self, *axes: Axis, zipped_groups: set[str] | None = None):
        assert axes, "Scan requires at least one Axis"
        self.axes = list(axes)
        self._zipped_groups = zipped_groups

    def __len__(self) -> int:
        return math.prod(self._group_length(g) for g in self._groups().values())

    def validate(self) -> None:
        """Check that groups have the same length.
        Raises ``ParameterError`` on mismatch.
        """
        for axes in self._groups().values():
            self._group_length(axes)

    def points(self) -> Iterator[dict[str, Any]]:
        groups = self._groups()
        group_points = [self._zip_group(axes) for axes in groups.values()]
        for combo in itertools.product(*group_points):
            merged: dict[str, Any] = {}
            for d in combo:
                merged.update(d)
            yield merged

    def _is_zipped(self, group: str) -> bool:
        if self._zipped_groups is None:
            # zip groups by default
            return True
        return group in self._zipped_groups

    def _groups(self) -> dict[str | int, list[Axis]]:
        """Partition axes into groups.

        Named groups whose zip is active are collected together.
        Ungrouped axes (and axes in non-zipped groups) each get a unique
        integer key so they remain independent in the cartesian product.
        """
        result: dict[str | int, list[Axis]] = {}
        ungrouped_id = 0
        for ax in self.axes:
            key = ax.param.group
            if key is not None and self._is_zipped(key):
                result.setdefault(key, []).append(ax)
            else:
                result[ungrouped_id] = [ax]
                ungrouped_id += 1
        return result

    @staticmethod
    def _group_length(axes: list[Axis]) -> int:
        lengths = {len(ax) for ax in axes}
        if len(lengths) > 1:
            names = [ax.name for ax in axes]
            raise ParameterError(
                f"Grouped axes {names} have mismatched lengths: "
                + ", ".join(f"{ax.name}={len(ax)}" for ax in axes)
            )
        return lengths.pop()

    @staticmethod
    def _zip_group(axes: list[Axis]) -> list[dict[str, Any]]:
        """Zip axes within a group into a list of point dicts."""
        Scan._group_length(axes)  # validate
        return [
            {ax.name: v if ax.is_discrete else float(v) for ax, v in zip(axes, vals, strict=False)}
            for vals in zip(*[ax.values for ax in axes], strict=False)
        ]
