import pandas as pd
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class RunControls(QWidget):
    run_requested = Signal(int)
    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)

        self._shots_label = QLabel("Shots:")
        hl.addWidget(self._shots_label)
        self._shots = QSpinBox()
        self._shots.setRange(1, 100_000)
        self._shots.setValue(10)
        hl.addWidget(self._shots)

        self._run_btn = QPushButton("Run")
        self._run_btn.clicked.connect(self._on_run)
        hl.addWidget(self._run_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop_requested)
        hl.addWidget(self._stop_btn)

        hl.addStretch()
        layout.addWidget(row)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        layout.addWidget(self._log)

    def log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def _on_run(self) -> None:
        self._log.clear()
        self.run_requested.emit(self._shots.value())

    def set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)

    def on_shot_complete(self, idx: int, frame: pd.DataFrame) -> None:
        def fmt_group(group: str) -> str:
            sub = pd.DataFrame(frame[group])
            pairs = "  ".join(
                f"{col}={sub[col].iloc[0]:.4g}"
                if pd.api.types.is_numeric_dtype(sub[col])
                else f"{col}={sub[col].iloc[0]}"
                for col in sub.columns
            )
            return f"[{group}] {pairs}"

        all_groups = set(frame.columns.get_level_values(0).unique())
        ordered = [g for g in ("params", "result") if g in all_groups]
        self._log.appendPlainText(f"Shot {idx + 1}:  " + "   ".join(fmt_group(g) for g in ordered))
