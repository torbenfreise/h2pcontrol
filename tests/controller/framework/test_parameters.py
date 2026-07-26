from typing import Any

import pytest

from h2pcontrol.controller.framework.parameters import ParameterError, ParamSpec, param


def _spec(
    default: Any,
    *,
    dtype: type | None = None,
    choices: tuple | None = None,
    low: Any = None,
    high: Any = None,
) -> ParamSpec:
    """Build a ParamSpec with non-init fields set (the experiment class normally does this)."""
    s = ParamSpec(default=default, low=low, high=high)
    s.dtype = dtype
    s.choices = choices
    return s


# ---------------------------------------------------------------------------
# param() factory
# ---------------------------------------------------------------------------


def test_param_returns_paramspec_with_defaults():
    p: Any = param(42, min=0, max=10, unit="V", description="supply voltage")
    assert isinstance(p, ParamSpec)
    assert p.default == 42
    assert p.low == 0
    assert p.high == 10
    assert p.unit == "V"
    assert p.description == "supply voltage"


def test_param_choices_kwarg():
    p = param("fast", choices=("fast", "slow"))
    assert p.choices == ("fast", "slow")
    with pytest.raises(ValueError, match="not in"):
        p.validate("medium")


# ---------------------------------------------------------------------------
# validate type coercion
# ---------------------------------------------------------------------------


def test_coerce_float_from_int():
    result = _spec(0.0, dtype=float).validate(3)
    assert result == 3.0
    assert isinstance(result, float)


def test_coerce_int_from_float():
    result = _spec(0, dtype=int).validate(3.9)
    assert result == 3
    assert isinstance(result, int)


def test_bool_rejects_int():
    with pytest.raises(ParameterError, match="expected bool"):
        _spec(False, dtype=bool).validate(1)


def test_no_dtype_passes_value_through():
    assert ParamSpec(default=None).validate("anything") == "anything"


# ---------------------------------------------------------------------------
# validate choices
# ---------------------------------------------------------------------------


def test_choices_accepts_valid():
    assert _spec("a", choices=("a", "b", "c")).validate("b") == "b"


def test_choices_rejects_invalid():
    with pytest.raises(ValueError, match="not in"):
        _spec("a", choices=("a", "b")).validate("c")


# ---------------------------------------------------------------------------
# validate bounds
# ---------------------------------------------------------------------------


def test_bounds_accept_edges():
    spec = _spec(5, dtype=int, low=0, high=10)
    assert spec.validate(0) == 0
    assert spec.validate(10) == 10


def test_bounds_reject_out_of_range():
    spec = _spec(5, dtype=int, low=0, high=10)
    with pytest.raises(ValueError, match="< min"):
        spec.validate(-1)

    with pytest.raises(ValueError, match="> max"):
        spec.validate(11)
