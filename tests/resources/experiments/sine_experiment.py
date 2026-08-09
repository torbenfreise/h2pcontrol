from collections.abc import Mapping
from pathlib import Path

import numpy as np

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import Results, result


class SineExperiment(Experiment):
    name = "Sine"
    frequency = param(1.0, min=0.1, max=100.0, unit="Hz")
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")
    marker = param("")

    class Record(Results):
        time: np.ndarray = result(unit="s", description="sample times")
        signal: np.ndarray = result(unit="V", description="waveform")
        peak: float = result(unit="V", description="peak amplitude")

    def metadata(self) -> Mapping[str, str]:
        # A run-level constant (the trace length) recorded as a root attribute.
        return {"n_samples": "100"}

    async def shot(self, ctx: Context) -> list[Record]:
        t = np.linspace(0, 1.0 / self.frequency, 100)
        y = self.amplitude * np.sin(2 * np.pi * self.frequency * t)
        return [self.Record(time=t, signal=y, peak=float(np.max(y)))]

    async def teardown(self) -> None:
        if self.marker:
            Path(self.marker).write_text("torn down")
