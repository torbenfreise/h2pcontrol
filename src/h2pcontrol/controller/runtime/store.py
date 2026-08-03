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
                                       trigger) appends all rows, sharing shot_idx
        /traces/shot_00000/<column>  — array dataset per trace / image, always
                                       stacked to shape (n_rows, …). Axis 0 is
                                       unconditionally the row axis, so a 1-row
                                       shot storing a (4, 250) multichannel trace
                                       is (1, 4, 250) and is not confusable with a
                                       4-row shot of (250,) traces

The file is kept open during a run and flushed after every shot.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import tables

_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def _sanitize(name: str) -> str:
    return _UNSAFE.sub("_", name).strip() or "experiment"


def _is_array(value: Any) -> bool:
    return isinstance(value, np.ndarray)


def _next_run_number(root: Path, prefix: str) -> int:
    pattern = re.compile(re.escape(prefix) + r"_(\d+)\.h5$")
    existing = [
        int(m.group(1)) for p in root.iterdir() if p.is_file() and (m := pattern.match(p.name))
    ]
    return max(existing, default=0) + 1


class RunStore:
    """Writes shots into a single HDF5 file for one run."""

    def __init__(
        self,
        h5: tables.File,
        run_number: int,
        experiment_name: str,
        path: Path,
    ):
        self._h5 = h5
        self.run_number = run_number
        self.experiment_name = experiment_name
        self.path = path
        self._table: tables.Table | None = None
        self._traces: tables.Group | None = None

    @classmethod
    def create(
        cls,
        root: Path | str,
        experiment_name: str,
        *,
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
        if attrs:
            for key, value in attrs.items():
                setattr(h5.root._v_attrs, key, value)

        return cls(h5, run_number, experiment_name, path)

    def save_shot(self, shot_idx: int, frame: pd.DataFrame) -> None:
        """Append one shot's scalars to the data table; write arrays as datasets."""
        flat = self._flatten(frame)
        if len(flat) == 0:
            raise ValueError(f"Shot {shot_idx}: empty DataFrame")

        arrays: dict[str, np.ndarray] = {}
        for col in list(flat.columns):
            if _is_array(flat[col].iloc[0]):
                values = [np.asarray(v) for v in flat[col]]
                shapes = {v.shape for v in values}
                if len(shapes) > 1:
                    raise ValueError(
                        f"Shot {shot_idx} column {col!r}: array shapes differ across "
                        f"rows ({sorted(shapes)}) — all rows in a shot must carry "
                        "equal-shape arrays"
                    )
                arrays[col] = np.stack(values)
        if arrays:
            flat = flat.drop(columns=list(arrays))

        # Append scalar row
        if self._table is None:
            desc = {"shot_idx": tables.Col.from_dtype(np.dtype(np.int64))}
            for col in flat.columns:
                np_dtype = flat[col].to_numpy().dtype
                if np_dtype.kind in ("O", "U", "S"):
                    desc[col] = tables.Col.from_dtype(np.dtype("S256"))
                else:
                    desc[col] = tables.Col.from_dtype(np_dtype)
            table = self._h5.create_table("/", "data", desc)
            self._table = table
        else:
            table = self._table
            expected = set(table.colnames) - {"shot_idx"}
            actual = set(flat.columns)
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
        for i in range(len(flat)):
            row["shot_idx"] = shot_idx
            for col in flat.columns:
                row[col] = flat[col].iloc[i]
            row.append()
        table.flush()

        # Write trace / image arrays
        if arrays:
            if self._traces is None:
                self._traces = self._h5.create_group("/", "traces")
            shot_grp = self._h5.create_group(self._traces, f"shot_{shot_idx:05d}")
            for name, arr in arrays.items():
                self._h5.create_array(shot_grp, name, arr)

        self._h5.flush()

    def close(self) -> None:
        """Close the HDF5 file."""
        if self._h5.isopen:
            self._h5.close()

    @staticmethod
    def _flatten(frame: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame.copy()
        flat = frame.copy()
        flat.columns = ["_".join(str(p) for p in c).strip("_") for c in frame.columns]
        return flat
