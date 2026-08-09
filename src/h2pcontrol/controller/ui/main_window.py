import asyncio
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)

from ..framework.parameters import ParameterError
from ..runtime.engine import RunEngine
from ..runtime.events import (
    EntryState,
    RunFinished,
    RunStarted,
)
from ..runtime.log_aggregator import LogAggregator
from ..runtime.session import Session
from ..runtime.spec import RunRequest
from ..runtime.store import RunStoreFactory
from .engine_bridge import EngineBridge
from .experiment_view import ExperimentView
from .log_dock import LogDock
from .plot_dock import PlotDock
from .schedule_dock import ScheduleDock
from .settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("h2pcontrol")

        self._settings = QSettings("h2pcontrol", "controller")
        address = self._settings.value("manager_address", "localhost:50051")
        self._session = Session(manager_address=str(address))
        # Held rather than inlined: the engine ships this factory to the writer
        # process, and Settings retargets it by assigning to ``root``.
        self._sink_factory = RunStoreFactory(str(self._settings.value("results_root", "results")))

        self._experiment_path: Path | None = None
        self._experiment_name: str = ""
        # Source code snapshot captured at File -> Open
        self._source: str = ""

        self._engine = RunEngine(
            client_provider=lambda: self._session.client,
            sink_factory=self._sink_factory,
            loader=self._session.load_experiment_from_source,
        )
        self._bridge = EngineBridge(self._engine, self)

        self._log_aggregator = LogAggregator(client_provider=lambda: self._session.client)

        self._build_menu()
        self._build_central()
        self._build_docks()
        self._build_status_bar()
        self._wire_signals()

        self._bg_tasks: set[asyncio.Task] = set()

        # Ping the manager every 10 seconds
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._schedule_ping)
        self._ping_timer.start(10_000)
        self._schedule_ping()

        # defer until qasync loop has started.
        QTimer.singleShot(0, self._log_aggregator.start)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        open_action = QAction("Open Experiment\u2026", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        edit_menu = menubar.addMenu("Edit")
        settings_action = QAction("Settings\u2026", self)
        settings_action.triggered.connect(self._on_settings)
        edit_menu.addAction(settings_action)

        self._window_menu = menubar.addMenu("Window")

    def _build_central(self) -> None:
        self._experiment_view = ExperimentView(self)
        self._experiment_panel = self._experiment_view.panel
        self._run_controls = self._experiment_view.controls
        self.setCentralWidget(self._experiment_view)

    def _build_docks(self) -> None:
        # Plot dock opens to the right of the experiment view when a run declares plots.
        self._plot_dock = PlotDock(self._bridge, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._plot_dock)
        self._plot_dock.hide()

        self._log_dock = LogDock(self)
        self._log_aggregator.subscribe(self._log_dock.append_record)
        self._schedule_dock = ScheduleDock(self._engine, self._bridge, self)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._schedule_dock)
        self.tabifyDockWidget(self._log_dock, self._schedule_dock)
        self._log_dock.raise_()

        self.resizeDocks([self._plot_dock], [600], Qt.Orientation.Horizontal)

        self._window_menu.addAction(self._plot_dock.toggleViewAction())
        self._window_menu.addAction(self._log_dock.toggleViewAction())
        self._window_menu.addAction(self._schedule_dock.toggleViewAction())

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self._conn_label = QLabel("\u25cf Disconnected")
        self._conn_label.setStyleSheet("color: red;")
        bar.addPermanentWidget(self._conn_label)

    def _wire_signals(self) -> None:
        self._run_controls.schedule_requested.connect(self._on_schedule)
        self._experiment_panel.scan_changed.connect(self._on_scan_changed)

        self._bridge.run_started.connect(self._on_run_started)
        self._bridge.run_finished.connect(self._on_run_finished)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _schedule_ping(self) -> None:
        self._spawn(self._ping())

    async def _ping(self) -> None:
        connected = await self._session.ping_manager()
        if connected:
            self._conn_label.setText(f"\u25cf {self._session.manager_address}")
            self._conn_label.setStyleSheet("color: green;")
        else:
            self._conn_label.setText("\u25cf Disconnected")
            self._conn_label.setStyleSheet("color: red;")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Experiment", "", "Python files (*.py)")
        if path:
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        try:
            source = Path(path).read_text(encoding="utf-8")
            cls = self._session.load_experiment_from_source(source, path)
            self._experiment_panel.load_experiment(cls)
            self._experiment_path = Path(path)
            self._experiment_name = cls.name or cls.__name__
            self._source = source
            self._experiment_view.set_experiment_name(self._experiment_name)
            self._run_controls.set_loaded(True)
        except Exception as exc:
            logger.exception("Failed to load experiment")
            QMessageBox.critical(self, "Load Error", str(exc))

    def _on_scan_changed(self) -> None:
        self._run_controls.set_scanning(self._experiment_panel.has_scan_axis())

    def _on_schedule(self) -> None:
        if self._experiment_path is None:
            return
        try:
            param_values = self._experiment_panel.current_values()
            scan = self._experiment_panel.current_scan_spec()
            repeats_per_point, scan_repeats = self._run_controls.run_counts()

            request = RunRequest(
                experiment_path=self._experiment_path,
                experiment_name=self._experiment_name,
                param_values=param_values,
                source=self._source,
                scan=scan,
                repeats_per_point=repeats_per_point,
                scan_repeats=scan_repeats,
            )
            self._engine.submit(request)
        except ParameterError as exc:
            QMessageBox.warning(self, "Invalid Parameters", str(exc))

    def _on_run_started(self, event: RunStarted) -> None:
        logger.info("Run %s started \u2192 %s", event.run_id, event.result_path)

    def _on_run_finished(self, event: RunFinished) -> None:
        if event.outcome == EntryState.COMPLETED:
            logger.info("Run %s completed", event.run_id)
        elif event.outcome == EntryState.STOPPED:
            logger.info("Run %s stopped", event.run_id)
        elif event.outcome == EntryState.FAILED:
            logger.error("Run %s failed: %s", event.run_id, event.error)
            message = event.error or "Unknown error"
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Run Failed", message))

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self._session.manager_address, self._sink_factory.root, self)
        if dlg.exec():
            address = dlg.address()
            self._settings.setValue("manager_address", address)
            self._sink_factory.root = dlg.results_root()
            self._settings.setValue("results_root", self._sink_factory.root)
            self._spawn(self._apply_address(address))

    async def _apply_address(self, address: str) -> None:
        await self._session.set_manager_address(address)
        await self._ping()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._bridge.close()
        for coro in (self._engine.aclose(), self._log_aggregator.aclose()):
            task = asyncio.ensure_future(coro)
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        super().closeEvent(event)
