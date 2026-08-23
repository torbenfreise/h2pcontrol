import tomllib
from pathlib import Path

import pytest

from h2pcontrol.controller.app import _parse_args
from h2pcontrol.controller.scaffold import STARTER_FILENAME, init_project, project_name


def test_creates_expected_layout(tmp_path: Path) -> None:
    root = init_project(tmp_path / "lab")

    assert root == (tmp_path / "lab").resolve()
    assert (root / "pyproject.toml").is_file()
    assert (root / ".gitignore").is_file()
    assert (root / "experiments").is_dir()
    assert (root / "results").is_dir()


def test_pyproject_carries_index_and_overrides(tmp_path: Path) -> None:
    root = init_project(tmp_path / "lab")
    config = tomllib.loads((root / "pyproject.toml").read_text())

    assert config["project"]["dependencies"] == ["h2pcontrol"]
    assert config["tool"]["uv"]["index"] == [{"url": "https://buf.build/gen/python"}]
    # The pyi stubs must be excluded so the mypy stubs win deterministically.
    assert any(
        "protocolbuffers-pyi" in override and "no-such-platform" in override
        for override in config["tool"]["uv"]["override-dependencies"]
    )
    assert "git" in config["tool"]["uv"]["sources"]["h2pcontrol"]


def test_writes_starter_experiment(tmp_path: Path) -> None:
    root = init_project(tmp_path / "lab")
    starter = root / "experiments" / STARTER_FILENAME

    assert starter.is_file()
    assert "class Ramp(Experiment)" in starter.read_text()


def test_results_is_gitignored(tmp_path: Path) -> None:
    root = init_project(tmp_path / "lab")

    assert "results/" in (root / ".gitignore").read_text()


def test_existing_files_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    (root / "experiments").mkdir(parents=True)
    (root / "pyproject.toml").write_text("# mine\n")
    (root / "experiments" / STARTER_FILENAME).write_text("# mine\n")

    init_project(root)

    assert (root / "pyproject.toml").read_text() == "# mine\n"
    assert (root / "experiments" / STARTER_FILENAME).read_text() == "# mine\n"


def test_force_overwrites(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    (root / "experiments").mkdir(parents=True)
    (root / "pyproject.toml").write_text("# mine\n")
    (root / "experiments" / STARTER_FILENAME).write_text("# mine\n")

    init_project(root, force=True)

    assert "h2pcontrol" in (root / "pyproject.toml").read_text()
    assert "# mine" not in (root / "experiments" / STARTER_FILENAME).read_text()


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    root = init_project(tmp_path / "lab")
    before = (root / "pyproject.toml").read_text()
    listing = sorted(p.name for p in (root / "experiments").glob("*.py"))

    init_project(tmp_path / "lab")

    assert (root / "pyproject.toml").read_text() == before
    assert sorted(p.name for p in (root / "experiments").glob("*.py")) == listing


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        ("My Lab", "my-lab"),
        ("beyer_lab_2026", "beyer-lab-2026"),
        ("...", "experiments"),
    ],
)
def test_project_name_is_slugified(tmp_path: Path, directory: str, expected: str) -> None:
    assert project_name(tmp_path / directory) == expected


def test_cli_defaults_to_gui() -> None:
    assert _parse_args([]).command is None


def test_cli_init_accepts_directory_and_force() -> None:
    args = _parse_args(["init", "lab", "--force"])

    assert args.command == "init"
    assert args.directory == Path("lab")
    assert args.force is True


def test_cli_init_directory_defaults_to_cwd() -> None:
    args = _parse_args(["init"])

    assert args.directory == Path()
    assert args.force is False
