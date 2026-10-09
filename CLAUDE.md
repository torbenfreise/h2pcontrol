# h2pcontrol — agent context

Experiment control GUI + framework for the h2pcontrol ecosystem (bachelor thesis, VU Beyer Lab).
Sibling repos: ../h2pcontrol-manager (Go registry), ../h2pcontrol-sdk (client/server SDK,
git-pinned in pyproject), ../h2pcontrol-protos (Buf/BSR), device servers (mccdaq, picoscope,
pulseblaster). Plan of record: PHASE0.md here and ../../checkpoint_review.md (thesis folder).

## Commands
- uv sync --locked (deps) · uv run h2pcontrol (GUI, needs a running h2pmanager)
- uv run ruff check src/ tests/ examples/ · uv run ruff format src/ tests/ examples/
- uv run pyright src/ tests/ examples/
- uv run pytest        # QT_QPA_PLATFORM=offscreen when headless
- .claude/scripts/gate.sh — verification gate (ruff format + ruff check + pyright + pytest).
  Run after making changes; formats in place, then fails fast on the first failing step.

## Architecture rules (enforced direction: ui → runtime → framework)
- src/h2pcontrol/controller/framework/ — domain (Experiment, ParamSpec descriptors, Scan/Axis).
  stdlib + numpy/pandas only. No I/O, no grpc, no Qt.
- src/h2pcontrol/controller/runtime/ — application layer. asyncio-native. May import framework
  + h2pcontrol.sdk. Never Qt. (Known debt: the run loop currently lives in ui/main_window.py
  — moving it here is Phase 1; do not add logic to widgets.)
- src/h2pcontrol/controller/ui/ — Qt adapter only. Single qasync event loop; never block it
  (no sync file/network I/O in handlers).

## Conventions & gotchas
- Python >=3.12, ruff line-length 100, rules E,F,I,B,UP,SIM,RUF,T20 (T20: no print — use logging).
- Generated gRPC stubs come from the buf.build/gen/python index (see pyproject); the h2pcontrol.*
  namespace is shared across this repo, the sdk, and stub packages — never add __init__.py at
  the h2pcontrol/ namespace root.
- examples/ = demonstration experiments, not user experiments; browsed on GitHub, never
  bundled in the wheel. `h2pcontrol init` writes the only shipped starter, from a string
  template in controller/scaffold.py; the README deliberately carries no code example, so
  the template is the single copy. results/ = local data, never commit.
- HDF5: one file per run (RunStore); /data scalar table schema freezes on first shot.
