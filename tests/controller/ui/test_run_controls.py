"""Tests for RunControls: adaptive repeats/sweeps, ∞, load gating, schedule signal."""

from __future__ import annotations

import pytest

from h2pcontrol.controller.ui.run_controls import RunControls


@pytest.fixture
def controls(qtbot) -> RunControls:
    c = RunControls()
    qtbot.addWidget(c)
    return c


class TestNoScanMode:
    def test_default_is_single_point(self, controls: RunControls):
        # Not scanning: repeats-per-point hidden, count labelled "Repeats".
        # isHidden() (not isVisible()) reflects the explicit hide state when the
        # top-level widget isn't shown, as under offscreen Qt.
        assert controls._repeats.isHidden()
        assert controls._count_label.text() == "Repeats:"

    def test_count_drives_scan_repeats(self, controls: RunControls):
        controls._count.setValue(100)
        repeats_per_point, scan_repeats = controls.run_counts()
        # Single fixed point: 1 shot per pass, `count` passes.
        assert repeats_per_point == 1
        assert scan_repeats == 100

    def test_infinite_runs_forever(self, controls: RunControls):
        controls._inf_check.setChecked(True)
        repeats_per_point, scan_repeats = controls.run_counts()
        assert repeats_per_point == 1
        assert scan_repeats is None
        assert not controls._count.isEnabled()


class TestScanMode:
    def test_shows_per_point_and_sweeps(self, controls: RunControls):
        controls.set_scanning(True)
        assert not controls._repeats.isHidden()
        # The count knob keeps its "Repeats:" label in both modes.
        assert controls._count_label.text() == "Repeats:"

    def test_counts_are_orthogonal(self, controls: RunControls):
        controls.set_scanning(True)
        controls._repeats.setValue(10)
        controls._count.setValue(4)
        repeats_per_point, scan_repeats = controls.run_counts()
        assert repeats_per_point == 10  # averaging per point
        assert scan_repeats == 4  # sweeps

    def test_infinite_sweeps(self, controls: RunControls):
        controls.set_scanning(True)
        controls._repeats.setValue(5)
        controls._inf_check.setChecked(True)
        repeats_per_point, scan_repeats = controls.run_counts()
        assert repeats_per_point == 5
        assert scan_repeats is None


class TestGatingAndSignals:
    def test_schedule_disabled_until_loaded(self, controls: RunControls):
        assert not controls._schedule_btn.isEnabled()
        controls.set_loaded(True)
        assert controls._schedule_btn.isEnabled()
        controls.set_loaded(False)
        assert not controls._schedule_btn.isEnabled()

    def test_schedule_requested_emitted(self, qtbot, controls: RunControls):
        controls.set_loaded(True)
        with qtbot.waitSignal(controls.schedule_requested, timeout=1000):
            controls._schedule_btn.click()
