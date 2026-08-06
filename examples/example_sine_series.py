import asyncio

import numpy as np
import pandas as pd

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import result


class SineSeries(Experiment):
    """
    'Measures' one point of a sine wave form each shot.
    Demonstrates the 'series' plot kind.
    """

    name = "Sine series"
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")
    period = param(20.0, min=2.0, max=200.0, description="shots per cycle")

    signal = result(float, unit="V", description="signal")

    async def setup(self) -> None:
        self.plot(self.signal, title="Sine")

    async def shot(self, ctx: Context) -> pd.DataFrame:
        await asyncio.sleep(0.05)
        value = self.amplitude * np.sin(2 * np.pi * ctx.shot_idx / self.period)
        return pd.DataFrame({"signal": [value]})
