from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDockWidget, QTabWidget, QVBoxLayout, QWidget

from ..framework.views import SeriesViewHandle, ViewHandle

if TYPE_CHECKING:
    from ..runtime.events import RunFinished, RunStarted
    from .engine_bridge import EngineBridge


pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

# Repaint dirty panels at ~30 Hz, instead of on push
# to keep ui work out of the shot.
_REPAINT_INTERVAL_MS = 33

_PEN = "#1f77b4"


class _ViewPanel:
    """One view tab. Reads its handle's buffer on repaint."""

    def __init__(self, handle: ViewHandle) -> None:
        self.handle = handle
        self.spec = handle.spec
        self._is_series = isinstance(handle, SeriesViewHandle)

        self._shot_axis = self._is_series and not self.spec.x_unit
        self.widget = pg.PlotWidget()
        self.widget.showGrid(x=True, y=True, alpha=0.3)

        if self._shot_axis:
            self._set_axis("bottom", "shot", None)
        else:
            self._set_axis("bottom", "", self.spec.x_unit)
        self._set_axis("left", self.spec.title, self.spec.y_unit)

        # Series accumulate discrete points, so mark each one
        symbol = "o" if self._is_series else None
        self.curve = self.widget.plot(
            pen=_PEN,
            symbol=symbol,
            symbolSize=2,
            symbolPen=_PEN,
            symbolBrush=_PEN,
        )

        # Crosshair
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
        """Cursor coordinates as unit-aware text."""
        xstr = f"shot {x:.0f}" if self._shot_axis else pg.siFormat(x, suffix=self.spec.x_unit or "")
        return f"{xstr},  {pg.siFormat(y, suffix=self.spec.y_unit or '')}"

    def repaint(self) -> None:
        """Draw the handle's latest buffer if it changed, then mark it painted."""
        if not self.handle.dirty:
            return
        # The lock-free buffer is only safe if pushes and repaints share a thread.
        assert self.handle.push_thread in (None, threading.get_ident()), (
            "view pushed from a different thread than the plot dock repaints on"
        )
        self.handle.clear_dirty()
        data = self.handle.plot_data()
        if data is None:
            return
        x, y = data
        self.curve.setData(x, y, connect="finite")


class PlotDock(QDockWidget):
    """Plot dock with one tab per declared view, repainted from a timer."""

    def __init__(self, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__("Plots", parent)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)
        self.setWidget(container)

        self._panels: list[_ViewPanel] = []
        self._run_id: str | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(_REPAINT_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

        bridge.run_started.connect(self._on_run_started)
        bridge.run_finished.connect(self._on_run_finished)

    def _clear(self) -> None:
        while self._tabs.count():
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._panels = []

    def _tick(self) -> None:
        for panel in self._panels:
            panel.repaint()

    def _on_run_started(self, event: RunStarted) -> None:
        self._timer.stop()
        self._clear()
        if not event.views:
            self._run_id = None
            self.hide()
            return

        self._panels = [_ViewPanel(handle) for handle in event.views]
        for i, panel in enumerate(self._panels):
            self._tabs.addTab(panel.widget, panel.spec.title or f"Plot {i + 1}")

        self._run_id = event.run_id
        self.show()
        self.raise_()
        self._timer.start()

    def _on_run_finished(self, event: RunFinished) -> None:
        # Stop repainting, but flush any final pushes and leave the plot up.
        if event.run_id == self._run_id:
            self._timer.stop()
            self._tick()
            self._run_id = None
