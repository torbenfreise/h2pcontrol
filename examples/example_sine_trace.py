import asyncio

import numpy as np
import pandas as pd

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import result


class SineTrace(Experiment):
    """
    'Measures' an entire sine wave trace each shot.
    Demonstrates the 'trace' plot kind.
    """

    name = "Sine trace"
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")
    period = param(20.0, min=2.0, max=200.0, description="samples per cycle")

    sample = result(np.ndarray, description="sample")
    signal = result(np.ndarray, unit="V", description="signal")

    async def setup(self) -> None:
        self.plot(self.signal, x=self.sample, title="Sine")

    async def shot(self, ctx: Context) -> pd.DataFrame:
        await asyncio.sleep(0.05)
        sample = np.arange(200.0)
        # Drift the phase each shot
        phase = 2 * np.pi * ctx.shot_idx / 8
        signal = self.amplitude * np.sin(2 * np.pi * sample / self.period + phase)
        return pd.DataFrame({"sample": [sample], "signal": [signal]})
