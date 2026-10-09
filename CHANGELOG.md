# Changelog

All notable changes to the controller are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Documentation site at [h2pcontrol.torbenfreise.dev](https://h2pcontrol.torbenfreise.dev/),
  built with MkDocs Material and deployed from GitHub Actions.
- `h2pcontrol.controller.framework` re-exports the authoring API, so experiments import
  from one place instead of five submodules. The submodules remain importable.

### Changed

- The starter experiment written by `h2pcontrol init` now lives in a real module
  (`controller/_starter.py`) rather than a string literal, so it is linted, type-checked
  and included verbatim in the documentation.

### Fixed

- Typos in the starter experiment's docstring and comments.

## 0.1.1 — 2026-08-23

!!! note

    Version `0.1.1` was bumped in `pyproject.toml` but never tagged; `0.1.0` is the only
    tag in the repository.

### Added

- `h2pcontrol init` scaffolds a new experiment project — `pyproject.toml` with the Buf
  registry index and stub overrides, a `.gitignore`, and a runnable starter experiment
  (#20).

## [0.1.0] — 2026-08-14

First tagged release.

### Added

- `Experiment` base class with `setup()`/`shot()`/`teardown()` hooks (#1).
- Qt main window, settings, and running an experiment from the GUI (#2, #3, #4).
- Scans, with improved axis handling (#6, #8).
- Per-run HDF5 saving, one file per run (#7).
- Experiment scheduling (#10).
- Log dock, replacing the shot dock (#12).
- `shot()` may return multiple rows, batching within a single shot (#13).
- Declared results and live plots, with plotting separated from results (#15, #17).
- Variable x-axis for line views (#18); `view` as a class-level data descriptor (#19).
- `service_stub` for calling device servers, with a PicoScope example (#16).
- Coverage reporting on pull requests (#11).

[Unreleased]: https://github.com/torbenfreise/h2pcontrol/compare/0.1.0...HEAD
[0.1.0]: https://github.com/torbenfreise/h2pcontrol/releases/tag/0.1.0
