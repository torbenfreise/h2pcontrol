# h2pcontrol

[![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/torbenfreise/h2pcontrol/python-coverage-comment-action-data/endpoint.json)](https://github.com/torbenfreise/h2pcontrol/actions/workflows/test.yml)

Experiment control GUI and framework for the h2pcontrol ecosystem. Works together
with the [h2pmanager](https://github.com/torbenfreise/h2pcontrol-manager) registry,
the [h2pcontrol-sdk](https://github.com/torbenfreise/h2pcontrol-sdk) client/server SDK,
and device service implementations (MCC DAQ, Picoscope, PulseBlaster, etc.).

> **Note — `profiling` branch:** this branch carries per-shot timing
> instrumentation and the measurement data used for the performance analysis
> in the thesis. It is frozen as evidence and not meant to be merged.
> See [PROFILING.md](PROFILING.md) for methodology and how to reproduce.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- A running `h2pmanager` instance for device communication

## Quickstart

```bash
uv sync          # install dependencies
uv run h2pcontrol  # launch the GUI
```

The `examples/` directory contains demonstration experiments that can be opened
via File -> Open in the GUI.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, linting, and testing instructions.
