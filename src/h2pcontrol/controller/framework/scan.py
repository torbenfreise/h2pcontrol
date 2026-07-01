import itertools
import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np


@dataclass
class Axis:
    param: str  # must match a key in Experiment._parameters
    start: float
    stop: float
    steps: int

    @property
    def values(self) -> np.ndarray:
        return np.linspace(self.start, self.stop, self.steps)


class Scan:
    """Grid scan (cartesian product) over one or more Axis objects."""

    def __init__(self, *axes: Axis):
        if not axes:
            raise ValueError("Scan requires at least one Axis")
        self.axes = list(axes)

    def __len__(self) -> int:
        return math.prod(ax.steps for ax in self.axes)

    def points(self) -> Iterator[dict[str, float]]:
        for combo in itertools.product(*[ax.values for ax in self.axes]):
            yield {ax.param: float(v) for ax, v in zip(self.axes, combo, strict=False)}
