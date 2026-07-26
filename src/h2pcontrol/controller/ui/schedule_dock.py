from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..runtime.events import EngineState, EntryState, QueueChanged, QueueEntry, RunId, ShotCompleted

if TYPE_CHECKING:
    from ..runtime.engine import RunEngine
    from ..runtime.spec import RunRequest
    from .engine_bridge import EngineBridge


def format_request(request: RunRequest) -> str:
    """Format a RunRequest for the details dialog."""

    lines = [
        f"Experiment: {request.experiment_name}",
        "",
        "Parameters:",
    ]
    for name, value in request.param_values.items():
        lines.append(f"  {name} = {value!r}")

    if request.scan:
        lines.append("")
        lines.append("Scan:")
        for axis in request.scan.axes:
            lines.append(f"  {axis.summary()}")
        if request.scan.zipped_groups:
            lines.append(f"  zipped: {sorted(request.scan.zipped_groups)}")

    lines.append("")
    lines.append(f"Repeats per point: {request.repeats_per_point}")
    reps = "∞" if request.scan_repeats is None else str(request.scan_repeats)
    lines.append(f"Scan repeats: {reps}")

    return "\n".join(lines)


_GREY = QColor(128, 128, 128)
_TERMINAL = (
    EntryState.COMPLETED,
    EntryState.FAILED,
    EntryState.STOPPED,
    EntryState.CANCELLED,
)


class ScheduleDock(QDockWidget):
    """Dock widget showing the run queue as a table."""

    def __init__(
        self,
        engine: RunEngine,
        bridge: EngineBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Schedule", parent)
        self._engine = engine
        self._run_ids: list[RunId] = []

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self._clear_btn = QPushButton("Clear completed")
        self._clear_btn.setToolTip("Remove finished entries (completed / failed / stopped)")
        self._clear_btn.clicked.connect(self._engine.clear_finished)
        toolbar.addWidget(self._clear_btn)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Experiment", "State", "Progress"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)

        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        self.setWidget(container)

        bridge.queue_changed.connect(self._on_queue_changed)
        bridge.shot_completed.connect(self._on_shot_completed)
        bridge.state_changed.connect(self._on_state_changed)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._size_columns()

    def _size_columns(self) -> None:
        """Ensure that each column is as wide as its text.
        Distribute remaining width favouring the experiment column."""
        header = self._table.horizontalHeader()
        total = self._table.viewport().width()
        if total <= 0:
            return
        # Minimum width to fit the header and cell content.
        mins = [max(self._table.sizeHintForColumn(c), header.sectionSizeHint(c)) for c in range(3)]
        self._table.setMinimumWidth(sum(mins) + (self._table.width() - total))
        extra = max(0, total - sum(mins))
        shares = (4, 1, 1)
        widths = [m + extra * s // sum(shares) for m, s in zip(mins, shares, strict=True)]
        widths[0] += total - sum(widths)
        for col, width in enumerate(widths):
            self._table.setColumnWidth(col, width)

    def _state_text(self, entry: QueueEntry) -> str:
        if entry.state == EntryState.QUEUED:
            return "pending"
        if entry.state == EntryState.RUNNING and self._engine.state is EngineState.STOPPING:
            return "stopping"
        return entry.state.value

    def _entry_at(self, row: int) -> QueueEntry | None:
        if row < 0 or row >= len(self._run_ids):
            return None
        run_id = self._run_ids[row]
        return next((e for e in self._engine.queue if e.run_id == run_id), None)

    def _on_queue_changed(self, event: QueueChanged) -> None:
        self._table.setRowCount(len(event.entries))
        self._run_ids = [e.run_id for e in event.entries]

        for row, entry in enumerate(event.entries):
            name_item = QTableWidgetItem(entry.request.experiment_name)
            state_item = QTableWidgetItem(self._state_text(entry))
            progress_item = QTableWidgetItem("")

            # Grey out finished entries
            if entry.state in _TERMINAL:
                for item in (name_item, state_item, progress_item):
                    item.setForeground(_GREY)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, state_item)
            self._table.setItem(row, 2, progress_item)

        self._size_columns()

    def _on_shot_completed(self, event: ShotCompleted) -> None:
        if event.run_id not in self._run_ids:
            return
        row = self._run_ids.index(event.run_id)
        item = self._table.item(row, 2)
        if item is None:
            return
        total = str(event.total_shots) if event.total_shots is not None else "—"
        item.setText(f"{event.shot_idx + 1}/{total}")

    def _on_state_changed(self, event: object) -> None:
        """Refresh the running row's State cell."""
        by_id = {e.run_id: e for e in self._engine.queue}
        for row, run_id in enumerate(self._run_ids):
            entry = by_id.get(run_id)
            if entry is not None and entry.state == EntryState.RUNNING:
                item = self._table.item(row, 1)
                if item is not None:
                    item.setText(self._state_text(entry))

    def _menu_for(self, entry: QueueEntry) -> QMenu:
        """Per-entry context menu."""
        menu = QMenu(self._table)
        if entry.state == EntryState.QUEUED:
            act = menu.addAction("Cancel")
            act.triggered.connect(lambda *_: self._engine.cancel(entry.run_id))
        elif entry.state == EntryState.RUNNING:
            soft = menu.addAction("Stop after current shot")
            soft.triggered.connect(lambda *_: self._engine.stop_current(hard=False))
            hard = menu.addAction("Force terminate")
            hard.triggered.connect(lambda *_: self._engine.stop_current(hard=True))
        else:
            act = menu.addAction("Cancel")
            act.setEnabled(False)
        return menu

    def _on_context_menu(self, pos: QPoint) -> None:
        entry = self._entry_at(self._table.rowAt(pos.y()))
        if entry is None:
            return
        menu = self._menu_for(entry)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _details_dialog(self, entry: QueueEntry) -> QDialog:
        """Build the run-details dialog for *entry*."""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Run details — {entry.request.experiment_name}")
        dlg.resize(560, 480)
        layout = QVBoxLayout(dlg)

        summary = QPlainTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText(format_request(entry.request))
        summary.setMaximumHeight(180)
        layout.addWidget(summary)

        header = QHBoxLayout()
        header.addWidget(QLabel("Source"))
        header.addStretch()
        copy_btn = QPushButton("Copy source")
        copy_btn.clicked.connect(lambda: self._copy_source(entry.request.source))
        header.addWidget(copy_btn)
        layout.addLayout(header)

        source_view = QPlainTextEdit()
        source_view.setObjectName("source_view")
        source_view.setReadOnly(True)
        source_view.setPlainText(entry.request.source)
        source_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        source_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(source_view, stretch=1)

        return dlg

    @staticmethod
    def _copy_source(source: str) -> None:
        QGuiApplication.clipboard().setText(source)

    def _on_double_click(self, index: QModelIndex) -> None:
        entry = self._entry_at(index.row())
        if entry is None:
            return
        self._details_dialog(entry).exec()
