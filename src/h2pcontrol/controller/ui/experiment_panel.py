from collections import defaultdict

from PySide6.QtCore import QLocale, Qt, Signal
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
from ..framework.parameters import ParameterError, ParamSpec
from ..runtime.spec import AxisSpec, CenteredAxis, ChoicesAxis, LinearAxis, ListAxis, ScanSpec


class _FloatSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that uses a period decimal separator and strips trailing zeros."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(QLocale.c())

    def textFromValue(self, value: float) -> str:
        return f"{value:g}"


class _ParamRow(QWidget):
    """Base class for a single parameter row."""

    # Signal when this rows scan status may have changed
    scan_toggled = Signal()

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(parent)
        self._name = name
        self._spec = spec

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def is_scan_axis(self) -> bool:
        raise NotImplementedError

    def value(self) -> object:
        """Return the current fixed value for this parameter."""
        raise NotImplementedError

    def get_axis_spec(self) -> AxisSpec:
        """Return an AxisSpec for this parameter (when scanned)."""
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
        self._single.textChanged.connect(self._refresh_validation)
        self._layout.addWidget(self._single, stretch=2)

        # Scan config defaults
        default = float(spec.default)
        start_default = float(spec.low) if spec.low is not None else default
        stop_default = (
            float(spec.high) if spec.high is not None else max(default * 10, default + 1.0)
        )
        suffix = f" {spec.unit}" if spec.unit else ""

        # Clamp scan spin boxes to the parameter bounds
        lo = float(spec.low) if spec.low is not None else -1e9
        hi = float(spec.high) if spec.high is not None else 1e9

        # Linear widgets
        self._start = _FloatSpinBox()
        self._start.setDecimals(4)
        self._start.setRange(lo, hi)
        self._start.setValue(start_default)
        self._start.setSuffix(suffix)

        self._stop = _FloatSpinBox()
        self._stop.setDecimals(4)
        self._stop.setRange(lo, hi)
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

        if spec.low is not None and spec.high is not None:
            center_default = (lo + hi) / 2
            span_default = hi - lo
            span_max = hi - lo
        else:
            center_default = default
            span_default = (stop_default - start_default) if spec.low is not None else 1.0
            span_max = 1e9

        self._center = _FloatSpinBox()
        self._center.setDecimals(4)
        self._center.setRange(lo, hi)
        self._center.setValue(center_default)
        self._center.setSuffix(suffix)

        self._span = _FloatSpinBox()
        self._span.setDecimals(4)
        self._span.setRange(0, span_max)
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
        self._list_edit.textChanged.connect(self._refresh_validation)

        # Live validation
        for _sb in (self._start, self._stop, self._center, self._span):
            _sb.valueChanged.connect(self._refresh_validation)

        # Add all scan widgets (hidden initially)
        for w in self._linear_widgets:
            self._layout.addWidget(w)
            w.setVisible(False)
        for w in self._centered_widgets:
            self._layout.addWidget(w)
            w.setVisible(False)
        self._layout.addWidget(self._list_edit, stretch=2)
        self._list_edit.setVisible(False)

        # Unit label
        self._unit_label: QLabel | None = None
        if spec.unit:
            lbl = QLabel(spec.unit)
            lbl.setStyleSheet("color: gray;")
            self._layout.addWidget(lbl)
            self._unit_label = lbl

    def _refresh_validation(self, *_: object) -> None:
        """Re-validate the active mode's input and flag the relevant field."""
        mode = self._mode.currentText()
        field = {
            "Fixed": self._single,
            "Linear": self._stop,
            "Centered": self._span,
            "List": self._list_edit,
        }[mode]
        _mark(field, self._spec.description, self._current_error(mode))

    def _current_error(self, mode: str) -> Exception | None:
        """Return the validation error for the current inputs, or None if valid.

        Scan modes reuse the schedule-time path (get_axis_spec → resolve →
        validate_values) so live feedback matches exactly what Schedule reports.
        """
        try:
            if mode == "Fixed":
                self._spec.validate(self._single.text().strip())
            else:
                self.get_axis_spec().resolve(self._spec).validate_values()
        except (ValueError, TypeError) as exc:
            return exc
        return None

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
        self.scan_toggled.emit()
        self._refresh_validation()

    def is_scan_axis(self) -> bool:
        return self._mode.currentText() != "Fixed"

    def value(self) -> object:
        """Coerce and validate the fixed value, raising ParameterError if invalid."""
        return self._spec.validate(self._single.text().strip())

    def get_axis_spec(self) -> AxisSpec:
        mode = self._mode.currentText()
        if mode == "Linear":
            return LinearAxis(
                param=self._name,
                start=self._start.value(),
                stop=self._stop.value(),
                steps=self._steps.value(),
            )
        if mode == "Centered":
            return CenteredAxis(
                param=self._name,
                center=self._center.value(),
                span=self._span.value(),
                steps=self._center_steps.value(),
            )
        if mode == "List":
            try:
                values = tuple(
                    float(v.strip()) for v in self._list_edit.text().split(",") if v.strip()
                )
            except ValueError as exc:
                raise ParameterError(f"{self._name!r}: invalid list value ({exc})") from exc
            return ListAxis(param=self._name, values=values)
        raise RuntimeError(f"get_axis_spec called in {mode} mode")


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
        self.scan_toggled.emit()

    def is_scan_axis(self) -> bool:
        return self._check.isChecked()

    def value(self) -> object:
        return self._spec.validate(self._combo.currentData())

    def get_axis_spec(self) -> AxisSpec:
        return ChoicesAxis(param=self._name)


class _TextParamRow(_ParamRow):
    """Row for non-numeric parameters (e.g. strings) — no scanning."""

    def __init__(self, name: str, spec: ParamSpec, parent=None):
        super().__init__(name, spec, parent)

        self._edit = QLineEdit(str(spec.default))
        if spec.description:
            self._edit.setToolTip(spec.description)
        self._edit.textChanged.connect(self._on_text_changed)
        self._layout.addWidget(self._edit, stretch=2)

    def _on_text_changed(self, text: str) -> None:
        try:
            self._spec.validate(text.strip())
            err: Exception | None = None
        except (ValueError, TypeError) as exc:
            err = exc
        _mark(self._edit, self._spec.description, err)

    def is_scan_axis(self) -> bool:
        return False

    def value(self) -> object:
        return self._spec.validate(self._edit.text().strip())

    def get_axis_spec(self) -> AxisSpec:
        raise RuntimeError("Text parameters cannot be scanned")


def _mark(widget: QWidget, description: str | None, err: Exception | None) -> None:
    """Set or clear error highlighting."""
    if err is None:
        widget.setStyleSheet("")
        widget.setToolTip(description or "")
    else:
        widget.setStyleSheet("border: 1px solid red;")
        widget.setToolTip(str(err))


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


class ExperimentPanel(QTreeWidget):
    # Signal when the set of scanned parameters may have changed
    scan_changed = Signal()

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
        for name, spec in cls.parameters().items():
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
            zip_check.setToolTip("Scan grouped parameters in lockstep")
            self.setItemWidget(group_item, 1, zip_check)
            self._zip_checks[group_name] = zip_check

            for name, spec in params:
                child = QTreeWidgetItem(group_item, [name])
                row = _make_param_row(name, spec)
                row.scan_toggled.connect(self.scan_changed)
                self.setItemWidget(child, 1, row)
                self._rows[name] = row

        # Ungrouped params
        for name, spec in ungrouped:
            item = QTreeWidgetItem(self, [name])
            row = _make_param_row(name, spec)
            row.scan_toggled.connect(self.scan_changed)
            self.setItemWidget(item, 1, row)
            self._rows[name] = row

        self.scan_changed.emit()

    def has_scan_axis(self) -> bool:
        """True if at least one parameter row is currently set to scan."""
        return any(row.is_scan_axis() for row in self._rows.values())

    def current_values(self) -> dict[str, object]:
        """Return validated values for all non-scanned parameters.

        :raises ParameterError: if a parameter value is invalid.
        :raises RuntimeError: if no experiment is loaded.
        """
        if self._cls is None:
            raise RuntimeError("No experiment loaded")
        values: dict[str, object] = {}
        for name, row in self._rows.items():
            if row.is_scan_axis():
                continue
            values[name] = row.value()
        return values

    def current_scan_spec(self) -> ScanSpec | None:
        """Return a ScanSpec if at least one axis is checked, else None.

        :raises ParameterError: if a group is partially scanned.
        """
        if self._cls is None:
            return None

        # Determine which groups have zip enabled
        zipped_groups: set[str] = set()
        params = self._cls.parameters()
        groups: dict[str, list[str]] = defaultdict(list)
        for name, spec in params.items():
            if spec.group is not None:
                groups[spec.group].append(name)

        for group_name, members in groups.items():
            if not self._zip_checks[group_name].isChecked():
                continue
            zipped_groups.add(group_name)
            # When zipped, all params in the group must be scanned
            scanning = [n for n in members if self._rows[n].is_scan_axis()]
            if scanning and len(scanning) != len(members):
                not_scanning = [n for n in members if n not in scanning]
                raise ParameterError(
                    f"Group {group_name!r}: all parameters must be scanned together "
                    f"when zipped. Missing: {not_scanning}"
                )

        axes = tuple(row.get_axis_spec() for row in self._rows.values() if row.is_scan_axis())
        if not axes:
            return None
        scan_spec = ScanSpec(axes=axes, zipped_groups=frozenset(zipped_groups))
        # resolve against loaded class to validate errors
        scan_spec.to_scan(self._cls)
        return scan_spec
