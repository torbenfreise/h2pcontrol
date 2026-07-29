"""Shared fixtures for integration tests."""

import asyncio
import contextlib

import pytest
import pytest_asyncio

from .example_server_mock import ExampleServerMock, load_config

MANAGER_ADDRESS = "localhost:50051"
SERVICE_PORT = 50199


@pytest_asyncio.fixture
async def fake_device():
    """Start the fake device server in the background, yield it, then shut down."""
    config = load_config(MANAGER_ADDRESS, SERVICE_PORT)
    server = ExampleServerMock(config)

    task = asyncio.create_task(server.start())

    # Give it time to register with the manager
    await asyncio.sleep(0.5)

    if task.done():
        exc = task.exception()
        pytest.skip(f"Manager not available at {MANAGER_ADDRESS}: {exc}")

    yield server

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
