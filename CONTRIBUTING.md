# Developer Guide

## Setup

```bash
uv sync
```

## Format and linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.
The checks are run automatically on every pull request in the [GitHub Actions workflow](.github/workflows/lint.yml)
and are a pre-condition for merging.

To run the same checks locally:

```bash
uv run ruff format src/ tests/ examples/       # format in-place
uv run ruff check --fix src/ tests/ examples/  # lint and auto-fix
uv run pyright src/ tests/ examples/           # type-check
```

These checks also run automatically on every pull request and pushes to main via
the [github workflow](./.github/workflows/lint.yml)

## Testing

To run the tests use:

```bash
uv run pytest
```

The tests also run on every pull request and are a pre-condition for merging.

GUI tests require a display. In headless environments (CI), set `QT_QPA_PLATFORM=offscreen`.

## Proto dependencies

Generated code is pulled from the [Buf Schema Registry](https://buf.build/beyer-labs/h2pcontrol) via the
`buf.build/gen/python` index configured in `pyproject.toml`. To update to the latest proto versions (necessary
for running an experiment with new devices):

```bash
uv sync --upgrade
```