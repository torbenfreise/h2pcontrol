from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, get_args, get_origin

import pandas as pd

from .parameters import ParamSpec
from .stubs import StubSpec


@dataclass
class Context:
    shot_idx: int


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
        """Collects param() declarations and replace
        attributes with default value"""
        # merge annotations up the MRO so subclasses inherit base params
        annotations: dict[str, Any] = {}
        for klass in reversed(experiment_cls.__mro__):
            annotations.update(getattr(klass, "__annotations__", {}))

        inherited = dict(getattr(experiment_cls, "_parameters", {}))
        for name, val in list(experiment_cls.__dict__.items()):
            if not isinstance(val, ParamSpec):
                continue
            # set name
            val.name = name

            # set dtype from annotation
            ann = annotations.get(name)
            if get_origin(ann) is Literal:
                val.choices = get_args(ann)
                val.dtype = type(val.default) if val.default is not None else None
            elif isinstance(ann, type):
                val.dtype = ann
            inherited[name] = val
            setattr(experiment_cls, name, val.default)  # replace  attribute with default value

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

    def __setattr__(self, name, value):
        spec = type(self)._parameters.get(name)
        if spec is not None:
            value = spec.validate(value)
        super().__setattr__(name, value)

    async def connect(self, client: Any) -> None:
        """Called once before running the experiment to connect to all required devices."""
        for attr_name, spec in type(self)._stubs.items():
            setattr(self, attr_name, await client.service(spec.service_name, spec.stub_class))

    @abstractmethod
    async def shot(self, ctx: "Context") -> pd.DataFrame: ...
