from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class ParamSpec:
    default: Any
    low: Any = None
    high: Any = None
    unit: str | None = None
    description: str | None = None

    # Inferred from attribute declaration
    choices: tuple[Any, ...] | None = field(default=None, init=False)
    dtype: type | None = field(default=None, init=False)
    name: str | None = field(default=None, init=False)

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
) -> T:  # type lie: we actually return ParamSpec
    return ParamSpec(  # type: ignore[return-value]
        default=default,
        low=min,
        high=max,
        unit=unit,
        description=description,
    )
