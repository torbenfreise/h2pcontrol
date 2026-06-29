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
            self._spec.validate(text.strip())
            self._single.setStyleSheet("")
            self._single.setToolTip(self._spec.description or "")
        except (ValueError, TypeError) as exc:
            self._single.setStyleSheet("border: 1px solid red;")
            self._single.setToolTip(str(exc))


class _ParamApplyError(Exception):
    """Raised when a parameter value cannot be applied."""


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

    def initialise_experiment(self) -> Experiment:
        """Instantiate the loaded experiment class with current parameter values.

        :raises _ParamApplyError: if a parameter is invalid.
        :raises RuntimeError: if no experiment is loaded.
        """
        if self._cls is None:
            raise RuntimeError("No experiment loaded")
        exp = self._cls()
        for name, row in self._rows.items():
            try:
                setattr(exp, name, row._single.text().strip())
            except (ValueError, TypeError) as exc:
                raise _ParamApplyError(f"Parameter {name!r}: {exc}") from exc
        return exp
