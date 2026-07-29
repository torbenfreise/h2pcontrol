from __future__ import annotations

import importlib.metadata
import sys

from .spec import RunRequest


def run_metadata(request: RunRequest) -> dict[str, str]:
    """Collect metadata for a given RunRequest"""
    attrs: dict[str, str] = {
        "h2pcontrol_version": _package_version(),
        "python_version": sys.version,
    }

    if request.source:
        attrs["experiment_source"] = request.source

    return attrs


def _package_version() -> str:
    try:
        return importlib.metadata.version("h2pcontrol")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
