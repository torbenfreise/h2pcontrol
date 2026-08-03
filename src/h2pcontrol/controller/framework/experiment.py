import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, final

import pandas as pd

from .parameters import ParamSpec
from .stubs import StubSpec


@dataclass(frozen=True)
class Context:
    shot_idx: int
    run_id: str = ""
    total_shots: int | None = None


class Experiment(ABC):
    name: ClassVar[str] = ""
    _parameters: ClassVar[dict[str, ParamSpec]] = {}
    _stubs: ClassVar[dict[str, StubSpec]] = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        Experiment._collect_parameters(cls)
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
                parameters = pd.DataFrame({k: [getattr(self, k)] for k in self._parameters})
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
