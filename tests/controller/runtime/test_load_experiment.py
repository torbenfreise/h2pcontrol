import textwrap
from pathlib import Path

import pytest

from h2pcontrol.controller.framework.experiment import Experiment
from h2pcontrol.controller.runtime.session import Session


@pytest.fixture
def session():
    return Session()


def _write_experiment(tmp_path: Path, source: str) -> Path:
    p = tmp_path / "exp.py"
    p.write_text(textwrap.dedent(source))
    return p


def _load_experiment(session: Session, path: str | Path) -> type[Experiment]:
    """Read an experiment file and compile it via the session's source loader.

    Mirrors what the GUI does at File→Open; kept in the tests because only they
    load an experiment straight from a path (production drives from captured text).
    """
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise ImportError(f"Cannot load experiment from {str(path)!r}")
    return session.load_experiment_from_source(resolved.read_text(encoding="utf-8"), resolved)


def test_loads_experiment_subclass(session, tmp_path):
    path = _write_experiment(
        tmp_path,
        """\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class MyExperiment(Experiment):
            voltage: float = param(1.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """,
    )
    cls = _load_experiment(session, str(path))
    assert issubclass(cls, Experiment)
    assert cls.__name__ == "MyExperiment"
    assert "voltage" in cls.parameters()


def test_raises_import_error_for_missing_file(session):
    with pytest.raises(ImportError):
        _load_experiment(session, "/nonexistent/path.py")


def test_raises_value_error_when_no_subclass(session, tmp_path):
    path = _write_experiment(tmp_path, "x = 42\n")
    with pytest.raises(ValueError, match="No Experiment subclass"):
        _load_experiment(session, str(path))


def test_reloads_same_path(session, tmp_path):
    path = _write_experiment(
        tmp_path,
        """\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class First(Experiment):
            a: float = param(1.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """,
    )
    cls1 = _load_experiment(session, str(path))
    assert cls1.__name__ == "First"

    path.write_text(
        textwrap.dedent("""\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class Second(Experiment):
            b: float = param(2.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """)
    )
    cls2 = _load_experiment(session, str(path))
    assert cls2.__name__ == "Second"


def test_excludes_imported_base_class(session, tmp_path):
    """An imported Experiment subclass from another module should not be picked up."""
    # Write a "base" module
    base_path = tmp_path / "base_exp.py"
    base_path.write_text(
        textwrap.dedent("""\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context

        class BaseExp(Experiment):
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """)
    )
    # Write a "derived" module that imports BaseExp
    derived_path = tmp_path / "derived_exp.py"
    derived_path.write_text(
        textwrap.dedent(
            """\
        import sys
        sys.path.insert(0, "{tmp_path}")
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param
        from base_exp import BaseExp

        class DerivedExp(BaseExp):
            x: float = param(1.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame({{"x": [self.x]}})
    """.replace("{tmp_path}", str(tmp_path))
        )
    )
    cls = _load_experiment(session, str(derived_path))
    assert cls.__name__ == "DerivedExp"


def test_multiple_classes_raises(session, tmp_path):
    """A file with two Experiment subclasses should be rejected."""
    path = _write_experiment(
        tmp_path,
        """\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class ExpA(Experiment):
            a: float = param(1.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()

        class ExpB(Experiment):
            b: float = param(2.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """,
    )
    with pytest.raises(ValueError, match="multiple experiments"):
        _load_experiment(session, str(path))
