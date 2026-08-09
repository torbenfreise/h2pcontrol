import asyncio

import numpy as np

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.views import ViewKind


class SineSeries(Experiment):
    """
    'Measures' one point of a sine wave form each shot.
    Demonstrates the SERIES view kind: each shot pushes one (x, y) point that
    accumulates on the panel.
    """

    name = "Sine series"
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")
    period = param(20.0, min=2.0, max=200.0, description="shots per cycle")

    class Record(Results):
        signal: float = result(unit="V", description="signal")

    async def setup(self) -> None:
        self.series = self.view("Sine", unit="V", kind=ViewKind.SERIES)

    async def shot(self, ctx: Context) -> list[Record]:
        await asyncio.sleep(0.05)
        value = self.amplitude * np.sin(2 * np.pi * ctx.shot_idx / self.period)
        self.series.push(ctx.shot_idx, value)  # a point on the live series
        return [self.Record(signal=value)]
