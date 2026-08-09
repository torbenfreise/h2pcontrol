"""Per-run HDF5 persistence.

Layout: one file per run

    <results_root>/<experiment_name>_0001.h5
        /  (root attrs)              — run metadata: experiment, run_number and
                                       started_at, plus every key passed to
                                       create(attrs=…) — the metadata from
                                       run_metadata() (h2pcontrol_version,
                                       python_version, experiment_source) and run_id
        /data                        — Table of scalar rows. One row per shot in
                                       the common case; a shot returning a
                                       multi-row frame (e.g. one row per hardware
                                       trigger) appends all rows, sharing shot_idx.
                                       Column attrs carry each result/param's
                                       declared unit and description
        /traces/shot_00000/<column>  — array dataset per trace / image, always
                                       stacked to shape (n_rows, …). Axis 0 is
                                       unconditionally the row axis, so a 1-row
                                       shot storing a (4, 250) multichannel trace
                                       is (1, 4, 250) and is not confusable with a
                                       4-row shot of (250,) traces

The table description is built from the experiment's declared result and
parameter specs (their dtypes, units and descriptions.
The file is kept open during a run and flushed after
every shot.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd
import tables

from ..framework.parameters import ParamSpec
from ..framework.results import ResultSpec
from .run_metadata import run_metadata
from .spec import RunRequest

_UNSAFE = re.compile(r'[\\/:*?"<>|]')

# Fixed width for declared string columns; strings are stored as bytes.
_STRING_ITEMSIZE = 256


def _sanitize(name: str) -> str:
    return _UNSAFE.sub("_", name).strip() or "experiment"


def _next_run_number(root: Path, prefix: str) -> int:
    pattern = re.compile(re.escape(prefix) + r"_(\d+)\.h5$")
    existing = [
        int(m.group(1)) for p in root.iterdir() if p.is_file() and (m := pattern.match(p.name))
    ]
    return max(existing, default=0) + 1


@dataclass(frozen=True)
class _Column:
    """A declared column, flattened to its stored name (``result_x`` / ``params_y``)."""

    dtype: type
    unit: str | None
    description: str | None

    @property
    def is_array(self) -> bool:
        return self.dtype is np.ndarray

    def tables_col(self):
        dtype = np.dtype(f"S{_STRING_ITEMSIZE}") if self.dtype is str else np.dtype(self.dtype)
        return tables.Col.from_dtype(dtype)


@dataclass(frozen=True)
class RunSchema:
    """
    Result specs and parameter specs by name.
    Also includes the user-defined run-level metadata.
    """

    results: Mapping[str, ResultSpec]
    params: Mapping[str, ParamSpec]
    metadata: Mapping[str, str] = field(default_factory=dict)

    # A schema travels to the writer process, and the mappingproxy that
    # Experiment.results()/parameters() hand out has no pickle support.
    def __getstate__(self) -> dict[str, dict[str, Any]]:
        return {
            "results": dict(self.results),
            "params": dict(self.params),
            "metadata": dict(self.metadata),
        }

    def __setstate__(self, state: dict[str, dict[str, Any]]) -> None:
        for name, mapping in state.items():
            object.__setattr__(self, name, MappingProxyType(mapping))

    def columns(self) -> dict[str, _Column]:
        cols: dict[str, _Column] = {}
        for name, spec in self.results.items():
            cols[f"result_{name}"] = _Column(spec.dtype, spec.unit, spec.description)
        for name, spec in self.params.items():
            dtype = spec.dtype or type(spec.default)
            cols[f"params_{name}"] = _Column(dtype, spec.unit, spec.description)
        return cols


class RunStore:
    """Writes shots into a single HDF5 file for one run."""

    def __init__(
        self,
        h5: tables.File,
        run_number: int,
        experiment_name: str,
        path: Path,
        columns: dict[str, _Column],
    ):
        self._h5 = h5
        self.run_number = run_number
        self.experiment_name = experiment_name
        self.path = path
        self._columns = columns
        self._table: tables.Table | None = None
        self._traces: tables.Group | None = None
        # Per-shot write timing, written next to the result file on close.
        # Splits the total save cost from the HDF5 flush(es) so profiling can
        # tell disk-sync cost from the pytables append/build cost.
        self._shot_timings: list[dict[str, float]] = []

    @classmethod
    def create(
        cls,
        root: Path | str,
        experiment_name: str,
        *,
        schema: RunSchema,
        attrs: Mapping[str, str] | None = None,
    ) -> RunStore:
        """Create the next run file for *experiment_name* under *root*."""
        root = Path(root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        prefix = _sanitize(experiment_name)
        run_number = _next_run_number(root, prefix)
        path = root / f"{prefix}_{run_number:04d}.h5"

        h5 = tables.open_file(str(path), mode="w")
        h5.root._v_attrs.experiment = experiment_name
        h5.root._v_attrs.run_number = run_number
        h5.root._v_attrs.started_at = datetime.now().astimezone().isoformat()
        # Experiment-declared run metadata first, so the framework's own attrs
        # (experiment source, versions, run id) win on any key collision.
        for key, value in schema.metadata.items():
            setattr(h5.root._v_attrs, key, value)
        if attrs:
            for key, value in attrs.items():
                setattr(h5.root._v_attrs, key, value)

        return cls(h5, run_number, experiment_name, path, schema.columns())

    def _column(self, shot_idx: int, name: str) -> _Column:
        col = self._columns.get(name)
        if col is None:
            raise ValueError(
                f"Shot {shot_idx}: column {name!r} was not declared as a result or parameter"
            )
        return col

    def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None:
        """Append one shot's scalars to the data table; write arrays as datasets."""
        t_start = time.perf_counter_ns()
        flush_ns = 0
        flat = self._flatten(frame)
        n_rows = len(flat)

        # Partition declared columns into scalar (table) and array (/traces) by
        # their declared kind, independent of whether this shot produced rows.
        array_cols = [c for c in flat.columns if self._column(shot_idx, c).is_array]
        scalar_cols = [c for c in flat.columns if not self._column(shot_idx, c).is_array]

        arrays: dict[str, np.ndarray] = {}
        for col in array_cols:
            values = [np.asarray(v) for v in flat[col]]
            if not values:
                continue
            shapes = {v.shape for v in values}
            if len(shapes) > 1:
                raise ValueError(
                    f"Shot {shot_idx} column {col!r}: array shapes differ across "
                    f"rows ({sorted(shapes)}) — all rows in a shot must carry "
                    "equal-shape arrays"
                )
            arrays[col] = np.stack(values)

        # Append scalar row
        if self._table is None:
            desc = {"shot_idx": tables.Col.from_dtype(np.dtype(np.int64))}
            for col in scalar_cols:
                desc[col] = self._column(shot_idx, col).tables_col()
            table = self._h5.create_table("/", "data", desc)
            self._write_column_attrs(table, [*scalar_cols, *array_cols])
            self._table = table
        else:
            table = self._table
            expected = set(table.colnames) - {"shot_idx"}
            actual = set(scalar_cols)
            if actual != expected:
                added = sorted(actual - expected)
                missing = sorted(expected - actual)
                parts = []
                if added:
                    parts.append(f"added {added}")
                if missing:
                    parts.append(f"missing {missing}")
                raise ValueError(
                    f"Shot {shot_idx} column mismatch ({'; '.join(parts)}) "
                    "— all shots in a run must share the same columns"
                )

        row = table.row
        for i in range(n_rows):
            row["shot_idx"] = shot_idx
            for col in scalar_cols:
                row[col] = flat[col].iloc[i]
            row.append()
        t_flush = time.perf_counter_ns()
        table.flush()
        flush_ns += time.perf_counter_ns() - t_flush

        # Write trace / image arrays
        if arrays:
            if self._traces is None:
                self._traces = self._h5.create_group("/", "traces")
            shot_grp = self._h5.create_group(self._traces, f"shot_{shot_idx:05d}")
            for name, arr in arrays.items():
                node = self._h5.create_array(shot_grp, name, arr)
                self._set_meta(node._v_attrs, self._columns[name])

        t_flush = time.perf_counter_ns()
        self._h5.flush()
        flush_ns += time.perf_counter_ns() - t_flush

        self._shot_timings.append(
            {
                "shot_idx": float(shot_idx),
                "store_save_ms": (time.perf_counter_ns() - t_start) / 1e6,
                "store_flush_ms": flush_ns / 1e6,
            }
        )

    def _write_column_attrs(self, table: tables.Table, columns: list[str]) -> None:
        """Record each column's declared unit and description as table attributes."""
        for col in columns:
            self._set_meta(table.attrs, self._columns[col], prefix=f"{col}__")

    @staticmethod
    def _set_meta(attrs, column: _Column, prefix: str = "") -> None:
        if column.unit is not None:
            setattr(attrs, f"{prefix}unit", column.unit)
        if column.description is not None:
            setattr(attrs, f"{prefix}description", column.description)

    def close(self) -> None:
        """Close the HDF5 file and write the per-shot write-timing sidecar."""
        if self._h5.isopen:
            self._h5.close()
        if self._shot_timings:
            # Name avoids the '*_timings.csv' glob the analysis uses for per-shot
            # timing files — this is a separate, decoupled sidecar.
            stem = self.path.with_suffix("")
            pd.DataFrame(self._shot_timings).to_csv(f"{stem}_store.csv", index=False)

    @staticmethod
    def _flatten(frame: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame.copy()
        flat = frame.copy()
        flat.columns = ["_".join(str(p) for p in c).strip("_") for c in frame.columns]
        return flat


@dataclass
class RunStoreFactory:
    """Creates one :class:`RunStore` per run under *root*.

    A dataclass rather than a closure or a bound method because the writer
    process builds the sink itself, so the factory is pickled and sent there.
    ``root`` stays mutable so the GUI can retarget it from Settings without
    rebuilding the engine.
    """

    root: str

    def __call__(self, request: RunRequest, run_id: str, schema: RunSchema) -> RunStore:
        attrs = run_metadata(request) | {"run_id": run_id}
        return RunStore.create(self.root, request.experiment_name, schema=schema, attrs=attrs)
