"""Client-side gRPC call timing.

The SDK's ``Client`` creates channels internally, so instead of channel
interceptors this module wraps the *stubs* it hands out: every RPC issued by
an experiment is timed with ``time.perf_counter_ns`` and appended to an
in-memory :class:`RpcLog`. The engine tags records with the current shot
index and writes the log to a CSV next to the run's result file.

What the records mean:

- Unary calls (``Stop``, ``Program``, ``Start``, ``Configure*``) are timed
  from invocation to response — the full client-observed RPC round-trip.
- Server-streaming calls (``Capture``) log ``<method>/open`` for call
  creation plus one ``<method>/read`` record per ``read()``. For
  hardware-triggered captures a read's duration is dominated by the wait for
  arm/trigger, so those records measure hardware wait, not gRPC overhead.

Note: wrapped unary calls return a plain coroutine, not the ``grpc.aio``
call object — ``await stub.Method(req)`` works unchanged, but call-object
APIs (``cancel()``, ``initial_metadata()``) are not reachable through the
wrapper.
"""

from __future__ import annotations

import time
from typing import Any

import grpc

_STREAM_MULTICALLABLES = (
    grpc.aio.UnaryStreamMultiCallable,
    grpc.aio.StreamStreamMultiCallable,
)


class RpcLog:
    """In-memory log of timed RPCs; one dict per call/read."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        #: Set by the engine before each shot; -1 outside the shot loop
        #: (connect/setup/teardown calls).
        self.shot_idx: int = -1

    def record(self, method: str, t0_ns: int, t1_ns: int, *, ok: bool = True) -> None:
        self.records.append(
            {
                "shot_idx": self.shot_idx,
                "method": method,
                "duration_ms": (t1_ns - t0_ns) / 1e6,
                "ok": ok,
            }
        )


class _TimedStreamCall:
    """Delegates to an aio streaming call, timing each ``read()``."""

    def __init__(self, call: Any, method: str, log: RpcLog) -> None:
        self._call = call
        self._method = method
        self._log = log

    async def read(self) -> Any:
        t0 = time.perf_counter_ns()
        ok = True
        try:
            return await self._call.read()
        except BaseException:
            ok = False
            raise
        finally:
            self._log.record(f"{self._method}/read", t0, time.perf_counter_ns(), ok=ok)

    def __aiter__(self) -> Any:
        return self._call.__aiter__()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._call, name)


class InstrumentedStub:
    """Wraps a generated aio stub; multicallable attributes are timed."""

    def __init__(self, stub: Any, service_name: str, log: RpcLog) -> None:
        self._stub = stub
        self._service_name = service_name
        self._log = log

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._stub, name)
        method = f"{self._service_name}/{name}"
        if isinstance(attr, grpc.aio.UnaryUnaryMultiCallable):
            return self._wrap_unary(attr, method)
        if isinstance(attr, _STREAM_MULTICALLABLES):
            return self._wrap_stream(attr, method)
        return attr

    def _wrap_unary(self, multicallable: Any, method: str) -> Any:
        log = self._log

        def invoke(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter_ns()
            call = multicallable(*args, **kwargs)

            async def _await() -> Any:
                ok = True
                try:
                    return await call
                except BaseException:
                    ok = False
                    raise
                finally:
                    log.record(method, t0, time.perf_counter_ns(), ok=ok)

            return _await()

        return invoke

    def _wrap_stream(self, multicallable: Any, method: str) -> Any:
        log = self._log

        def invoke(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter_ns()
            call = multicallable(*args, **kwargs)
            log.record(f"{method}/open", t0, time.perf_counter_ns())
            return _TimedStreamCall(call, method, log)

        return invoke


class InstrumentedClient:
    """Delegates to the SDK ``Client``, wrapping stubs handed out by ``service()``."""

    def __init__(self, client: Any, log: RpcLog) -> None:
        self._client = client
        self._log = log

    async def service(self, name: str, stub_class: Any) -> Any:
        stub = await self._client.service(name, stub_class)
        return InstrumentedStub(stub, name, self._log)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
