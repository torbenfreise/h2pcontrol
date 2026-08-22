# h2pcontrol

[![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/torbenfreise/h2pcontrol/python-coverage-comment-action-data/endpoint.json)](https://github.com/torbenfreise/h2pcontrol/actions/workflows/test.yml)

Experiment control GUI and framework for h2pcontrol.

## Requirements

- [uv](https://docs.astral.sh/uv/)

Using device servers within an experiment additionally needs a running
[h2pmanager](https://github.com/torbenfreise/h2pcontrol-manager) instance, 
with which the device servers themselves must register.
The manager is the registry h2pcontrol queries to find those
services; the GUI tries to connect to it at `localhost:50051` by default (configurable under *Settings*).
Any service defined in
[h2pcontrol-protos](https://github.com/torbenfreise/h2pcontrol-protos) can be used.
New services can be built by describing their interface in the proto
repository and implementing the service following the
[server template](https://github.com/torbenfreise/h2pcontrol-server-template).


## Setup

Scaffold an experiment project:
```bash
uvx --index https://buf.build/gen/python \
  --from git+https://github.com/torbenfreise/h2pcontrol \
  h2pcontrol init my-experiments
```

Then create the environment and launch the GUI:

```bash
cd my-experiments
uv sync
uv run h2pcontrol
```

`init` writes a `pyproject.toml` with the required dependencies, 
`experiments/` with a starter experiment to run straight away, and a gitignored
`results/` for measurement data.

## Upgrading

To upgrade to a new [h2pcontrol-protos](https://github.com/torbenfreise/h2pcontrol-protos) version
— for instance, after it received a new service interface — run the following command in your project:


```bash
uv sync --upgrade
```


## Running an experiment

An experiment is a single `.py` file. In the GUI choose *File → Open Experiment…* and
select it. The declared parameters appear as editable fields, one live plot panel is drawn
per declared view, and a scan can be set up over any numeric or choice parameter. Set
*Repeats* and press *Schedule* to run. Each run is written to its own HDF5 file under the
results directory (*Settings*).

## Writing an experiment

An experiment is a single class deriving from abstract base class `Experiment`.
The only requirement is a `shot()` method, which performs one experimental sequence
and returns the rows to record. 

Declared in the class body:

- **`name`** — the title shown in the GUI; defaults to the class name.
- **`param(...)`** — an input. It becomes an editable field and is recorded alongside
  every row. Numeric and choice parameters can also be swept by the scan editor.
- **`view(...)`** — a live plot panel. `ViewKind.SERIES` accumulates one point per push,
  `ViewKind.LINE` replaces the curve with the latest push.
- **`service_stub(...)`** — a device server, resolved by its name in the manager registry. 
 Connected before the run and available inside shot().
- **an inner `Results` subclass** — the columns of one recorded row, which determines the
  HDF5 schema.

Over a run h2pcontrol connects the stubs, calls `setup()` and `metadata()` once, then
`shot()` once per shot, and `teardown()` at the end. `shot()` receives a `Context`
carrying `shot_idx`, `run_id` and `total_shots`, and returns 
a sequence of `Results`, one row is written per item returned. `setup()` and `teardown()`
are intended to be used to configure and shutdown devices respectively, and 
the return value of `metadata()` is written as attributes to the HDF5 root.



## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, linting, and testing instructions.
