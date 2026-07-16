from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    def __init__(self, current_address: str, current_results_root: str = "results", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._address_edit = QLineEdit(current_address)
        self._address_edit.setPlaceholderText("host:port")
        form.addRow("Manager address:", self._address_edit)

        self._results_edit = QLineEdit(current_results_root)
        self._results_edit.setPlaceholderText("results")
        self._results_edit.setToolTip("Run files are written to <folder>/<experiment>_<run>.h5")
        browse = QPushButton("…")
        browse.setFixedWidth(28)
        browse.clicked.connect(self._on_browse)
        results_row = QHBoxLayout()
        results_row.setContentsMargins(0, 0, 0, 0)
        results_row.addWidget(self._results_edit)
        results_row.addWidget(browse)
        form.addRow("Results folder:", results_row)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose results folder", self._results_edit.text()
        )
        if path:
            self._results_edit.setText(path)

    def address(self) -> str:
        return self._address_edit.text().strip()

    def results_root(self) -> str:
        return self._results_edit.text().strip() or "results"
