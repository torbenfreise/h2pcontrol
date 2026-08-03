from __future__ import annotations

import logging
from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from h2pcontrol.controller.runtime.log_aggregator import LogLine
from h2pcontrol.controller.ui.log_dock import (
    LogDock,
    LogFilterProxy,
    LogTableModel,
    is_at_bottom,
)


def _rec(
    source: str = "h2pcontrol",
    level: int = logging.INFO,
    message: str = "msg",
) -> LogLine:
    return LogLine(
        source=source,
        level=level,
        timestamp=datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC),
        message=message,
    )


class TestModel:
    def test_append_and_row_column_count(self, qtbot):
        model = LogTableModel()
        model.append(_rec(source="picoscope", level=logging.WARNING, message="warm"))
        assert model.rowCount() == 1
        assert model.columnCount() == 4

    def test_display_columns(self, qtbot):
        model = LogTableModel()
        model.append(_rec(source="Rabi", level=logging.ERROR, message="boom"))

        def cell(col: int):
            return model.data(model.index(0, col), Qt.ItemDataRole.DisplayRole)

        assert cell(0) == "Rabi"
        assert cell(1) == "ERROR"
        assert cell(3) == "boom"

    def test_level_text_variants(self, qtbot):
        model = LogTableModel()
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            model.append(_rec(level=level))
        rows = [model.data(model.index(r, 1), Qt.ItemDataRole.DisplayRole) for r in range(4)]
        assert rows == ["DEBUG", "INFO", "WARN", "ERROR"]

    def test_foreground_colors(self, qtbot):
        model = LogTableModel()
        model.append(_rec(level=logging.DEBUG))
        model.append(_rec(level=logging.INFO))
        model.append(_rec(level=logging.ERROR))

        def color(row: int):
            return model.data(model.index(row, 1), Qt.ItemDataRole.ForegroundRole)

        assert color(0) == QColor(128, 128, 128)
        assert color(1) is None  # INFO uses the default text colour
        assert color(2) == QColor(Qt.GlobalColor.red)

    def test_eviction_at_maxlen(self, qtbot):
        model = LogTableModel(maxlen=3)
        for i in range(5):
            model.append(_rec(message=f"m{i}"))
        assert model.rowCount() == 3
        messages = [model.data(model.index(r, 3), Qt.ItemDataRole.DisplayRole) for r in range(3)]
        assert messages == ["m2", "m3", "m4"]

    def test_clear(self, qtbot):
        model = LogTableModel()
        model.append(_rec())
        model.clear()
        assert model.rowCount() == 0


class TestProxyFiltering:
    def _model_proxy(self, records: list[LogLine]) -> tuple[LogTableModel, LogFilterProxy]:
        model = LogTableModel()
        proxy = LogFilterProxy()
        proxy.setSourceModel(model)
        for rec in records:
            model.append(rec)
        return model, proxy

    def _sources(self, proxy: LogFilterProxy) -> list[str]:
        return [
            proxy.data(proxy.index(r, 0), Qt.ItemDataRole.DisplayRole)
            for r in range(proxy.rowCount())
        ]

    def test_empty_selection_shows_all(self, qtbot):
        _, proxy = self._model_proxy([_rec(source="a"), _rec(source="b")])
        assert proxy.rowCount() == 2

    def test_source_only(self, qtbot):
        _, proxy = self._model_proxy([_rec(source="a"), _rec(source="b"), _rec(source="a")])
        proxy.set_sources({"a"})
        assert self._sources(proxy) == ["a", "a"]

    def test_level_only(self, qtbot):
        _, proxy = self._model_proxy(
            [_rec(level=logging.INFO), _rec(level=logging.ERROR), _rec(level=logging.ERROR)]
        )
        proxy.set_levels({logging.ERROR})
        assert proxy.rowCount() == 2

    def test_search_only(self, qtbot):
        _, proxy = self._model_proxy([_rec(message="Hello World"), _rec(message="bye")])
        proxy.set_search("hello")  # case-insensitive
        assert proxy.rowCount() == 1

    def test_combined(self, qtbot):
        _, proxy = self._model_proxy(
            [
                _rec(source="a", level=logging.ERROR, message="fail here"),
                _rec(source="a", level=logging.INFO, message="fail here"),
                _rec(source="b", level=logging.ERROR, message="fail here"),
                _rec(source="a", level=logging.ERROR, message="ok"),
            ]
        )
        proxy.set_sources({"a"})
        proxy.set_levels({logging.ERROR})
        proxy.set_search("fail")
        assert proxy.rowCount() == 1


class TestDynamicSources:
    def test_new_source_adds_one_checked_option(self, qtbot):
        dock = LogDock()
        qtbot.addWidget(dock)
        dock.append_record(_rec(source="picoscope"))

        assert dock._source_filter.selected() == {"picoscope"}

    def test_repeat_source_adds_no_option(self, qtbot):
        dock = LogDock()
        qtbot.addWidget(dock)
        dock.append_record(_rec(source="picoscope"))
        dock.append_record(_rec(source="picoscope"))
        assert len(dock._source_filter._actions) == 1

    def test_unchecking_source_filters_it_out(self, qtbot):
        dock = LogDock()
        qtbot.addWidget(dock)
        dock.append_record(_rec(source="picoscope", message="keep"))
        dock.append_record(_rec(source="mccdaq", message="drop"))

        dock._source_filter.set_checked("mccdaq", False)
        assert dock._proxy.rowCount() == 1


class TestLevelFilter:
    def test_debug_hidden_by_default(self, qtbot):
        dock = LogDock()
        qtbot.addWidget(dock)
        dock.append_record(_rec(level=logging.DEBUG, message="dbg"))
        dock.append_record(_rec(level=logging.INFO, message="info"))
        # DEBUG is unchecked out of the box, so only the INFO row shows.
        assert dock._proxy.rowCount() == 1
        assert logging.DEBUG not in dock._level_filter.selected()

    def test_unchecking_level_filters_it_out(self, qtbot):
        dock = LogDock()
        qtbot.addWidget(dock)
        dock.append_record(_rec(level=logging.INFO, message="info"))
        dock.append_record(_rec(level=logging.ERROR, message="err"))

        dock._level_filter.set_checked(logging.INFO, False)
        assert dock._proxy.rowCount() == 1


class TestMultiSelectButton:
    def test_text_tracks_selection(self, qtbot):
        from h2pcontrol.controller.ui.log_dock import MultiSelectButton

        button: MultiSelectButton[str] = MultiSelectButton()
        qtbot.addWidget(button)
        assert button.text() == "All"

        button.add_option("a", "Alpha")
        button.add_option("b", "Bravo")
        button.add_option("c", "Charlie")
        assert button.text() == "All"

        button.set_checked("c", False)
        assert button.text() == "Alpha, Bravo"  # ≤2 → names

        button.set_checked("b", False)
        assert button.text() == "Alpha"

        button.set_checked("a", False)
        assert button.text() == "None"

        button.set_checked("a", True)
        button.set_checked("b", True)
        button.set_checked("c", True)
        assert button.text() == "All"


class TestFollowTailHelper:
    def test_at_bottom(self):
        assert is_at_bottom(100, 100)
        assert is_at_bottom(99, 100)  # within one pixel
        assert not is_at_bottom(50, 100)

    def test_zero_range_is_at_bottom(self):
        assert is_at_bottom(0, 0)
