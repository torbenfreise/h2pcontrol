"""Tests for ScheduleDock: queue table, per-row menus, clear-completed."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QPlainTextEdit, QPushButton

from h2pcontrol.controller.runtime.engine import RunEngine
from h2pcontrol.controller.runtime.events import (
    EngineState,
    EntryState,
    QueueChanged,
    QueueEntry,
    RunId,
    ShotCompleted,
    StateChanged,
)
from h2pcontrol.controller.runtime.spec import LinearAxis, RunRequest, ScanSpec
from h2pcontrol.controller.ui.engine_bridge import EngineBridge
from h2pcontrol.controller.ui.schedule_dock import ScheduleDock, format_request

_GREY = (128, 128, 128)


class FakeEngine:
    def __init__(self) -> None:
        self.callbacks: list = []
        self.state = EngineState.IDLE
        self._entries: tuple[QueueEntry, ...] = ()
        self.cleared = 0
        self.cancelled: list[RunId] = []
        self.stops: list[bool] = []

    # engine surface used by the dock
    @property
    def queue(self) -> tuple[QueueEntry, ...]:
        return self._entries

    def clear_finished(self) -> None:
        self.cleared += 1

    def cancel(self, run_id: RunId) -> None:
        self.cancelled.append(run_id)

    def stop_current(self, *, hard: bool = False) -> None:
        self.stops.append(hard)

    # subscription surface used by the bridge
    def subscribe(self, cb) -> None:
        self.callbacks.append(cb)

    def unsubscribe(self, cb) -> None:
        self.callbacks.remove(cb)

    def emit(self, event) -> None:
        for cb in list(self.callbacks):
            cb(event)

    # test helper
    def set_queue(self, entries: tuple[QueueEntry, ...]) -> None:
        self._entries = entries
        self.emit(QueueChanged(entries=entries))


def _entry(name: str, state: EntryState, source: str = "") -> QueueEntry:
    req = RunRequest(
        experiment_path=Path(f"/{name}.py"),
        experiment_name=name,
        param_values={},
        source=source,
    )
    return QueueEntry(run_id=RunId(name), request=req, state=state)


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def dock(qtbot, fake_engine: FakeEngine) -> ScheduleDock:
    bridge = EngineBridge(cast("RunEngine", fake_engine))
    d = ScheduleDock(cast("RunEngine", fake_engine), bridge)
    qtbot.addWidget(d)
    return d


def _color(item) -> tuple[int, int, int]:
    return item.foreground().color().getRgb()[:3]


class TestQueueRendering:
    def test_three_mixed_entries_render_grey_terminals(self, dock, fake_engine):
        fake_engine.set_queue(
            (
                _entry("done", EntryState.COMPLETED),
                _entry("run", EntryState.RUNNING),
                _entry("wait", EntryState.QUEUED),
            )
        )
        table = dock._table
        assert table.rowCount() == 3
        assert table.item(0, 1).text() == "completed"
        assert table.item(1, 1).text() == "running"
        assert table.item(2, 1).text() == "pending"

        # Only the terminal row is greyed.
        assert _color(table.item(0, 0)) == _GREY
        assert _color(table.item(1, 0)) != _GREY
        assert _color(table.item(2, 0)) != _GREY

    def test_shot_completed_updates_only_progress(self, dock, fake_engine):
        fake_engine.set_queue((_entry("run", EntryState.RUNNING),))
        table = dock._table
        state_before = table.item(0, 1).text()

        fake_engine.emit(
            ShotCompleted(run_id=RunId("run"), shot_idx=0, total_shots=5, frame=None)  # type: ignore[arg-type]
        )
        assert table.item(0, 2).text() == "1/5"
        assert table.item(0, 1).text() == state_before  # state cell untouched

    def test_stopping_state_shown_on_running_row(self, dock, fake_engine):
        fake_engine.set_queue((_entry("run", EntryState.RUNNING),))
        fake_engine.state = EngineState.STOPPING
        # bridge re-emits → dock refreshes the running row's State cell
        fake_engine.emit(StateChanged(state=EngineState.STOPPING))
        assert dock._table.item(0, 1).text() == "stopping"


class TestContextMenu:
    def test_queued_row_offers_cancel(self, dock, fake_engine):
        entry = _entry("wait", EntryState.QUEUED)
        fake_engine.set_queue((entry,))
        menu = dock._menu_for(entry)
        assert [a.text() for a in menu.actions()] == ["Cancel"]
        assert menu.actions()[0].isEnabled()

        menu.actions()[0].trigger()
        assert fake_engine.cancelled == [entry.run_id]

    def test_running_row_offers_stop_actions(self, dock, fake_engine):
        entry = _entry("run", EntryState.RUNNING)
        fake_engine.set_queue((entry,))
        menu = dock._menu_for(entry)
        assert [a.text() for a in menu.actions()] == [
            "Stop after current shot",
            "Force terminate",
        ]

        menu.actions()[0].trigger()
        menu.actions()[1].trigger()
        assert fake_engine.stops == [False, True]

    def test_terminal_row_menu_disabled(self, dock, fake_engine):
        entry = _entry("done", EntryState.COMPLETED)
        fake_engine.set_queue((entry,))
        menu = dock._menu_for(entry)
        assert all(not a.isEnabled() for a in menu.actions())


class TestClearCompleted:
    def test_clear_button_calls_clear_finished(self, dock, fake_engine):
        dock._clear_btn.click()
        assert fake_engine.cleared == 1


class TestFormatRequest:
    def test_plain_request(self):
        req = RunRequest(
            experiment_path=Path("/exp.py"),
            experiment_name="Exp",
            param_values={"voltage": 3.3},
            repeats_per_point=5,
        )
        text = format_request(req)
        assert "Experiment: Exp" in text
        assert "voltage = 3.3" in text
        assert "Repeats per point: 5" in text
        assert "Scan repeats: 1" in text
        # The file path is no longer surfaced in the summary — the source is.
        assert "Path:" not in text

    def test_scan_request(self):
        scan = ScanSpec(axes=(LinearAxis(param="voltage", start=0.0, stop=5.0, steps=3),))
        req = RunRequest(
            experiment_path=Path("/exp.py"),
            experiment_name="Exp",
            param_values={},
            scan=scan,
            scan_repeats=None,
        )
        text = format_request(req)
        assert "Scan:" in text
        assert "voltage (linear)" in text
        assert "steps=3" in text
        assert "Scan repeats: ∞" in text


class TestDetailsDialog:
    _SRC = "class Rabi(Experiment):\n    freq = param(5.0)\n"

    def test_dialog_shows_source_snapshot(self, qtbot, dock, fake_engine):
        entry = _entry("run", EntryState.QUEUED, source=self._SRC)
        fake_engine.set_queue((entry,))

        dlg = dock._details_dialog(entry)
        qtbot.addWidget(dlg)

        view = dlg.findChild(QPlainTextEdit, "source_view")
        assert view is not None
        assert view.toPlainText() == self._SRC

    def test_copy_button_puts_source_on_clipboard(self, qtbot, dock, fake_engine):
        entry = _entry("run", EntryState.QUEUED, source=self._SRC)
        fake_engine.set_queue((entry,))

        dlg = dock._details_dialog(entry)
        qtbot.addWidget(dlg)

        copy_btn = dlg.findChild(QPushButton)
        assert copy_btn is not None
        copy_btn.click()
        assert QGuiApplication.clipboard().text() == self._SRC
