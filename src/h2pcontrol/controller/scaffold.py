import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_URL = "https://github.com/torbenfreise/h2pcontrol"

STARTER_FILENAME = "ramp.py"

_PYPROJECT = """[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["h2pcontrol"]

[[tool.uv.index]]
url = "https://buf.build/gen/python"

[tool.uv]
# The official protocolbuffers-pyi and mypy-protobuf stubs both ship the same
# *_pb2.pyi paths; whichever installs last wins, which is non-deterministic across
# machines.
# We exclude pyi here to ensure  the richer mypy stubs  win deterministically.
override-dependencies = [
    "protobuf>=7.34.1",
    "beyer-labs-h2pcontrol-protocolbuffers-pyi ; sys_platform == 'no-such-platform'",
]

[tool.uv.sources]
h2pcontrol = {{ git = "{repo}" }}

[tool.pyright]
pythonVersion = "3.12"
"""

_GITIGNORE = """.venv/
__pycache__/
*.py[cod]

results/
"""

_STARTER = '''"""
Example Experiment declaring a series plot.
Open it with File -> Open Experiment, set Repeats, and press Schedule. 
Does not required the h2pmanager or any device servers.
"""

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.results import Results, result
from h2pcontrol.controller.framework.views import ViewKind, view


class Ramp(Experiment):
    # Title shown in the GUI.
    name = "Ramp"

    # Editable in gui. its value is stored for every shot.
    amplitude = param(1.0, min=0.0, max=10.0, unit="V")

    # A live plot panel. SERIES accumulates one point per push.
    signal = view("Signal", ViewKind.SERIES, y_unit="V")

    # One row of recorded data. Determines the HDF5 schema
    class Record(Results):
        value: float = result(unit="V")

    async def shot(self, ctx: Context) -> list[Record]:
        value = self.amplitude * ctx.shot_idx
        self.signal.push(ctx.shot_idx, value)
        return [self.Record(value=value)]
'''


def project_name(directory: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", directory.resolve().name.lower()).strip("-")
    return slug or "experiments"


def _write(path: Path, content: str, *, label: str, force: bool) -> bool:
    """Write *content* to *path*, unless it exists and *force* is not set."""
    if path.exists() and not force:
        logger.info("  skip     %s (exists)", label)
        return False
    path.write_text(content, encoding="utf-8")
    logger.info("  create   %s", label)
    return True


def init_project(directory: Path, *, force: bool = False) -> Path:
    """Scaffold an experiment project in *directory*, creating it if needed.
    Use force to overwrite existing files.
    """
    root = directory.expanduser().resolve()
    experiments = root / "experiments"
    results = root / "results"
    for path in (root, experiments, results):
        path.mkdir(parents=True, exist_ok=True)

    logger.info("Scaffolding experiment project in %s", root)
    _write(
        root / "pyproject.toml",
        _PYPROJECT.format(name=project_name(root), repo=_REPO_URL),
        label="pyproject.toml",
        force=force,
    )
    _write(root / ".gitignore", _GITIGNORE, label=".gitignore", force=force)
    _write(
        experiments / STARTER_FILENAME,
        _STARTER,
        label=f"experiments/{STARTER_FILENAME}",
        force=force,
    )

    logger.info("")
    logger.info("Next steps:")
    logger.info("  cd %s", root)
    logger.info("  uv sync            # create the environment")
    logger.info("  uv run h2pcontrol  # launch the GUI")
    return root
