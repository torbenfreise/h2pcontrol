"""
Same acquisition as ``example_picoscope``, but the trace is reduced to scalars.

Requirements:
h2pmanager: https://github.com/torbenfreise/h2pcontrol-manager
picoscope-server: https://github.com/torbenfreise/picoscope-server
pulseblaster-server: https://github.com/torbenfreise/pulseblaster-server

The counterpart to ``example_picoscope``, which stores every waveform. Here each
capture is integrated over a time window and only the resulting numbers are
recorded, so a run costs a few hundred bytes per shot instead of a few kilobytes
per capture. The trace is still pushed to a view, so you watch the full waveform
live while none of it is stored — the point of the view/record split.

The window bounds are ordinary parameters. That makes them adjustable from the
GUI while the run is going, scannable like anything else, and — because every
stored row carries the current parameter values — self-describing: each
``gate_area`` is filed next to the window that produced it.

The signal is the same PulseBlaster square wave, so ``gate_area`` is amplitude
times the high fraction of the window rather than a peak area. Scanning
``period_ns`` against a fixed gate therefore gives a predictable curve, which is
the point: the demo checks itself without a detector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from h2pcontrol.picoscope.v1.picoscope_pb2 import (
    CaptureRequest,
    CaptureResponse,
    ChannelConfig,
    ConfigureChannelRequest,
    ConfigureTimebaseRequest,
    ConfigureTriggerRequest,
    Coupling,
    TriggerConfig,
    TriggerDirection,
    VoltageRange,
)
from h2pcontrol.picoscope.v1.picoscope_pb2_grpc import PicoscopeServiceStub
from h2pcontrol.pulseblaster.v1.pulseblaster_pb2 import (
    Instruction,
    InstructionProgram,
    OpCode,
    ProgramRequest,
    StartRequest,
    StopRequest,
)
from h2pcontrol.pulseblaster.v1.pulseblaster_pb2_grpc import PulseBlasterServiceStub

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.stubs import service_stub

if TYPE_CHECKING:
    from grpc.aio import UnaryStreamCall
    from h2pcontrol.picoscope.v1.picoscope_pb2_grpc import PicoscopeServiceAsyncStub
    from h2pcontrol.pulseblaster.v1.pulseblaster_pb2_grpc import PulseBlasterServiceAsyncStub

# PulseBlaster output bit-flags
CHANNEL_0_HIGH = 0x01
ALL_LOW = 0x00


class PicoscopeGatedExperiment(Experiment):
    name = "Picoscope Gated Integral"

    picoscope: PicoscopeServiceAsyncStub = service_stub("picoscope-service", PicoscopeServiceStub)
    pulseblaster: PulseBlasterServiceAsyncStub = service_stub(
        "pulseblaster-service", PulseBlasterServiceStub
    )

    # Picoscope input channel
    channel: int = 0
    voltage_range = VoltageRange.VOLTAGE_RANGE_5_V
    trigger_threshold_v: float = 1.5

    # Timebase / samples.
    timebase_index: int = 4
    pre_samples: int = 0
    post_samples: int = 1000

    # Number of waveforms collected per shot in rapid block mode.
    captures_per_shot = param(50, min=1, max=1000)

    # PulseBlaster pulse period.
    period_ns = param(20000000, min=200, max=20000000, unit="ns")

    # The integration window. Parameters, not constants: tunable while running,
    # scannable, and stored with every row so the reduction stays interpretable.
    gate_start_us = param(2.0, min=0.0, max=16.0, unit="us")
    gate_stop_us = param(10.0, min=0.0, max=16.0, unit="us")

    # Declared results: one row per capture, scalars only. The waveform the
    # numbers came from is viewed live and never stored.
    class Record(Results):
        capture_index: int = result(description="Capture index within the shot")
        gate_area: float = result(unit="V*us", description="Integral over the gate window")
        baseline: float = result(unit="V", description="Mean before the gate, subtracted")

    async def setup(self) -> None:
        await self.picoscope.ConfigureChannel(
            ConfigureChannelRequest(
                channel=ChannelConfig(
                    channel_index=self.channel,
                    enabled=True,
                    coupling=Coupling.COUPLING_DC,
                    voltage_range=self.voltage_range,
                    analog_offset_volts=0.0,
                )
            )
        )
        await self.picoscope.ConfigureTrigger(
            ConfigureTriggerRequest(
                trigger=TriggerConfig(
                    channel_index=self.channel,
                    enabled=True,
                    direction=TriggerDirection.TRIGGER_DIRECTION_RISING,
                    threshold_mv=self.trigger_threshold_v * 1000,
                )
            )
        )
        timebase = await self.picoscope.ConfigureTimebase(
            ConfigureTimebaseRequest(
                timebase_index=self.timebase_index,
                num_samples_pre_trigger=self.pre_samples,
                num_samples_post_trigger=self.post_samples,
            )
        )

        # The sample grid is fixed by the timebase, so build it once here. The
        # gate *indices* are not cached: setup() runs before the scan loop
        # assigns per-point values, so a window resolved here would go stale the
        # moment anyone scans its bounds.
        self.times_us = np.arange(self.post_samples) * timebase.sample_interval_ns / 1000.0
        self.captures = self.view("Picoscope captures", x=self.times_us, x_unit="us", unit="V")

        # Last program uploaded to the pulseblaster; used to skip re-uploading an
        # identical waveform every shot (see shot()).
        self._last_program: InstructionProgram | None = None

    async def teardown(self) -> None:
        # Stop the pulseblaster (NO-OP if it was already stopped inside shot())
        await self.pulseblaster.Stop(StopRequest())

    async def shot(self, ctx: Context) -> list[Record]:
        # Phase spans (ctx.span) subdivide the engine's per-shot "shot" span
        # into software overhead vs hardware-inclusive waits; they land in
        # <run>_timings.csv and are no-ops when timing is disabled.

        # Program the pulseblaster, but only when the waveform actually changed
        # (e.g. a new period_ns scan point). Re-uploading an identical program
        # every shot is pure overhead; skipping it also frees the start of the
        # shot so a background save can overlap the capture wait. Scans still
        # reprogram whenever a parameter shapes a different waveform.
        program = self.square_wave_program()
        if program != self._last_program:
            with ctx.span("pb_program"):
                await self.pulseblaster.Program(ProgramRequest(instructions=program))
            self._last_program = program

        # Arm the picoscope trigger and open the capture stream.
        with ctx.span("capture_open"):
            stream = self.picoscope.Capture(CaptureRequest(num_captures=self.captures_per_shot))

        # Wait for confirmation that the picoscope is armed (scope arm time).
        with ctx.span("armed_wait"):
            await _expect(stream, "armed", ctx)

        # Start the hardware timing sequence
        with ctx.span("pb_start"):
            await self.pulseblaster.Start(StartRequest())

        rows = []
        for expected_index in range(self.captures_per_shot):
            # In rapid block the scope collects all captures before streaming
            # them back: the first read carries the full trigger/acquisition
            # wait, the remaining reads are mostly gRPC trace transfer.
            wait_span = "capture_wait_first" if expected_index == 0 else "capture_wait_rest"
            with ctx.span(wait_span):
                capture = (await _expect(stream, "capture", ctx)).capture
            if capture.capture_index != expected_index:
                raise RuntimeError(
                    f"shot {ctx.shot_idx}: expected capture {expected_index}, "
                    f"got {capture.capture_index}"
                )

            with ctx.span("frame_build"):
                samples = np.asarray(capture.traces[0].samples, dtype=np.float32)
            with ctx.span("plot_push"):
                self.captures.push(samples)  # live, per capture, not stored

            with ctx.span("integrate"):
                area, baseline = self.integrate(samples)
            with ctx.span("frame_build"):
                rows.append(
                    self.Record(
                        capture_index=capture.capture_index,
                        gate_area=area,
                        baseline=baseline,
                    )
                )

        with ctx.span("pb_stop"):
            await self.pulseblaster.Stop(StopRequest())

        return rows

    def integrate(self, samples: np.ndarray) -> tuple[float, float]:
        """Integrate one trace over the gate, against the mean before it.

        Resolved per call rather than cached: searchsorted on the sample grid is
        far cheaper than a window that silently disagrees with the parameters
        stored alongside its own output.
        """
        start, stop = np.searchsorted(self.times_us, [self.gate_start_us, self.gate_stop_us])
        baseline = float(samples[:start].mean()) if start > 0 else 0.0
        area = float(np.trapezoid(samples[start:stop] - baseline, self.times_us[start:stop]))
        return area, baseline

    def square_wave_program(self) -> InstructionProgram:
        """
        Program an infinite square wave on output channel 0.
        Each rising edge will trigger a picoscope acquisition.
        """
        half_period_ns = int(self.period_ns // 2)
        return InstructionProgram(
            instructions=[
                # Set channel 0 to high and continue
                Instruction(
                    flags=CHANNEL_0_HIGH,
                    op_code=OpCode.OP_CODE_CONTINUE,
                    inst_data=0,
                    duration_ns=half_period_ns,
                ),
                # Set all low and branch back to instruction 0
                Instruction(
                    flags=ALL_LOW,
                    op_code=OpCode.OP_CODE_BRANCH,
                    inst_data=0,
                    duration_ns=half_period_ns,
                ),
            ]
        )


async def _expect(
    stream: UnaryStreamCall[CaptureRequest, CaptureResponse],
    event: str,
    ctx: Context,
) -> CaptureResponse:
    """Read the next CaptureResponse  and assert on its event type."""
    response = await stream.read()
    if not isinstance(response, CaptureResponse) or response.WhichOneof("event") != event:
        raise RuntimeError(
            f"shot {ctx.shot_idx}: expected {event} from picoscope, got {response!r}"
        )
    return response
