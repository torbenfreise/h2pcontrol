import hashlib
import logging
import sys
import types
from collections.abc import Callable
from pathlib import Path

from h2pcontrol.sdk.client import Client

from ..framework.experiment import Experiment

logger = logging.getLogger(__name__)


type ClientProvider = Callable[[], Client]
"""A callable yielding the current manager client."""


class Session:
    def __init__(self, manager_address: str = "localhost:50051"):
        self._address = manager_address
        self._client = Client(manager_address)

    @property
    def manager_address(self) -> str:
        return self._address

    async def set_manager_address(self, value: str) -> None:
        """Reconnect to a different manager, closing the previous client."""
        if value == self._address:
            return
        old = self._client
        self._address = value
        self._client = Client(value)
        await old.close()

    @property
    def client(self) -> Client:
        return self._client

    def load_experiment_from_source(self, source: str, path: str | Path) -> type[Experiment]:
        """Compile the experiment file text (source)  into its Experiment subclass.

        Raises ValueError if zero or more than one candidate is found.
        """
        resolved = Path(path).resolve()

        # Stable module key
        module_key = f"h2pexp_{hashlib.sha1(str(resolved).encode()).hexdigest()[:12]}"

        module = types.ModuleType(module_key)
        module.__file__ = str(resolved)
        sys.modules[module_key] = module
        code = compile(source, str(resolved), "exec")
        exec(code, module.__dict__)

        candidates = [
            v
            for v in vars(module).values()
            if isinstance(v, type)
            and issubclass(v, Experiment)
            and v is not Experiment
            and v.__module__ == module_key
        ]
        if not candidates:
            raise ValueError(f"No Experiment subclass found in {str(path)!r}")
        if len(candidates) > 1:
            names = ", ".join(c.__name__ for c in candidates)
            raise ValueError(f"File defines multiple experiments: {names} — keep one per file")
        return candidates[0]

    async def ping_manager(self) -> bool:
        """:return True if the manager responds, else False."""
        try:
            await self._client.connect()
            return True
        except Exception:
            return False
