from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .experiment_panel import ExperimentPanel
from .run_controls import RunControls


class ExperimentView(QWidget):
    """Central widget: Experiment name header, parameter panel, and run controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel("Experiment")
        self._header.setStyleSheet("font-weight: bold; padding: 4px 6px;")
        layout.addWidget(self._header)

        self.panel = ExperimentPanel()
        layout.addWidget(self.panel, stretch=1)

        self.controls = RunControls()
        layout.addWidget(self.controls)

    def set_experiment_name(self, name: str | None) -> None:
        self._header.setText(name or "Experiment")
