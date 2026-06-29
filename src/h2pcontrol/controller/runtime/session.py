import asyncio
import importlib.util
import sys
from typing import TYPE_CHECKING, cast

import grpc
import grpc.aio
from h2pcontrol.manager.v1.manager_pb2 import ListRequest
from h2pcontrol.manager.v1.manager_pb2_grpc import ManagerServiceStub

if TYPE_CHECKING:
    from h2pcontrol.manager.v1.manager_pb2_grpc import ManagerServiceAsyncStub

from ..framework.experiment import Experiment


class Session:
    def __init__(self, manager_address: str = "localhost:50051"):
        self._address = manager_address
        self._stop_event = asyncio.Event()
        self._manager_channel: grpc.aio.Channel | None = None

    @property
    def manager_address(self) -> str:
        return self._address

    @manager_address.setter
    def manager_address(self, value: str) -> None:
        self._address = value
        self._manager_channel = None

    def load_experiment(self, path: str) -> type[Experiment]:
        """Load the first Experiment subclass found in the given .py file."""
        spec = importlib.util.spec_from_file_location("_experiment_module", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load experiment from {path!r}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"_experiment_{path}"] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        candidates = [
            v
            for v in vars(module).values()
            if isinstance(v, type) and issubclass(v, Experiment) and v is not Experiment
        ]
        if not candidates:
            raise ValueError(f"No Experiment subclass found in {path!r}")
        return candidates[0]

    async def ping_manager(self) -> bool:
        """:return True if the manager response within two seconds, else false"""
        channel = self._manager_channel or grpc.aio.insecure_channel(self._address)
        self._manager_channel = channel
        try:
            stub = cast("ManagerServiceAsyncStub", ManagerServiceStub(channel))
            await stub.List(ListRequest(), timeout=2.0)
            return True
        except Exception:
            return False
