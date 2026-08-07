# Profiling

This branch (`profiling`) adds per-shot timing instrumentation to h2pcontrol
and holds the raw measurement data for the thesis performance analysis. It is
frozen as evidence; the instrumentation is not meant to be merged into `main`.
It sits on top of the run-metadata and coordinate work, so the traces it
measures no longer carry a per-row time axis: what is timed is the transfer
and storage of the samples alone.

`scripts/analyze_timings.py` aggregates the raw CSVs into the summary tables
quoted in the thesis; the interpretation lives in the thesis, not here.

## What is measured

Three layers, all client-side on the controller machine:

1. **Per-shot phase spans** (`src/.../framework/timing.py`).
   `ShotTimings` records named wall-clock spans via `time.perf_counter_ns`
   (monotonic, ns resolution). The engine times its own phases (`shot`,
   `save`, `emit`, `framework_params`); the experiment marks phases inside
   `shot()` via `ctx.span(name)`. Because spans wrap `await`s, a span around
   a hardware-bound call measures the full time until the hardware responds.

2. **Per-RPC round-trips** (`src/.../runtime/rpc_instrumentation.py`).
   The engine wraps the SDK client so every gRPC call an experiment issues is
   timed from invocation to response and tagged with the current shot index
   (−1 for setup/teardown calls). Streaming reads are logged individually
   (`<method>/read`); for hardware-triggered captures those reads measure
   hardware wait, not gRPC overhead.

3. **Shot period.** Each timing row carries `t_mono` (`time.perf_counter`,
   taken at the end of the shot loop iteration); shot periods are diffs of
   consecutive `t_mono` values. A monotonic clock is used so periods are
   immune to NTP steps and wall-clock resolution limits.

## Files produced per run

Written next to the run's HDF5 result file when the run ends:

    <run>_timings.csv   one row per shot: shot_idx, t_mono, one column per phase (ms)
    <run>_rpc.csv       one row per gRPC call: shot_idx, method, duration_ms, ok
    <run>_meta.json     provenance: git commit + dirty flag, Python/OS versions,
                        hostname, absolute timestamp

## The profiled experiment

`examples/profiled_picoscope.py` is an instrumented copy of
`examples/example_picoscope.py` (identical logic). Phases:

| span                 | class    | meaning                                              |
|----------------------|----------|------------------------------------------------------|
| `capture_open`       | software | open the Capture stream call                         |
| `armed_wait`         | hardware | wait for scope arm confirmation                      |
| `pb_start`           | software | PulseBlaster Start RPC                               |
| `capture_wait_first` | hardware | trigger wait + acquisition (first rapid-block read)  |
| `capture_wait_rest`  | software | remaining reads — dominated by gRPC trace transfer   |
| `frame_build`        | software | numpy/pandas frame construction                      |
| `pb_stop`            | software | PulseBlaster Stop RPC                                |
| `framework_params`   | software | framework parameter-column attachment                |
| `save`               | software | HDF5 persistence (engine)                            |
| `emit`               | software | ShotCompleted event → UI/plot subscribers (engine)   |
| `shot`               | envelope | whole `shot()` call; overlaps the spans above        |

The hardware/software classification is the intended split for analysis:
"hardware" spans are bounded below by the physics of the trigger sequence,
everything else is framework/gRPC overhead. `shot` overlaps the other spans
and must be excluded from additive sums. The first shot of a run should be
dropped as warmup (first-RPC channel setup, allocator warmup).

## Measurement setup

- Two lab PCs on the same LAN: one runs the controller (GUI + engine), the
  other runs `h2pmanager`, `picoscope-server`, and `pulseblaster-server`.
- The PulseBlaster square wave output is wired into the Picoscope input as
  both signal and trigger source.
- Thesis runs: `captures_per_shot = 50`, `period_ns = 20_000_000` (20 ms,
  mimicking mains-synchronised triggering at 50 Hz).

## Known limitations

- Both machines run standard non-realtime OSes; occasional multi-ms
  scheduling outliers (e.g. in `pb_start`) are expected. Median/p95 are the
  robust statistics; means should be reported alongside.
- Python garbage collection is not disabled and can contribute to tails.
- All timings are client-observed: an RPC round-trip includes server-side
  processing and network transit; the split into "hardware" and "software"
  phases is by construction of the spans, not by independent measurement.
- Determinism here means statistical reproducibility across repeat runs, not
  bit-identical timings.
- Runs recorded before the time axis became a coordinate are not comparable
  with these: they transferred and saved a float64 time array alongside every
  trace, which inflates `capture_wait_rest` and `save`. Earlier runs also
  used a single `capture_wait` span instead of the `_first`/`_rest` split.

## Reproducing / evidence freeze

1. On both machines: check out this branch at the frozen tag, `uv sync`.
2. Confirm a clean tree (`git status --porcelain` empty) — the `_meta.json`
   sidecar records the commit and dirty flag of the controller machine.
3. Run the `Picoscope Rapid Block Profiled` experiment (≥ 3 repeat runs,
   ≥ 50 shots each) from the GUI.
4. Commit the resulting `*_timings.csv`, `*_rpc.csv`, and `*_meta.json`
   under `results/`.
