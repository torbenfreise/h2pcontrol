import pandas as pd
from PySide6.QtWidgets import QDockWidget, QPlainTextEdit, QWidget


def format_shot_line(idx: int, total: int | None, frame: pd.DataFrame) -> str:
    """Format a single shot result line for the log."""
    shot_label = f"Shot {idx + 1}/{total}" if total is not None else f"Shot {idx + 1}/\u221e"

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
    return f"{shot_label}:  " + "   ".join(fmt_group(g) for g in ordered)


class ShotDock(QDockWidget):
    """Dock widget displaying per-shot output for the current run."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Shots", parent)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self.setWidget(self._log)

    def append(self, text: str) -> None:
        self._log.appendPlainText(text)

    def clear(self) -> None:
        self._log.clear()
