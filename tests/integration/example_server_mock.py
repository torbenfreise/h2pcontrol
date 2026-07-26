"""Fake ExampleService device server using the h2pcontrol SDK Server class.

Usage as a pytest fixture or standalone (for manual testing).
Configure via environment variables (same as any h2pcontrol service):
    MANAGER__ADDRESS=localhost:50051
    MANAGER__RETRY_INTERVAL_S=5
    SERVICE__NAME=example-service
    SERVICE__DESCRIPTION=Fake ExampleService for integration tests
    SERVICE__ADDRESS=localhost:50199
"""

import asyncio
import logging
import os

from h2pcontrol.example.v1.example_pb2 import SayHelloResponse
from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceServicer
from h2pcontrol.sdk.server import Server
from h2pcontrol.sdk.server._config import ServerConfig

logger = logging.getLogger(__name__)


class ExampleServerMock(ExampleServiceServicer, Server):
    """Minimal ExampleService that echoes back a greeting."""

    def __init__(self, config: ServerConfig) -> None:
        Server.__init__(self, config)
        self.call_count = 0

    def _healthy(self) -> bool:
        return True

    async def SayHello(self, request, context):  # type: ignore[override]
        self.call_count += 1
        return SayHelloResponse(message=f"Hello, {request.name}!")


def load_config(
    manager_address: str = "localhost:50051",
    service_port: int = 50199,
) -> ServerConfig:
    """Load ServerConfig from env vars, setting defaults for test use."""
    os.environ.setdefault("MANAGER__ADDRESS", manager_address)
    os.environ.setdefault("MANAGER__RETRY_INTERVAL_S", "5")
    os.environ.setdefault("SERVICE__NAME", "example-service")
    os.environ.setdefault("SERVICE__DESCRIPTION", "Fake ExampleService for integration tests")
    os.environ.setdefault("SERVICE__ADDRESS", f"localhost:{service_port}")
    return ServerConfig.load()


async def run_server(
    manager_address: str = "localhost:50051",
    service_port: int = 50199,
) -> None:
    """Run the mock server (blocks until cancelled)."""
    config = load_config(manager_address, service_port)
    server = ExampleServerMock(config)
    await server.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())
