import asyncio
import traceback
from collections.abc import Coroutine
from typing import Any

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..framework.experiment import Context, Experiment
from ..framework.scan import Scan
from ..runtime.session import Session
from .experiment_panel import ExperimentPanel, _ParamApplyError
from .run_controls import RunControls
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("h2pcontrol")

        self._settings = QSettings("h2pcontrol", "controller")
        address = self._settings.value("manager_address", "localhost:50051")
        self._session = Session(manager_address=str(address))

        self._build_menu()
        self._build_central()
        self._build_status_bar()

        self._bg_tasks: set[asyncio.Task] = set()
        self._run_task: asyncio.Task | None = None

        # Ping the manager every 10 seconds
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._schedule_ping)
        self._ping_timer.start(10_000)
        self._schedule_ping()

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        open_action = QAction("Open Experiment…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        edit_menu = menubar.addMenu("Edit")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._on_settings)
        edit_menu.addAction(settings_action)

    def _build_central(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        self._experiment_panel = ExperimentPanel()
        layout.addWidget(self._experiment_panel, stretch=1)

        self._run_controls = RunControls()
        self._run_controls.run_requested.connect(self._on_run)
        self._run_controls.stop_requested.connect(self._on_stop)
        layout.addWidget(self._run_controls)

        self.setCentralWidget(central)

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self._conn_label = QLabel("● Disconnected")
        self._conn_label.setStyleSheet("color: red;")
        bar.addPermanentWidget(self._conn_label)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _schedule_ping(self) -> None:
        self._spawn(self._ping())

    async def _ping(self) -> None:
        connected = await self._session.ping_manager()
        if connected:
            self._conn_label.setText(f"● {self._session.manager_address}")
            self._conn_label.setStyleSheet("color: green;")
        else:
            self._conn_label.setText("● Disconnected")
            self._conn_label.setStyleSheet("color: red;")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Experiment", "", "Python files (*.py)")
        if path:
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        try:
            cls = self._session.load_experiment(path)
            self._experiment_panel.load_experiment(cls)
            display_name = cls.name or cls.__name__
            self.setWindowTitle(f"h2pcontrol — {display_name}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Load Error", str(exc))

    def _on_run(self, repeats: int) -> None:
        try:
            experiment = self._experiment_panel.initialise_experiment()
        except _ParamApplyError as exc:
            QMessageBox.warning(self, "Invalid Parameters", str(exc))
            return
        scan = self._experiment_panel.get_scan()
        self._run_task = asyncio.ensure_future(self._run_loop(experiment, repeats, scan))
        self._bg_tasks.add(self._run_task)
        self._run_task.add_done_callback(self._bg_tasks.discard)
        self._run_controls.set_running(True)

    def _on_stop(self) -> None:
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()

    async def _run_loop(
        self, experiment: Experiment, repeats: int, scan: Scan | None = None
    ) -> None:
        try:
            if scan is not None:
                scan.validate_for(type(experiment))
            await experiment.connect(self._session.client)
            points = list(scan.points()) if scan else [{}]
            total = len(points) * repeats
            shot_idx = 0
            for point in points:
                for param_name, value in point.items():
                    setattr(experiment, param_name, value)
                for _ in range(repeats):
                    ctx = Context(shot_idx=shot_idx, total_shots=total)
                    frame = await experiment.shot(ctx)
                    self._run_controls.on_shot_complete(shot_idx, total, frame)
                    shot_idx += 1
        except asyncio.CancelledError:
            self._run_controls.log("Stopped")
        except Exception as exc:
            traceback.print_exc()
            self._run_controls.log(f"Error: {exc}")
        finally:
            self._run_controls.set_running(False)
            self._run_task = None

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self._session.manager_address, self)
        if dlg.exec():
            address = dlg.address()
            self._session.manager_address = address
            self._settings.setValue("manager_address", address)
            self._schedule_ping()
