from collections import defaultdict

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
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


# ------------------------------------------------------------------
# Parameter rows
# ------------------------------------------------------------------


class _ParamRow(QWidget):
    """Base class for a single parameter row."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(parent)
        self._name = name
        self._spec = spec

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def is_scan_axis(self) -> bool:
        raise NotImplementedError

    def apply_to(self, experiment: Experiment) -> None:
        raise NotImplementedError

    def get_axis(self) -> Axis:
        raise NotImplementedError


class _ContinuousParamRow(_ParamRow):
    """Row for numeric parameters with scan type dropdown."""

    _MODES = ("Fixed", "Linear", "Centered", "List")

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(name, spec, parent)

        # Scan mode dropdown
        self._mode = QComboBox()
        self._mode.addItems(self._MODES)
        self._mode.setFixedWidth(90)
        self._mode.currentTextChanged.connect(self._on_mode_changed)
        self._layout.addWidget(self._mode)

        # Fixed value
        self._single = QLineEdit(str(spec.default))
        if spec.description:
            self._single.setToolTip(spec.description)
        self._single.textChanged.connect(self._on_value_changed)
        self._layout.addWidget(self._single, stretch=2)

        # Scan config defaults
        default = float(spec.default)
        start_default = float(spec.low) if spec.low is not None else default
        stop_default = (
            float(spec.high) if spec.high is not None else max(default * 10, default + 1.0)
        )
        suffix = f" {spec.unit}" if spec.unit else ""

        # Linear widgets
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

        self._linear_widgets = (
            _labeled("start", self._start),
            _labeled("stop", self._stop),
            _labeled("steps", self._steps),
        )

        # Centered widgets
        self._center = _FloatSpinBox()
        self._center.setDecimals(4)
        self._center.setRange(-1e9, 1e9)
        self._center.setValue(default)
        self._center.setSuffix(suffix)

        span_default = (stop_default - start_default) if spec.low is not None else 1.0
        self._span = _FloatSpinBox()
        self._span.setDecimals(4)
        self._span.setRange(0, 1e9)
        self._span.setValue(span_default)
        self._span.setSuffix(suffix)

        self._center_steps = QSpinBox()
        self._center_steps.setRange(2, 10_000)
        self._center_steps.setValue(10)

        self._centered_widgets = (
            _labeled("center", self._center),
            _labeled("span", self._span),
            _labeled("steps", self._center_steps),
        )

        # List widget
        self._list_edit = QLineEdit()
        self._list_edit.setPlaceholderText("1.0, 2.0, 3.0")

        # Add all scan widgets (hidden initially)
        for w in self._linear_widgets:
            self._layout.addWidget(w)
            w.setVisible(False)
        for w in self._centered_widgets:
            self._layout.addWidget(w)
            w.setVisible(False)
        self._layout.addWidget(self._list_edit, stretch=2)
        self._list_edit.setVisible(False)

        # Unit label (shown in Fixed mode)
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

    def _on_mode_changed(self, mode: str) -> None:
        is_fixed = mode == "Fixed"
        is_linear = mode == "Linear"
        is_centered = mode == "Centered"
        is_list = mode == "List"

        self._single.setVisible(is_fixed)
        if self._unit_label:
            self._unit_label.setVisible(is_fixed)
        for w in self._linear_widgets:
            w.setVisible(is_linear)
        for w in self._centered_widgets:
            w.setVisible(is_centered)
        self._list_edit.setVisible(is_list)

    def is_scan_axis(self) -> bool:
        return self._mode.currentText() != "Fixed"

    def apply_to(self, experiment: Experiment) -> None:
        text = self._single.text().strip()
        value: object = self._spec.dtype(text) if self._spec.dtype is not None else text
        setattr(experiment, self._name, value)

    def get_axis(self) -> Axis:
        mode = self._mode.currentText()
        if mode == "Linear":
            return Axis(
                param=self._spec,
                start=self._start.value(),
                stop=self._stop.value(),
                steps=self._steps.value(),
            )
        if mode == "Centered":
            return Axis.centered(
                param=self._spec,
                center=self._center.value(),
                span=self._span.value(),
                steps=self._center_steps.value(),
            )
        if mode == "List":
            values = [float(v.strip()) for v in self._list_edit.text().split(",") if v.strip()]
            return Axis.from_list(param=self._spec, values=values)
        raise RuntimeError(f"get_axis called in {mode} mode")


class _ChoicesParamRow(_ParamRow):
    """Row for choices parameters with a combobox and discrete scanning."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(name, spec, parent)
        assert spec.choices is not None

        self._check = QCheckBox()
        self._check.setFixedWidth(20)
        self._check.toggled.connect(self._on_toggled)
        self._layout.addWidget(self._check)

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

    def is_scan_axis(self) -> bool:
        return self._check.isChecked()

    def apply_to(self, experiment: Experiment) -> None:
        setattr(experiment, self._name, self._combo.currentData())

    def get_axis(self) -> Axis:
        return Axis(param=self._spec)


class _TextParamRow(_ParamRow):
    """Row for non-numeric parameters (e.g. strings) — no scanning."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(name, spec, parent)

        self._edit = QLineEdit(str(spec.default))
        if spec.description:
            self._edit.setToolTip(spec.description)
        self._layout.addWidget(self._edit, stretch=2)

    def is_scan_axis(self) -> bool:
        return False

    def apply_to(self, experiment: Experiment) -> None:
        setattr(experiment, self._name, self._edit.text().strip())

    def get_axis(self) -> Axis:
        raise RuntimeError("Text parameters cannot be scanned")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


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


def _is_numeric(spec: ParamSpec) -> bool:
    return spec.dtype in (int, float) or isinstance(spec.default, (int, float))


def _make_param_row(name: str, spec: ParamSpec, parent: QWidget | None = None) -> _ParamRow:
    if spec.choices is not None:
        return _ChoicesParamRow(name, spec, parent)
    if _is_numeric(spec):
        return _ContinuousParamRow(name, spec, parent)
    return _TextParamRow(name, spec, parent)


# ------------------------------------------------------------------
# Panel
# ------------------------------------------------------------------


class _ParamApplyError(Exception):
    """Raised when a parameter value cannot be applied."""


class ExperimentPanel(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(16)
        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self._rows: dict[str, _ParamRow] = {}
        self._zip_checks: dict[str, QCheckBox] = {}
        self._cls: type[Experiment] | None = None

    def load_experiment(self, cls: type[Experiment]) -> None:
        self.clear()
        self._rows.clear()
        self._zip_checks.clear()
        self._cls = cls

        # Partition params into groups and ungrouped
        groups: dict[str, list[tuple[str, ParamSpec]]] = defaultdict(list)
        ungrouped: list[tuple[str, ParamSpec]] = []
        for name, spec in cls._parameters.items():
            if spec.group is not None:
                groups[spec.group].append((name, spec))
            else:
                ungrouped.append((name, spec))

        # Grouped params: parent item per group, child items for params
        for group_name, params in sorted(groups.items()):
            group_item = QTreeWidgetItem(self, [group_name])
            group_item.setExpanded(True)
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            zip_check = QCheckBox("zip")
            zip_check.setToolTip("Scan grouped parameters in lockstep (zipped)")
            self.setItemWidget(group_item, 1, zip_check)
            self._zip_checks[group_name] = zip_check

            for name, spec in params:
                child = QTreeWidgetItem(group_item, [name])
                row = _make_param_row(name, spec)
                self.setItemWidget(child, 1, row)
                self._rows[name] = row

        # Ungrouped params: top-level items
        for name, spec in ungrouped:
            item = QTreeWidgetItem(self, [name])
            row = _make_param_row(name, spec)
            self.setItemWidget(item, 1, row)
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
        """Return a Scan if at least one axis is checked, else None.

        :raises _ParamApplyError: if a group is partially scanned.
        """
        if self._cls is None:
            return None

        # Determine which groups have zip enabled
        zipped_groups: set[str] = set()
        params = self._cls._parameters
        groups: dict[str, list[str]] = defaultdict(list)
        for name, spec in params.items():
            if spec.group is not None:
                groups[spec.group].append(name)

        for group_name, members in groups.items():
            if not self._zip_checks.get(group_name, QCheckBox()).isChecked():
                continue
            zipped_groups.add(group_name)
            # When zipped, all params in the group must be scanned
            scanning = [n for n in members if self._rows[n].is_scan_axis()]
            if scanning and len(scanning) != len(members):
                not_scanning = [n for n in members if n not in scanning]
                raise _ParamApplyError(
                    f"Group {group_name!r}: all parameters must be scanned together "
                    f"when zipped. Missing: {not_scanning}"
                )

        axes = [row.get_axis() for row in self._rows.values() if row.is_scan_axis()]
        if not axes:
            return None
        return Scan(*axes, zipped_groups=zipped_groups)
