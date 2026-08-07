"""Lightweight per-shot phase timing.

``ShotTimings`` collects named wall-clock spans (``time.perf_counter_ns``)
during a single shot. The engine creates one instance per shot, hands it to
the experiment through :class:`~.experiment.Context`, times its own phases
(persistence, event emission) with the same instance, and persists one row
per shot next to the run's result file.

Span durations are wall-clock, so a span around an ``await`` measures the
full time until the awaited operation completes — including hardware waits.
Name spans so that pure software overhead (RPC round-trips, serialization)
stays distinguishable from hardware-bound waits (arm/trigger/acquisition).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class ShotTimings:
    """Named wall-clock spans for a single shot, in milliseconds.

    Re-entering the same span name accumulates (useful for loops).
    """

    def __init__(self) -> None:
        self._spans: dict[str, float] = {}

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
            self._spans[name] = self._spans.get(name, 0.0) + elapsed_ms

    def as_row(self) -> dict[str, float]:
        """Snapshot of accumulated spans (name -> milliseconds)."""
        return dict(self._spans)
