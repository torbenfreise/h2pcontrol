from pathlib import Path

import numpy as np
import pandas as pd

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param


class SineExperiment(Experiment):
    name = "Sine"
    frequency = param(1.0, min=0.1, max=100.0, unit="Hz")
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")
    marker = param("")

    async def shot(self, ctx: Context) -> pd.DataFrame:
        t = np.linspace(0, 1.0 / self.frequency, 100)
        y = self.amplitude * np.sin(2 * np.pi * self.frequency * t)
        return pd.DataFrame({"time": [t], "signal": [y], "peak": [float(np.max(y))]})

    async def teardown(self) -> None:
        if self.marker:
            Path(self.marker).write_text("torn down")
