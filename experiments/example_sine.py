import asyncio
import math

import pandas as pd

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param


class ExampleExperiment(Experiment):
    name = "Example sine"
    frequency = param(1.0, min=0.01, max=100.0, unit="Hz")
    amplitude = param(1.0, min=0.0, max=100.0, unit="V")
    delay = param(0.1, min=0.0, max=5.0, unit="s")
    waveform = param("sine", choices=("sine", "square"))

    async def shot(self, ctx: Context) -> pd.DataFrame:
        await asyncio.sleep(self.delay)
        t = ctx.shot_idx / max(self.frequency, 1e-9)
        phase = math.sin(2 * math.pi * self.frequency * t)
        if self.waveform == "square":
            signal = math.copysign(self.amplitude, phase)
        else:
            signal = self.amplitude * phase
        return pd.DataFrame({"t": [t], "signal": [signal]})
