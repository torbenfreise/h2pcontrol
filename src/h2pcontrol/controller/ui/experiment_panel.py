from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..framework.experiment import Experiment
from ..framework.parameters import ParamSpec
from ..framework.scan import Axis, Scan


class _FloatSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that uses a period decimal separator and strips trailing zeros."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(QLocale.c())

    def textFromValue(self, value: float) -> str:
        return f"{value:g}"


class _ParamRow(QWidget):
    """Base class for a single parameter row with a scan checkbox."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(parent)
        self._name = name
        self._spec = spec

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._check = QCheckBox()
        self._check.setFixedWidth(20)
        self._check.toggled.connect(self._on_toggled)
        self._layout.addWidget(self._check)

    def _on_toggled(self, checked: bool) -> None:
        raise NotImplementedError

    def is_scan_axis(self) -> bool:
        return self._check.isChecked()

    def apply_to(self, experiment: Experiment) -> None:
        raise NotImplementedError

    def get_axis(self) -> Axis:
        raise NotImplementedError


class _ContinuousParamRow(_ParamRow):
    """Row for numeric parameters with start/stop/steps scanning."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(name, spec, parent)

        self._single = QLineEdit(str(spec.default))
        if spec.description:
            self._single.setToolTip(spec.description)
        self._single.textChanged.connect(self._on_value_changed)
        self._layout.addWidget(self._single, stretch=2)

        default = float(spec.default)
        start_default = float(spec.low) if spec.low is not None else default
        stop_default = (
            float(spec.high) if spec.high is not None else max(default * 10, default + 1.0)
        )

        suffix = f" {spec.unit}" if spec.unit else ""

        self._start = _FloatSpinBox()
        self._start.setDecimals(4)
        self._start.setRange(-1e9, 1e9)
        self._start.setValue(start_default)
        self._start.setSuffix(suffix)

        self._stop = _FloatSpinBox()
        self._stop.setDecimals(4)
        self._stop.setRange(-1e9, 1e9)
        self._stop.setValue(stop_default)
        self._stop.setSuffix(suffix)

        self._steps = QSpinBox()
        self._steps.setRange(2, 10_000)
        self._steps.setValue(10)

        def _labeled(label: str, widget: QWidget) -> QWidget:
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)

            ql = QLabel(label)
            ql.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(ql)
            hl.addWidget(widget)
            return w

        self._scan_widgets = (
            _labeled("start", self._start),
            _labeled("stop", self._stop),
            _labeled("steps", self._steps),
        )
        for w in self._scan_widgets:
            self._layout.addWidget(w)
            w.setVisible(False)

        self._unit_label: QLabel | None = None
        if spec.unit:
            lbl = QLabel(spec.unit)
            lbl.setStyleSheet("color: gray;")
            self._layout.addWidget(lbl)
            self._unit_label = lbl

    def _on_value_changed(self, text: str) -> None:
        try:
            value = self._spec.dtype(text.strip()) if self._spec.dtype is not None else text.strip()
            self._spec.validate(value)
            self._single.setStyleSheet("")
            self._single.setToolTip(self._spec.description or "")
        except (ValueError, TypeError) as exc:
            self._single.setStyleSheet("border: 1px solid red;")
            self._single.setToolTip(str(exc))

    def _on_toggled(self, checked: bool) -> None:
        self._single.setVisible(not checked)
        if self._unit_label:
            self._unit_label.setVisible(not checked)
        for w in self._scan_widgets:
            w.setVisible(checked)

    def apply_to(self, experiment: Experiment) -> None:
        text = self._single.text().strip()
        value: object = self._spec.dtype(text) if self._spec.dtype is not None else text
        setattr(experiment, self._name, value)

    def get_axis(self) -> Axis:
        return Axis(
            param=self._spec,
            start=self._start.value(),
            stop=self._stop.value(),
            steps=self._steps.value(),
        )


class _ChoicesParamRow(_ParamRow):
    """Row for choices parameters with a combobox and discrete scanning."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(name, spec, parent)
        assert spec.choices is not None

        self._combo = QComboBox()
        for choice in spec.choices:
            self._combo.addItem(str(choice), choice)
        idx = self._combo.findData(spec.default)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        if spec.description:
            self._combo.setToolTip(spec.description)
        self._layout.addWidget(self._combo, stretch=2)

        self._scan_label = QLabel(f"all: {', '.join(str(c) for c in spec.choices)}")
        self._scan_label.setStyleSheet("color: gray;")
        self._scan_label.setVisible(False)
        self._layout.addWidget(self._scan_label, stretch=2)

    def _on_toggled(self, checked: bool) -> None:
        self._combo.setVisible(not checked)
        self._scan_label.setVisible(checked)

    def apply_to(self, experiment: Experiment) -> None:
        setattr(experiment, self._name, self._combo.currentData())

    def get_axis(self) -> Axis:
        return Axis(param=self._spec)


def _make_param_row(name: str, spec: ParamSpec, parent: QWidget | None = None) -> _ParamRow:
    if spec.choices is not None:
        return _ChoicesParamRow(name, spec, parent)
    return _ContinuousParamRow(name, spec, parent)


class _ParamApplyError(Exception):
    """Raised when a parameter value cannot be applied."""


class ExperimentPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(4, 4, 4, 4)

        # parameter form
        self._form = QFormLayout()
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        outer.addLayout(self._form)
        outer.addStretch()

        # "scan" header
        self._scan_header = QLabel("scan")
        self._scan_header.setStyleSheet("color: gray; font-size: 10px;")
        self._scan_header.setFixedWidth(30)
        self._scan_header.setVisible(False)

        self.setWidget(container)

        self._rows: dict[str, _ParamRow] = {}
        self._cls: type[Experiment] | None = None

    def load_experiment(self, cls: type[Experiment]) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._rows.clear()
        self._cls = cls

        self._scan_header.setVisible(True)
        self._form.addRow("", self._scan_header)

        for name, spec in cls._parameters.items():
            row = _make_param_row(name, spec)
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
                row.apply_to(exp)
            except (ValueError, TypeError) as exc:
                raise _ParamApplyError(f"Parameter {name!r}: {exc}") from exc
        return exp

    def get_scan(self) -> Scan | None:
        """Return a Scan if at least one axis is checked, else None."""
        axes = [row.get_axis() for row in self._rows.values() if row.is_scan_axis()]
        return Scan(*axes) if axes else None
