import asyncio
from typing import TYPE_CHECKING, cast

import grpc
import grpc.aio
from h2pcontrol.manager.v1.manager_pb2 import ListRequest
from h2pcontrol.manager.v1.manager_pb2_grpc import ManagerServiceStub

if TYPE_CHECKING:
    from h2pcontrol.manager.v1.manager_pb2_grpc import ManagerServiceAsyncStub


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
