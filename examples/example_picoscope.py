"""
This example experiment demonstrates programming a hardware-timed shot.

Requirements:
h2pmanager: https://github.com/torbenfreise/h2pcontrol-manager
picoscope-server: https://github.com/torbenfreise/picoscope-server
pulseblaster-server: https://github.com/torbenfreise/pulseblaster-server

The PulseBlaster runs an infinite square wave on output channel 0, which is
wired into the Picoscope input and acts as both signal and trigger source. Each
shot opens one Capture call asking for ``captures_per_shot`` waveforms.

When ``captures_per_shot``is 1 the scope runs a single block acquisition.
Above 1 it switches to rapid block mode, where the scope re-arms itself in
hardware between triggers and writes each waveform into its own memory segment,
collecting the requested amount of captures before returning.
The wave is stopped once the captures are in. ``shot()`` returns one
row per capture, and the traces are plotted live.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
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
from h2pcontrol.controller.framework.results import result
from h2pcontrol.controller.framework.stubs import service_stub

if TYPE_CHECKING:
    from grpc.aio import UnaryStreamCall
    from h2pcontrol.picoscope.v1.picoscope_pb2_grpc import PicoscopeServiceAsyncStub
    from h2pcontrol.pulseblaster.v1.pulseblaster_pb2_grpc import PulseBlasterServiceAsyncStub

# PulseBlaster output bit-flags
CHANNEL_0_HIGH = 0x01
ALL_LOW = 0x00


class PicoscopeRapidBlockExperiment(Experiment):
    name = "Picoscope Rapid Block"

    picoscope: PicoscopeServiceAsyncStub = service_stub("picoscope-service", PicoscopeServiceStub)
    pulseblaster: PulseBlasterServiceAsyncStub = service_stub(
        "pulseblaster-service", PulseBlasterServiceStub
    )

    # Picoscope input channel
    channel: int = 0
    voltage_range: VoltageRange = VoltageRange.VOLTAGE_RANGE_5_V
    trigger_threshold_v: float = 0.5

    # Timebase / samples.
    timebase_index: int = 4
    pre_samples: int = 0
    post_samples: int = 1000

    # Number of waveforms collected per shot in rapid block mode.
    captures_per_shot = param(1, min=1, max=1000)

    # PulseBlaster pulse period.
    period_ns = param(4000, min=200, max=100000, unit="ns")

    # Declared results: one row per capture.
    capture_index = result(int, description="Capture index within the shot")
    trigger_offset_us = result(float, unit="us", description="Trigger offset within the burst")
    times_us = result(np.ndarray, unit="us", description="Sample times")
    trace = result(np.ndarray, unit="V", description="Scope trace")

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
        await self.picoscope.ConfigureTimebase(
            ConfigureTimebaseRequest(
                timebase_index=self.timebase_index,
                num_samples_pre_trigger=self.pre_samples,
                num_samples_post_trigger=self.post_samples,
            )
        )
        await self.pulseblaster.Stop(StopRequest())
        await self.pulseblaster.Program(ProgramRequest(instructions=self.square_wave_program()))

        self.plot(self.trace, x=self.times_us, title="Picoscope captures")

    async def teardown(self) -> None:
        # Stop the pulseblaster (NO-OP if it was already stopped inside shot())
        await self.pulseblaster.Stop(StopRequest())

    async def shot(self, ctx: Context) -> pd.DataFrame:

        # Arm the picoscope trigger and open the capture stream.
        stream = self.picoscope.Capture(CaptureRequest(num_captures=self.captures_per_shot))

        # Wait for confirmation that the picoscope is armed
        armed = await _expect(stream, "armed", ctx)
        num_captures = armed.armed.num_captures

        # Start the hardware timing sequence
        await self.pulseblaster.Start(StartRequest())

        rows = []
        for expected_index in range(num_captures):
            capture = (await _expect(stream, "capture", ctx)).capture
            if capture.capture_index != expected_index:
                raise RuntimeError(
                    f"shot {ctx.shot_idx}: expected capture {expected_index}, "
                    f"got {capture.capture_index}"
                )

            trace = capture.traces[0]
            rows.append(
                {
                    "capture_index": capture.capture_index,
                    "trigger_offset_us": capture.trigger_time_offset_ns / 1000.0,
                    "times_us": np.asarray(trace.times_seconds, dtype=np.float64) * 1e6,
                    "trace": np.asarray(trace.samples, dtype=np.float32),
                }
            )

        await self.pulseblaster.Stop(StopRequest())
        return pd.DataFrame(rows)

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
