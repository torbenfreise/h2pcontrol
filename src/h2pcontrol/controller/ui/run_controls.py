"""Run settings and control bar."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)


class RunControls(QWidget):
    schedule_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Repeats per scan point — only shown when a scan is configured
        self._repeats_label = QLabel("Repeats per point:")
        layout.addWidget(self._repeats_label)
        self._repeats = QSpinBox()
        self._repeats.setRange(1, 100_000)
        self._repeats.setValue(1)
        self._repeats.setToolTip("Shots taken at each scan point")
        layout.addWidget(self._repeats)

        # Total repeats of the experiment
        self._count_label = QLabel("Repeats:")
        layout.addWidget(self._count_label)
        self._count = QSpinBox()
        self._count.setRange(1, 100_000)
        self._count.setValue(1)
        self._count.setToolTip("Number of repeats (use ∞ to run until stopped)")
        layout.addWidget(self._count)

        self._inf_check = QCheckBox("∞")
        self._inf_check.setToolTip("Run until stopped")
        self._inf_check.toggled.connect(self._count.setDisabled)
        layout.addWidget(self._inf_check)

        self._schedule_btn = QPushButton("Schedule")
        self._schedule_btn.clicked.connect(self.schedule_requested)
        layout.addWidget(self._schedule_btn)

        layout.addStretch()

        self.set_scanning(False)
        self.set_loaded(False)

    def run_counts(self) -> tuple[int, int | None]:
        """Return (repeats_per_point, scan_repeats) for the current mode.

        ``scan_repeats`` is None when ∞ is checked (run until stopped).
        """
        count = None if self._inf_check.isChecked() else self._count.value()
        if self._scanning:
            return self._repeats.value(), count
        return 1, count

    def set_scanning(self, scanning: bool) -> None:
        """Switch between scan mode and fixed mode."""
        self._scanning = scanning
        self._repeats_label.setVisible(scanning)
        self._repeats.setVisible(scanning)

    def set_loaded(self, loaded: bool) -> None:
        """Enable scheduling once an experiment has been loaded."""
        self._schedule_btn.setEnabled(loaded)
        self._schedule_btn.setToolTip("" if loaded else "Open an experiment first")
