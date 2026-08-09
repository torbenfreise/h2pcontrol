"""Serializable run description DTOs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..framework.experiment import Experiment
from ..framework.parameters import ParameterError, ParamSpec
from ..framework.scan import Axis, Scan


@dataclass(frozen=True)
class AxisSpec(ABC):
    """Snapshot of one scan axis, referencing its parameter by name."""

    param: str

    def to_axis(self, cls: type[Experiment]) -> Axis:
        """Resolve this spec against a loaded experiment class into a live Axis."""
        params = cls.parameters()
        if self.param not in params:
            available = ", ".join(sorted(params.keys()))
            raise ParameterError(
                f"Unknown parameter {self.param!r}; declared parameters: {available}"
            )
        return self.resolve(params[self.param])

    def resolve(self, spec: ParamSpec[Any]) -> Axis:
        """Build the live Axis from an already-resolved ParamSpec (skips name lookup)."""
        return self._build(spec)

    @abstractmethod
    def _build(self, spec: ParamSpec[Any]) -> Axis:
        """Build the live Axis from the resolved parameter spec."""

    @abstractmethod
    def summary(self) -> str:
        """Human-readable description of this axis."""


@dataclass(frozen=True)
class LinearAxis(AxisSpec):
    start: float
    stop: float
    steps: int

    def _build(self, spec: ParamSpec[Any]) -> Axis:
        return Axis(spec, start=self.start, stop=self.stop, steps=self.steps)

    def summary(self) -> str:
        return f"{self.param} (linear)  start={self.start}  stop={self.stop}  steps={self.steps}"


@dataclass(frozen=True)
class CenteredAxis(AxisSpec):
    center: float
    span: float
    steps: int

    def _build(self, spec: ParamSpec[Any]) -> Axis:
        return Axis.centered(spec, center=self.center, span=self.span, steps=self.steps)

    def summary(self) -> str:
        return (
            f"{self.param} (centered)  center={self.center}  span={self.span}  steps={self.steps}"
        )


@dataclass(frozen=True)
class ListAxis(AxisSpec):
    values: tuple[Any, ...]

    def _build(self, spec: ParamSpec[Any]) -> Axis:
        if not self.values:
            raise ParameterError(f"Axis {self.param!r} (list): requires non-empty values")
        return Axis.from_list(spec, list(self.values))

    def summary(self) -> str:
        return f"{self.param} (list)  values={self.values}"


@dataclass(frozen=True)
class ChoicesAxis(AxisSpec):
    def _build(self, spec: ParamSpec[Any]) -> Axis:
        return Axis(spec)

    def summary(self) -> str:
        return f"{self.param} (choices)"


@dataclass(frozen=True)
class ScanSpec:
    """Snapshot of a full scan configuration."""

    axes: tuple[AxisSpec, ...]
    zipped_groups: frozenset[str] = frozenset()

    def to_scan(self, cls: type[Experiment]) -> Scan:
        """Resolve all axes and build a live Scan object.

        Each resolved axis is validated against its parameter's bounds/choices,
        raising ``ParameterError`` for out-of-range scan values.
        """
        resolved = [a.to_axis(cls) for a in self.axes]
        for axis in resolved:
            axis.validate_values()
        scan = Scan(*resolved, zipped_groups=set(self.zipped_groups))
        scan.validate()  # zipped axes must share a length
        return scan


@dataclass(frozen=True)
class RunRequest:
    """Immutable snapshot of a scheduled run.

    ``source`` is the full experiment file text captured at File -> Open.
    ``experiment_path`` is retained for tracebacks.
    ``param_values`` are frozen at submit time.
    """

    experiment_path: Path
    experiment_name: str
    param_values: Mapping[str, Any]
    source: str = ""
    scan: ScanSpec | None = None
    repeats_per_point: int = 1
    scan_repeats: int | None = 1

    def __post_init__(self) -> None:
        # Freeze param_values into an immutable mapping.
        object.__setattr__(self, "param_values", MappingProxyType(dict(self.param_values)))

    # A request travels to the writer process, and mappingproxy has no pickle
    # support — unwrap it on the way out and re-freeze on the way in.
    def __getstate__(self) -> dict[str, Any]:
        return {**self.__dict__, "param_values": dict(self.param_values)}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        object.__setattr__(self, "param_values", MappingProxyType(dict(state["param_values"])))
