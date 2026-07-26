"""Tests for ShotDock and format_shot_line."""

from __future__ import annotations

import pandas as pd

from h2pcontrol.controller.ui.shot_dock import ShotDock, format_shot_line


def _frame() -> pd.DataFrame:
    return pd.concat(
        [pd.DataFrame({"peak": [1.23456]}), pd.DataFrame({"voltage": [3.3]})],
        axis=1,
        keys=["result", "params"],
    )


class TestFormatShotLine:
    def test_finite_total(self):
        line = format_shot_line(0, 10, _frame())
        assert line.startswith("Shot 1/10:")
        assert "[params] voltage=3.3" in line
        assert "[result] peak=1.235" in line

    def test_infinite_total(self):
        line = format_shot_line(4, None, _frame())
        assert line.startswith("Shot 5/∞:")

    def test_params_before_result(self):
        line = format_shot_line(0, 1, _frame())
        assert line.index("[params]") < line.index("[result]")


class TestShotDock:
    def test_append_and_clear(self, qtbot):
        dock = ShotDock()
        qtbot.addWidget(dock)

        dock.append("first")
        dock.append("second")
        assert "first" in dock._log.toPlainText()
        assert "second" in dock._log.toPlainText()

        dock.clear()
        assert dock._log.toPlainText() == ""
