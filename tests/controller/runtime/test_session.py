from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from h2pcontrol.controller.runtime.session import Session


class FakeClient:
    def __init__(self, address: str):
        self.address = address
        self.close = AsyncMock()


@pytest.fixture
def session():
    with patch("h2pcontrol.controller.runtime.session.Client", FakeClient):
        yield Session("localhost:50051")


def _fake(client: Any) -> FakeClient:
    assert isinstance(client, FakeClient)
    return client


@pytest.mark.asyncio
async def test_set_manager_address_closes_old_client(session: Session):
    old = _fake(session.client)
    await session.set_manager_address("localhost:9999")

    old.close.assert_awaited_once()
    assert session.client is not old
    assert _fake(session.client).address == "localhost:9999"
    assert session.manager_address == "localhost:9999"


@pytest.mark.asyncio
async def test_set_manager_address_noop_when_unchanged(session: Session):
    old = _fake(session.client)
    await session.set_manager_address("localhost:50051")

    old.close.assert_not_awaited()
    assert session.client is old


@pytest.mark.asyncio
async def test_set_manager_address_new_client_is_accessible(session: Session):
    await session.set_manager_address("localhost:9999")
    new = _fake(session.client)
    assert new.address == "localhost:9999"
