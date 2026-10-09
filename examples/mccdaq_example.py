from typing import TYPE_CHECKING

from h2pcontrol.mccdaq.v1.mccdaq_pb2 import AnalogReadRequest, AnalogWriteRequest
from h2pcontrol.mccdaq.v1.mccdaq_pb2_grpc import MccDaqServiceStub

from h2pcontrol.controller.framework import (
    Context,
    Experiment,
    Results,
    param,
    result,
    service_stub,
)

if TYPE_CHECKING:
    from h2pcontrol.mccdaq.v1.mccdaq_pb2_grpc import MccDaqServiceAsyncStub


class MccDaqSquareWave(Experiment):
    name = "MCC DAQ Example"
    mccdaq: "MccDaqServiceAsyncStub" = service_stub("mccdaq", MccDaqServiceStub)
    AO0 = param(2.0, min=2.0, max=4.0, unit="V")

    class Record(Results):
        v_in: float = result(unit="V", description="Analog input reading")

    async def shot(self, ctx: Context) -> list[Record]:
        await self.mccdaq.AnalogWrite(AnalogWriteRequest(channel=0, volts=self.AO0))
        response = await self.mccdaq.AnalogRead(AnalogReadRequest(channel=0))

        return [self.Record(v_in=response.sample.volts)]
