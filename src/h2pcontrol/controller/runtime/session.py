import importlib.util
import sys
from pathlib import Path

from h2pcontrol.sdk.client import Client

from ..framework.experiment import Experiment


class Session:
    def __init__(self, manager_address: str = "localhost:50051"):
        self._address = manager_address
        self._client = Client(manager_address)

    @property
    def manager_address(self) -> str:
        return self._address

    @manager_address.setter
    def manager_address(self, value: str) -> None:
        self._address = value
        self._client = Client(value)

    @property
    def client(self) -> Client:
        return self._client

    def load_experiment(self, path: str) -> type[Experiment]:
        """Load the first Experiment subclass found in the given .py file."""
        if not Path(path).is_file():
            raise ImportError(f"Cannot load experiment from {path!r}")
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
        """:return True if the manager responds, else False."""
        try:
            await self._client._ensure_connected()
            return True
        except Exception:
            return False
