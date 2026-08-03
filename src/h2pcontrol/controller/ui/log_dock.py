"""Docked, filterable log table aggregating controller / experiment / manager logs.

Fed synthetic-or-real ``LogLine``s via :meth:`LogDock.append_record`; never
touches the network itself. Rows are bounded by a ``deque(maxlen=…)`` in the
model. Source/level filters are multiselect (empty = all), search is a
case-insensitive substring of the message.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ..runtime.log_aggregator import LogLine

type _Index = QModelIndex | QPersistentModelIndex

_COLUMNS = ("Source", "Level", "Time", "Message")
_MAX_ROWS = 50_000

_LEVEL_TEXT = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
}
# levelno -> foreground colour
_LEVEL_COLOR = {
    logging.DEBUG: QColor(128, 128, 128),
    logging.WARNING: QColor(Qt.GlobalColor.darkYellow),
    logging.ERROR: QColor(Qt.GlobalColor.red),
}

_FILTER_LEVELS = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR)


def _level_text(level: int) -> str:
    return _LEVEL_TEXT.get(level, logging.getLevelName(level))


def _selection_summary(checked: list[str], total: int) -> str:
    """Compact label for a multiselect button: ``All`` / ``None`` / names / ``n/total``."""
    if total == 0 or len(checked) == total:
        return "All"
    if not checked:
        return "None"
    if len(checked) <= 2:
        return ", ".join(checked)
    return f"{len(checked)}/{total}"


def is_at_bottom(value: int, maximum: int) -> bool:
    return value >= maximum - 1


class MultiSelectButton[K](QToolButton):
    """A tool button whose popup menu holds checkable options (multiselect)."""

    selection_changed = Signal()

    # custom style
    _QSS = """
    QToolButton {
        border: 1px solid palette(mid);
        border-radius: 4px;
        padding: 3px 6px;
    }
    QToolButton:hover { border-color: palette(highlight); }
    QToolButton::menu-indicator { width: 0px; height: 0px; }
    QMenu {
        background: palette(base);
        border: 1px solid palette(mid);
        padding: 4px;
    }
    QMenu::item {
        padding: 4px 12px 4px 6px;
        border-radius: 4px;
    }
    QMenu::item:selected { background: palette(highlight); color: palette(highlighted-text); }
    QMenu::indicator { width: 15px; height: 15px; margin-left: 4px; }
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._menu = QMenu(self)
        self._menu.setStyleSheet(self._QSS)
        self.setStyleSheet(self._QSS)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._actions: dict[K, QAction] = {}
        self._update_text()

    def add_option(self, key: K, label: str, *, checked: bool = True) -> None:
        action = self._menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(checked)
        action.toggled.connect(self._on_toggled)
        self._actions[key] = action
        self._update_text()

    def set_checked(self, key: K, checked: bool) -> None:
        self._actions[key].setChecked(checked)

    def selected(self) -> set[K]:
        return {key for key, action in self._actions.items() if action.isChecked()}

    def _on_toggled(self, _checked: bool) -> None:
        self._update_text()
        self.selection_changed.emit()

    def _update_text(self) -> None:
        checked = [a.text() for a in self._actions.values() if a.isChecked()]
        self.setText(_selection_summary(checked, len(self._actions)))


class LogTableModel(QAbstractTableModel):
    """Table model over a bounded deque of ``LogLine`` objects.

    Emits :attr:`source_added` the first time each distinct source appears.
    """

    source_added = Signal(str)

    def __init__(self, maxlen: int = _MAX_ROWS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._records: deque[LogLine] = deque(maxlen=maxlen)
        self._sources: set[str] = set()

    def record_at(self, row: int) -> LogLine:
        return self._records[row]

    def append(self, record: LogLine) -> None:
        if len(self._records) == self._records.maxlen:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._records.popleft()
            self.endRemoveRows()

        row = len(self._records)
        self.beginInsertRows(QModelIndex(), row, row)
        self._records.append(record)
        self.endInsertRows()

        if record.source not in self._sources:
            self._sources.add(record.source)
            self.source_added.emit(record.source)

    def clear(self) -> None:
        self.beginResetModel()
        self._records.clear()
        self.endResetModel()

    # --- Qt model interface ---

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section]
        return None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        record = self._records[index.row()]
        col = index.column()

        # Show full content in tooltip, useful if cell is truncated
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if col == 0:
                return record.source
            if col == 1:
                return _level_text(record.level)
            if col == 2:
                return record.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
            return record.message

        if role == Qt.ItemDataRole.ForegroundRole:
            return _LEVEL_COLOR.get(record.level)

        return None


class LogFilterProxy(QSortFilterProxyModel):
    """Filters by source membership, level membership, and message substring."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sources: set[str] = set()
        self._levels: set[int] = set()
        self._search: str = ""

    def set_sources(self, sources: set[str]) -> None:
        self._sources = set(sources)
        self.invalidate()

    def set_levels(self, levels: set[int]) -> None:
        self._levels = set(levels)
        self.invalidate()

    def set_search(self, text: str) -> None:
        self._search = text.casefold()
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: _Index) -> bool:
        model = self.sourceModel()
        assert isinstance(model, LogTableModel)
        record = model.record_at(source_row)

        if self._sources and record.source not in self._sources:
            return False
        if self._levels and record.level not in self._levels:
            return False
        return not (self._search and self._search not in record.message.casefold())


class LogDock(QDockWidget):
    """Dock widget presenting the aggregated log as a filterable table."""

    def __init__(self, parent: QWidget | None = None, *, maxlen: int = _MAX_ROWS) -> None:
        super().__init__("Log", parent)

        self._model = LogTableModel(maxlen=maxlen)
        self._proxy = LogFilterProxy()
        self._proxy.setSourceModel(self._model)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._build_filter_bar())

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(True)
        fm = self._table.fontMetrics()
        pad = 24
        self._table.setColumnWidth(0, fm.horizontalAdvance("mccdaq-server") + pad)  # Source
        self._table.setColumnWidth(1, fm.horizontalAdvance("WARNING") + pad)  # Level
        self._table.setColumnWidth(2, fm.horizontalAdvance("00:00:00.000") + pad)  # Time
        layout.addWidget(self._table)

        self.setWidget(container)

        self._model.source_added.connect(self._on_source_added)
        self._proxy.set_levels(self._level_filter.selected())

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        bar.addWidget(QLabel("Source"))
        self._source_filter: MultiSelectButton[str] = MultiSelectButton()
        self._source_filter.selection_changed.connect(self._apply_source_filter)
        bar.addWidget(self._source_filter)

        bar.addSpacing(12)
        bar.addWidget(QLabel("Level"))
        self._level_filter: MultiSelectButton[int] = MultiSelectButton()
        # DEBUG hidden by default
        for level in _FILTER_LEVELS:
            self._level_filter.add_option(level, _level_text(level), checked=level != logging.DEBUG)
        self._level_filter.selection_changed.connect(self._apply_level_filter)
        bar.addWidget(self._level_filter)

        bar.addSpacing(12)
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search messages…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setMinimumWidth(160)
        self._search_box.textChanged.connect(self._proxy.set_search)
        bar.addWidget(self._search_box, stretch=1)

        return bar

    def _on_source_added(self, source: str) -> None:
        self._source_filter.add_option(source, source, checked=True)
        self._apply_source_filter()

    def _apply_source_filter(self) -> None:
        self._proxy.set_sources(self._source_filter.selected())

    def _apply_level_filter(self) -> None:
        self._proxy.set_levels(self._level_filter.selected())

    def append_record(self, record: LogLine) -> None:
        # Auto scroll on append if view is at bottom.
        bar = self._table.verticalScrollBar()
        was_at_bottom = is_at_bottom(bar.value(), bar.maximum())
        self._model.append(record)
        if was_at_bottom:
            self._table.scrollToBottom()
