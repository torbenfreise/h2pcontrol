import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, final

import pandas as pd

from .parameters import ParamSpec
from .results import Results, ResultSpec
from .stubs import StubSpec
from .views import ViewHandle, ViewSpec


@dataclass(frozen=True)
class Context:
    shot_idx: int
    run_id: str = ""
    total_shots: int | None = None


class _NoRecord(Results):
    """Default record for experiments that declare no results."""


class Experiment(ABC):
    name: ClassVar[str] = ""
    _parameters: ClassVar[dict[str, ParamSpec]] = {}
    _results: ClassVar[dict[str, ResultSpec]] = {}
    _record: ClassVar[type[Results]] = _NoRecord
    _stubs: ClassVar[dict[str, StubSpec]] = {}
    _views: ClassVar[dict[str, ViewSpec]] = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        Experiment._collect_parameters(cls)
        Experiment._collect_results(cls)
        Experiment._collect_stubs(cls)
        Experiment._collect_views(cls)

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
        """Find the experiment's inner ``Results`` subclass  and derive
        the storage schema from it."""
        for val in vars(experiment_cls).values():
            if isinstance(val, type) and issubclass(val, Results) and val is not Results:
                experiment_cls._record = val
                break
        experiment_cls._results = experiment_cls._record.specs()

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
    def _collect_views(experiment_cls) -> None:
        """
        Collects view() declarations. The ViewSpec stays on the class as a data descriptor:
        class access yields the spec, instance access that instance's handle.
        """
        inherited = dict(experiment_cls._views)
        for name, val in list(experiment_cls.__dict__.items()):
            if isinstance(val, ViewSpec):
                inherited[name] = val

        experiment_cls._views = inherited

    @final
    async def record(self, ctx: "Context") -> pd.DataFrame:
        """
        Run the user's shot, and return the results + parameters
        as a Pandas dataframe.
        """
        frame = type(self)._record.to_frame(await self.shot(ctx))
        parameters = pd.DataFrame(
            {k: [getattr(self, k)] * len(frame) for k in self._parameters},
            index=frame.index,
        )
        frame.columns = pd.MultiIndex.from_product([["result"], frame.columns])
        parameters.columns = pd.MultiIndex.from_product([["params"], parameters.columns])
        return pd.concat([frame, parameters], axis=1)

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

    def views(self) -> tuple[ViewHandle, ...]:
        """This instance's handles for every view declared on the class, in declaration order."""
        return tuple(getattr(self, name) for name in type(self)._views)

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

    def metadata(self) -> Mapping[str, str]:
        """Run-level metadata written to the result file's root attributes.

        Called once after ``setup()``, so it can refer to values populated there.
        Constant for the whole run.
        """
        return {}

    @abstractmethod
    async def shot(self, ctx: "Context") -> Sequence[Results]:
        """Run one shot and return its recorded rows.

        Return a list of ``self.Record(...)`` instances (one per row).
        """
        ...
