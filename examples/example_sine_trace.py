import asyncio

import numpy as np

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.views import ViewKind


class SineTrace(Experiment):
    """
    'Measures' an entire sine wave trace each shot.
    Demonstrates a LINE view: the view is updated
    with the new trace each shot.
    """

    name = "Sine trace"
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")
    period = param(20.0, min=2.0, max=200.0, description="samples per cycle")

    class Record(Results):
        signal: np.ndarray = result(unit="V", description="signal")

    async def setup(self) -> None:
        self.sample = np.arange(200.0)
        self.trace = self.view("Sine", ViewKind.LINE, y_unit="V")

    async def shot(self, ctx: Context) -> list[Record]:
        await asyncio.sleep(0.05)
        # Drift the phase each shot
        phase = 2 * np.pi * ctx.shot_idx / 8
        signal = self.amplitude * np.sin(2 * np.pi * self.sample / self.period + phase)
        self.trace.push(self.sample, signal)  # live, replaces the curve
        return [self.Record(signal=signal)]
