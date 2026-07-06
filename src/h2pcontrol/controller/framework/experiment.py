from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import pandas as pd

from .parameters import ParamSpec
from .stubs import StubSpec


@dataclass
class Context:
    shot_idx: int
    total_shots: int = 1


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
        inherited = dict(getattr(experiment_cls, "_parameters", {}))
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
        inherited_stubs = dict(getattr(experiment_cls, "_stubs", {}))
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

    async def connect(self, client: Any) -> None:
        """Called once before running the experiment to connect to all required devices."""
        for attr_name, spec in type(self)._stubs.items():
            setattr(self, attr_name, await client.service(spec.service_name, spec.stub_class))

    @abstractmethod
    async def shot(self, ctx: "Context") -> pd.DataFrame: ...
