from dataclasses import dataclass, field
from typing import Any, overload


@dataclass
class ParamSpec[T]:
    """Typed experiment parameter, implemented as a data descriptor.

    Class access (``MyExperiment.voltage``) returns the spec itself, enabling
    typed references (e.g. ``Axis(MyExperiment.voltage, ...)``).
    Instance access (``self.voltage``) returns the current value, falling back
    to ``default``.
    """

    default: T
    low: Any = None
    high: Any = None
    unit: str | None = None
    description: str | None = None
    choices: tuple[Any, ...] | None = None
    group: str | None = None

    # Inferred from attribute declaration
    dtype: type | None = field(default=None, init=False)
    name: str | None = field(default=None, init=False)

    # descriptor interface

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> "ParamSpec[T]": ...

    @overload
    def __get__(self, obj: object, objtype: type | None = None) -> T: ...

    def __get__(self, obj: object | None, objtype: type | None = None) -> "ParamSpec[T] | T":
        if obj is None:
            return self  # class-level access: the spec itself
        assert self.name is not None, "ParamSpec not attached to a class"
        return obj.__dict__.get(self.name, self.default)

    def __set__(self, obj: object, value: Any) -> None:
        assert self.name is not None, "ParamSpec not attached to a class"
        obj.__dict__[self.name] = self.validate(value)

    def validate(self, value: Any) -> Any:
        if self.dtype is not None:
            value = self._coerce(value, self.dtype)
        if self.choices is not None and value not in self.choices:
            raise ValueError(f"{self.name!r}: {value!r} not in {self.choices}")
        if self.low is not None and value < self.low:
            raise ValueError(f"{self.name!r}: {value} < min={self.low}")
        if self.high is not None and value > self.high:
            raise ValueError(f"{self.name!r}: {value} > max={self.high}")
        return value

    def _coerce(self, value: Any, t: type) -> Any:
        if t is bool:
            if not isinstance(value, bool):
                raise TypeError(f"expected bool, got {type(value).__name__}")
            return value
        if t in (int, float, str):
            return t(value)
        return value


def param[T](
    default: T,
    *,
    min: T | None = None,
    max: T | None = None,
    unit: str | None = None,
    description: str | None = None,
    choices: tuple[T, ...] | None = None,
    group: str | None = None,
) -> ParamSpec[T]:
    """Declare an experiment parameter.

    Examples::

        voltage = param(3.3, min=0.0, max=5.0, unit="V")
        mode = param("fast", choices=("fast", "slow"))

    The value type is inferred from ``default``.
    """
    return ParamSpec(
        default=default,
        low=min,
        high=max,
        unit=unit,
        description=description,
        choices=choices,
        group=group,
    )
