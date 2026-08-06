import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, final

import pandas as pd

from .parameters import ParamSpec
from .results import PlotError, PlotKind, PlotSpec, ResultSpec
from .stubs import StubSpec


@dataclass(frozen=True)
class Context:
    shot_idx: int
    run_id: str = ""
    total_shots: int | None = None


class Experiment(ABC):
    name: ClassVar[str] = ""
    _parameters: ClassVar[dict[str, ParamSpec]] = {}
    _results: ClassVar[dict[str, ResultSpec]] = {}
    _stubs: ClassVar[dict[str, StubSpec]] = {}
    _plots: list[PlotSpec]

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        Experiment._collect_parameters(cls)
        Experiment._collect_results(cls)
        Experiment._collect_stubs(cls)
        Experiment._wrap_shot(cls)

    @staticmethod
    def _collect_parameters(experiment_cls) -> None:
        """Collects param() declarations. The ParamSpec stays on the class as a
        data descriptor: class access yields the spec, instance access the value."""
        inherited = dict(experiment_cls._parameters)
        for name, val in list(experiment_cls.__dict__.items()):
            if not isinstance(val, ParamSpec):
                continue
            val.name = name
            if val.dtype is None and val.default is not None:
                val.dtype = type(val.default)
            inherited[name] = val

        experiment_cls._parameters = inherited

    @staticmethod
    def _collect_results(experiment_cls) -> None:
        """Collects result() declarations."""
        inherited = dict(experiment_cls._results)
        for name, val in list(experiment_cls.__dict__.items()):
            if not isinstance(val, ResultSpec):
                continue
            val.name = name
            inherited[name] = val

        experiment_cls._results = inherited

    @staticmethod
    def _collect_stubs(experiment_cls) -> None:
        """
        Collects service_stub() declarations in order to
        connect to the services required before running the experiment
        """
        inherited_stubs = dict(experiment_cls._stubs)
        for name, val in list(experiment_cls.__dict__.items()):
            if not isinstance(val, StubSpec):
                continue
            inherited_stubs[name] = val
            delattr(experiment_cls, name)  # delete class-level sentinel

        experiment_cls._stubs = inherited_stubs

    @staticmethod
    def _wrap_shot(experiment_cls) -> None:
        """
        Replaces the shot method defined in the experiment in order
        to append the current experiment parameters to the returned
        dataframe.
        """
        if "shot" in experiment_cls.__dict__:
            original = experiment_cls.__dict__["shot"]

            async def wrapped_shot(self, ctx, _orig=original):
                result = await _orig(self, ctx)
                parameters = pd.DataFrame(
                    {k: [getattr(self, k)] * len(result) for k in self._parameters},
                    index=result.index,
                )
                result.columns = pd.MultiIndex.from_product([["result"], result.columns])
                parameters.columns = pd.MultiIndex.from_product([["params"], parameters.columns])
                return pd.concat([result, parameters], axis=1)

            experiment_cls.shot = wrapped_shot

    @property
    def logger(self) -> logging.Logger:
        """Logger for experiment code.

        Named ``experiment.<name>`` so the log aggregator can attribute
        logs correctly.
        """
        return logging.getLogger(f"experiment.{self.name or type(self).__name__}")

    @classmethod
    def parameters(cls) -> Mapping[str, ParamSpec[Any]]:
        """Read-only view of this experiment's parameters."""
        return MappingProxyType(cls._parameters)

    @classmethod
    def results(cls) -> Mapping[str, ResultSpec]:
        """Read-only view of this experiment's declared results."""
        return MappingProxyType(cls._results)

    def plot(
        self,
        *ys: ResultSpec,
        x: ResultSpec | ParamSpec | None = None,
        kind: PlotKind | None = None,
        title: str | None = None,
    ) -> None:
        """Declare a live plot relating declared results. Call from ``setup()``.

        Every ``y`` must be a result declared on this experiment; ``x`` may be a declared
        result, a declared parameter, or ``None`` (one plot point per shot).
        """
        if not ys:
            raise PlotError("plot() requires at least one result to plot")
        for y in ys:
            if not any(y is r for r in self._results.values()):
                raise PlotError(f"plot() y {y!r} is not a result declared on {type(self).__name__}")
        if x is not None:
            registry = self._results if isinstance(x, ResultSpec) else self._parameters
            if not any(x is spec for spec in registry.values()):
                raise PlotError(
                    f"plot() x {x!r} is not a result or parameter declared on {type(self).__name__}"
                )
        if "_plots" not in self.__dict__:
            self._plots = []
        self._plots.append(PlotSpec(ys=tuple(ys), x=x, kind=kind, title=title))

    def plots(self) -> tuple[PlotSpec, ...]:
        """Plots declared during ``setup()``, in declaration order."""
        return tuple(self.__dict__.get("_plots", ()))

    @final
    async def connect(self, client: Any) -> None:
        """Connects to declared service stubs and sets them as attributes."""
        for attr_name, spec in type(self)._stubs.items():
            setattr(self, attr_name, await client.service(spec.service_name, spec.stub_class))

    async def setup(self) -> None:  # noqa: B027
        """Called once after stubs are connected, before the shot loop starts.

        Implement to configure devices or open persistent streams.
        """

    async def teardown(self) -> None:  # noqa: B027
        """Called once after the shot loop ends.

        Implement to close persistent streams opened in setup(), or set devices
        to rest state.
        """

    @abstractmethod
    async def shot(self, ctx: "Context") -> pd.DataFrame: ...
