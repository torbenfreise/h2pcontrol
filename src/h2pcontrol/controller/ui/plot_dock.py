from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QTabWidget, QVBoxLayout, QWidget

from ..framework.parameters import ParamSpec
from ..framework.results import PlotKind, PlotSpec, ResultSpec

if TYPE_CHECKING:
    import pandas as pd

    from ..runtime.events import RunFinished, RunStarted, ShotCompleted
    from .engine_bridge import EngineBridge


pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

# Distinct pen colours for plots with multiple curves.
_PENS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b")


def _axis_label(spec: ResultSpec | ParamSpec) -> str:
    return spec.description or spec.name or ""


def _column(frame: pd.DataFrame, spec: ResultSpec | ParamSpec) -> list:
    """``spec``'s column as one entry per row of the shot frame."""
    top = "params" if isinstance(spec, ParamSpec) else "result"
    return list(frame[(top, spec.name)])


def _join_rows(arrays: list) -> np.ndarray:
    """Concatenate per-row arrays into one curve, separated by blank space."""
    separator = np.array([np.nan])  # NaN stops pyqt from joining points.
    parts: list[np.ndarray] = []
    for array in arrays:
        parts.append(np.asarray(array, dtype=float))
        parts.append(separator)
    return np.concatenate(parts[:-1])


def _tab_label(spec: PlotSpec, index: int) -> str:
    if spec.title:
        return spec.title
    names = [str(y.description or y.name) for y in spec.ys if (y.description or y.name)]
    if len(names) > 2:
        names = [*names[:2], "…"]
    return ", ".join(names) or f"Plot {index + 1}"


class _PlotPanel:
    """One plot tab."""

    def __init__(self, spec: PlotSpec) -> None:
        self.spec = spec
        self.kind = spec.resolve_kind()
        self.widget = pg.PlotWidget()
        self.widget.showGrid(x=True, y=True, alpha=0.3)

        if self.spec.x is not None:
            self._set_axis("bottom", _axis_label(self.spec.x), self.spec.x.unit)
        else:
            self._set_axis("bottom", "shot", None)
        y0 = self.spec.ys[0]
        self._set_axis("left", _axis_label(y0), y0.unit)

        if len(spec.ys) > 1:
            self.widget.addLegend()
        # Series accumulate discrete points, so mark each one.
        # If we don't do this, the reuslt of  single shot will be invisible.
        symbol = "o" if self.kind == PlotKind.SERIES else None
        self.curves = []
        for i, y in enumerate(spec.ys):
            pen = _PENS[i % len(_PENS)]
            self.curves.append(
                self.widget.plot(
                    pen=pen,
                    name=_axis_label(y),
                    symbol=symbol,
                    symbolSize=2,
                    symbolPen=pen,
                    symbolBrush=pen,
                )
            )

        self._xs: list[float] = []
        self._ys: list[list[float]] = [[] for _ in spec.ys]
        self._row_counter = 0

        # Crosshair
        self._y_unit = y0.unit or ""
        pen = pg.mkPen((120, 120, 120), width=1, style=Qt.PenStyle.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        self._coord = pg.TextItem(color="k", anchor=(0, 1), fill=(255, 255, 255, 180))

        plot_item = self.widget.getPlotItem()
        assert plot_item is not None
        self._plot_item = plot_item
        vb = plot_item.getViewBox()
        assert vb is not None
        self._vb = vb
        for item in (self._vline, self._hline, self._coord):
            item.setVisible(False)
            plot_item.addItem(item, ignoreBounds=True)
        scene = plot_item.scene()
        assert scene is not None
        self._proxy = pg.SignalProxy(
            scene.sigMouseMoved,  # pyright: ignore[reportAttributeAccessIssue]
            rateLimit=60,
            slot=self._on_mouse_moved,
        )

    def _set_axis(self, side: str, label: str, unit: str | None) -> None:
        """Label an axis, disabling pyqtgraph's SI-prefix scaling when there is no unit."""
        self.widget.setLabel(side, label, units=unit or "")
        if not unit:
            self.widget.getAxis(side).enableAutoSIPrefix(False)

    def _on_mouse_moved(self, evt: tuple) -> None:
        pos = evt[0]  # SignalProxy delivers the signal args as a tuple
        if not self._plot_item.sceneBoundingRect().contains(pos):
            for item in (self._vline, self._hline, self._coord):
                item.setVisible(False)
            return
        pt = self._vb.mapSceneToView(pos)
        self._vline.setPos(pt.x())
        self._hline.setPos(pt.y())
        self._coord.setPos(pt.x(), pt.y())
        self._coord.setText(self._format_coord_text(pt.x(), pt.y()))
        for item in (self._vline, self._hline, self._coord):
            item.setVisible(True)

    def _format_coord_text(self, x: float, y: float) -> str:
        """Cursor coordinates as unit-aware text (x is the shot index when no x-result)."""
        if self.spec.x is not None:
            xstr = pg.siFormat(x, suffix=self.spec.x.unit or "")
        else:
            xstr = f"shot {x:.0f}"
        ystr = pg.siFormat(y, suffix=self._y_unit)
        return f"{xstr},  {ystr}"

    def update(self, frame: pd.DataFrame) -> None:
        if self.kind == PlotKind.SERIES:
            if self.spec.x is None:
                n = len(frame)
                xs = list(range(self._row_counter, self._row_counter + n))
                self._row_counter += n
            else:
                xs = _column(frame, self.spec.x)
            self._xs.extend(xs)
            for i, y in enumerate(self.spec.ys):
                self._ys[i].extend(_column(frame, y))
                self.curves[i].setData(self._xs, self._ys[i])
        else:  # LINE: replace the curve with every row of this shot
            xs = _join_rows(_column(frame, self.spec.x)) if self.spec.x is not None else None
            for i, y in enumerate(self.spec.ys):
                ys = _join_rows(_column(frame, y))
                if xs is not None:
                    self.curves[i].setData(xs, ys, connect="finite")
                else:
                    self.curves[i].setData(ys, connect="finite")


class PlotDock(QDockWidget):
    """Plot dock with multiple plot panels."""

    def __init__(self, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__("Plots", parent)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)
        self.setWidget(container)

        self._panels: list[_PlotPanel] = []
        self._run_id: str | None = None

        bridge.run_started.connect(self._on_run_started)
        bridge.shot_completed.connect(self._on_shot_completed)
        bridge.run_finished.connect(self._on_run_finished)

    def _clear(self) -> None:
        while self._tabs.count():
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._panels = []

    def _on_run_started(self, event: RunStarted) -> None:
        if not event.plots:
            self._run_id = None
            self._clear()
            self.hide()
            return

        self._clear()
        self._panels = [_PlotPanel(spec) for spec in event.plots]
        for i, panel in enumerate(self._panels):
            self._tabs.addTab(panel.widget, _tab_label(panel.spec, i))

        self._run_id = event.run_id
        self.show()
        self.raise_()

    def _on_shot_completed(self, event: ShotCompleted) -> None:
        if event.run_id != self._run_id:
            return
        for panel in self._panels:
            panel.update(event.frame)

    def _on_run_finished(self, event: RunFinished) -> None:
        # Stop updating, but leave the plot up.
        if event.run_id == self._run_id:
            self._run_id = None
