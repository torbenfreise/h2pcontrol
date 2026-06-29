from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..framework.experiment import Experiment
from ..framework.parameters import ParamSpec


class _ParamRow(QWidget):
    """Widget for displaying a single parameter."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(parent)
        self._name = name
        self._spec = spec

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._single = QLineEdit(str(spec.default))
        if spec.description:
            self._single.setToolTip(spec.description)
        self._single.textChanged.connect(self._on_value_changed)
        layout.addWidget(self._single, stretch=2)

        if spec.unit:
            lbl = QLabel(spec.unit)
            lbl.setStyleSheet("color: gray;")
            layout.addWidget(lbl)

    def _on_value_changed(self, text: str) -> None:
        """Validate the users input."""
        try:
            value = self._spec.dtype(text.strip()) if self._spec.dtype is not None else text.strip()
            self._spec.validate(value)
            self._single.setStyleSheet("")
            self._single.setToolTip(self._spec.description or "")
        except (ValueError, TypeError) as exc:
            self._single.setStyleSheet("border: 1px solid red;")
            self._single.setToolTip(str(exc))


class ExperimentPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(4, 4, 4, 4)

        self._form = QFormLayout()
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        outer.addLayout(self._form)
        outer.addStretch()

        self.setWidget(container)

        self._rows: dict[str, _ParamRow] = {}
        self._cls: type[Experiment] | None = None

    def load_experiment(self, cls: type[Experiment]) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._rows.clear()
        self._cls = cls

        for name, spec in cls._parameters.items():
            row = _ParamRow(name, spec)
            self._form.addRow(name, row)
            self._rows[name] = row
