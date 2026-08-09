from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from typing import Any, dataclass_transform, get_type_hints

import numpy as np
import pandas as pd


class ResultError(ValueError):
    """A result is malformed."""


@dataclass(frozen=True)
class ResultSpec:
    """Internal description of one result column.

    Used by the store to build ``/data`` table description from declared dtypes.
    """

    dtype: type
    unit: str | None = None
    description: str | None = None
    name: str | None = None

    @property
    def is_array(self) -> bool:
        """Whether this result stores arrays (``/traces`` datasets) vs table scalars."""
        return self.dtype is np.ndarray


def result(*, unit: str | None = None, description: str | None = None) -> Any:
    """Declare a result field on a :class:`Results` record.

    Optionally specify the  ``unit`` and ``description`` (stored as HDF5 column attributes)
    """
    return field(metadata={"unit": unit, "description": description})


@dataclass_transform(field_specifiers=(result,))
class Results:
    """Base for an experiment's per-shot record.

    Subclasses are turned into dataclasses automatically, so their annotated
    fields are the recorded columns and construction is type-checked.
    """

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        dataclass(cls)

    @classmethod
    def specs(cls) -> dict[str, ResultSpec]:
        """The storage schema: one :class:`ResultSpec` per declared field.

        Dtypes are resolved from the annotations.
        """
        hints = get_type_hints(cls)
        return {
            f.name: ResultSpec(
                dtype=hints[f.name],
                unit=f.metadata.get("unit"),
                description=f.metadata.get("description"),
                name=f.name,
            )
            for f in fields(cls)  # type: ignore[arg-type]  # cls is a dataclass
        }

    @classmethod
    def to_frame(cls, rows: Sequence[Results]) -> pd.DataFrame:
        """Assemble the shot's rows into a DataFrame, one column per declared field."""
        names = [f.name for f in fields(cls)]  # type: ignore[arg-type]  # cls is a dataclass
        return pd.DataFrame({n: [getattr(r, n) for r in rows] for n in names})
