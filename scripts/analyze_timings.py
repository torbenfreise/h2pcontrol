"""Aggregate per-shot timing CSVs written by the RunEngine.

Each run produces two files next to its HDF5 result file:

    <run>_timings.csv   one row per shot: t_wall + one column per phase (ms)
    <run>_rpc.csv       one row per gRPC call: method, duration_ms, shot_idx

This script combines one or more runs (repeats) and reports:

- per-phase statistics (mean/std/median/p95/max) across all shots
- shot period and achieved rate (Hz), per run and combined
- software overhead vs hardware-bound wait split, with a software-limited
  rate ceiling (what the duty cycle would be if hardware waits were zero)
- per-RPC-method statistics from the rpc logs

Usage:

    uv run python scripts/analyze_timings.py results/<run>_timings.csv [more...]
    uv run python scripts/analyze_timings.py --latest 3 results/
    ... [--warmup 1] [--hardware armed_wait,capture_wait] [--out summary.csv]

By default the first shot of every run is dropped as warmup (first-RPC channel
setup, allocator warmup); tune with --warmup.
"""

# ruff: noqa: T201  (CLI tool: printing the report is the point)
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Columns in *_timings.csv that are not phase durations.
META_COLS = ("shot_idx", "t_wall", "t_mono")

# Engine-level phases: 'shot' spans the whole experiment shot() and overlaps
# the experiment's own spans, so it is excluded from additive sums.
ENVELOPE_PHASES = ("shot",)

# capture_wait_rest (rapid block reads after the first) is dominated by trace
# transfer over gRPC, so it counts as software overhead, not hardware wait.
DEFAULT_HARDWARE = ("armed_wait", "capture_wait", "capture_wait_first")


def _find_latest(results_dir: Path, n: int) -> list[Path]:
    files = sorted(results_dir.glob("*_timings.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        sys.exit(f"no *_timings.csv found in {results_dir}")
    return files[:n]


def _load_runs(paths: list[Path], warmup: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (timings, rpc) frames with a 'run' column; warmup shots dropped."""
    timing_frames, rpc_frames = [], []
    for path in paths:
        run = path.name.removesuffix("_timings.csv")
        df = pd.read_csv(path)
        df = df[df["shot_idx"] >= warmup].copy()
        if df.empty:
            print(f"warning: {path.name}: no shots left after warmup, skipping")
            continue
        df["run"] = run
        # Period between consecutive shots, computed per run. Prefer the
        # monotonic timestamp (immune to NTP steps and wall-clock resolution);
        # t_wall is the fallback for logs written before t_mono existed.
        clock = "t_mono" if "t_mono" in df.columns else "t_wall"
        df["period"] = df[clock].diff() * 1000.0  # ms
        timing_frames.append(df)

        rpc_path = path.with_name(path.name.replace("_timings.csv", "_rpc.csv"))
        if rpc_path.exists():
            rdf = pd.read_csv(rpc_path)
            rdf = rdf[rdf["shot_idx"] >= warmup].copy()
            rdf["run"] = run
            rpc_frames.append(rdf)

    if not timing_frames:
        sys.exit("no usable shots")
    timings = pd.concat(timing_frames, ignore_index=True)
    rpc = pd.concat(rpc_frames, ignore_index=True) if rpc_frames else pd.DataFrame()
    return timings, rpc


def _stats(series: pd.Series) -> dict[str, float]:
    s = series.dropna()
    return {
        "mean": s.mean(),
        "std": s.std(),
        "median": s.median(),
        "p95": s.quantile(0.95),
        "max": s.max(),
        "n": len(s),
    }


def analyze(
    timings: pd.DataFrame, rpc: pd.DataFrame, hardware: tuple[str, ...]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    phase_cols = [c for c in timings.columns if c not in (*META_COLS, "run", "period")]

    phases = pd.DataFrame({c: _stats(timings[c]) for c in phase_cols}).T
    phases.index.name = "phase"

    hw_cols = [c for c in phase_cols if c in hardware]
    sw_cols = [c for c in phase_cols if c not in hardware and c not in ENVELOPE_PHASES]
    per_shot_hw = timings[hw_cols].sum(axis=1) if hw_cols else pd.Series(0.0, timings.index)
    per_shot_sw = timings[sw_cols].sum(axis=1) if sw_cols else pd.Series(0.0, timings.index)
    period = timings["period"]

    mean_period = period.mean()
    mean_hw = per_shot_hw.mean()
    mean_sw = per_shot_sw.mean()
    summary = pd.DataFrame(
        {
            "value": {
                "shots": float(len(timings)),
                "runs": float(timings["run"].nunique()),
                "mean_period_ms": mean_period,
                "achieved_hz": 1000.0 / mean_period if mean_period else float("nan"),
                "hardware_wait_ms": mean_hw,
                "software_overhead_ms": mean_sw,
                "unaccounted_ms": mean_period - mean_hw - mean_sw,
                "software_limited_hz": 1000.0 / mean_sw if mean_sw else float("nan"),
            }
        }
    )
    summary.index.name = "metric"

    per_run = (
        timings.groupby("run")
        .agg(
            shots=("shot_idx", "count"),
            mean_period_ms=("period", "mean"),
            std_period_ms=("period", "std"),
        )
        .assign(achieved_hz=lambda d: 1000.0 / d["mean_period_ms"])
    )

    if not rpc.empty:
        rpc_stats = pd.DataFrame({m: _stats(g["duration_ms"]) for m, g in rpc.groupby("method")}).T
        rpc_stats.index.name = "method"
        rpc_stats = rpc_stats.sort_values("mean", ascending=False)
    else:
        rpc_stats = pd.DataFrame()

    return phases, summary, per_run, rpc_stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", type=Path, help="*_timings.csv files, or a results dir")
    ap.add_argument("--latest", type=int, metavar="N", help="use the N newest runs in the dir")
    ap.add_argument("--warmup", type=int, default=1, help="shots to drop per run (default 1)")
    ap.add_argument(
        "--hardware",
        default=",".join(DEFAULT_HARDWARE),
        help="comma-separated phases counted as hardware-bound wait",
    )
    ap.add_argument("--out", type=Path, help="also write the combined summary as CSV")
    args = ap.parse_args()

    if args.latest is not None:
        if len(args.paths) != 1 or not args.paths[0].is_dir():
            sys.exit("--latest expects a single results directory")
        paths = _find_latest(args.paths[0], args.latest)
    else:
        paths = args.paths
        for p in paths:
            if not p.is_file():
                sys.exit(f"not a file: {p} (pass a results dir with --latest N)")

    hardware = tuple(s.strip() for s in args.hardware.split(",") if s.strip())
    timings, rpc = _load_runs(paths, args.warmup)
    phases, summary, per_run, rpc_stats = analyze(timings, rpc, hardware)

    fmt = {"float_format": lambda v: f"{v:.3f}"}
    print(f"\n=== runs ===\n{per_run.to_string(**fmt)}")
    print(f"\n=== per-shot phases (ms) — hardware-bound: {', '.join(hardware)} ===")
    print(phases.to_string(**fmt))
    print(f"\n=== duty cycle ===\n{summary.to_string(**fmt)}")
    if not rpc_stats.empty:
        print(f"\n=== gRPC calls (ms) ===\n{rpc_stats.to_string(**fmt)}")

    if args.out:
        combined = pd.concat(
            [
                summary.reset_index().assign(section="summary"),
                phases.reset_index().assign(section="phases"),
                per_run.reset_index().assign(section="runs"),
                rpc_stats.reset_index().assign(section="rpc"),
            ],
            ignore_index=True,
        )
        combined.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
