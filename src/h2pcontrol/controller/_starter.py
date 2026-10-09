"""
Example Experiment declaring a series plot.
Open it with File -> Open Experiment, set Repeats, and press Schedule.
Does not require the h2pmanager or any device servers.
"""

from h2pcontrol.controller.framework import (
    Context,
    Experiment,
    Results,
    ViewKind,
    param,
    result,
    view,
)


class Ramp(Experiment):
    # Title shown in the GUI.
    name = "Ramp"

    # Editable in the GUI. Its value is stored for every shot.
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")

    # A live plot panel. SERIES accumulates one point per push.
    signal = view("Signal", ViewKind.SERIES, y_unit="V")

    # One row of recorded data. Determines the HDF5 schema.
    class Record(Results):
        value: float = result(unit="V")

    async def shot(self, ctx: Context) -> list[Record]:
        value = self.amplitude * ctx.shot_idx
        self.signal.push(ctx.shot_idx, value)
        return [self.Record(value=value)]
