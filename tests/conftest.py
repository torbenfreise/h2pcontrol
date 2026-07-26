"""Shared test helpers available to every test module."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pytest

from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import EngineEvent

_E = TypeVar("_E", bound=EngineEvent)

_EXPERIMENTS = Path(__file__).parent / "resources" / "experiments"


@pytest.fixture
def experiments_dir() -> Path:
    """Directory of static experiment source files (tests/resources/experiments/)."""
    return _EXPERIMENTS


@pytest.fixture
def wait_for():
    """Return an awaitable that resolves when the engine emits a matching event.

    Replaces sleep-based ordering: subscribe, await an asyncio future set by the
    dispatch callback, unsubscribe.  ``count`` waits for the Nth match; an
    optional ``predicate`` filters (e.g. on shot_idx).
    """

    async def _wait_for(
        engine: RunEngine,
        event_type: type[_E],
        *,
        timeout: float = 5.0,
        count: int = 1,
        predicate: Callable[[_E], bool] | None = None,
    ) -> _E:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[_E] = loop.create_future()
        seen = 0

        def cb(event: EngineEvent) -> None:
            nonlocal seen
            if fut.done() or not isinstance(event, event_type):
                return
            if predicate is not None and not predicate(event):
                return
            seen += 1
            if seen >= count:
                fut.set_result(event)

        engine.subscribe(cb)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            with contextlib.suppress(ValueError):
                engine.unsubscribe(cb)

    return _wait_for
