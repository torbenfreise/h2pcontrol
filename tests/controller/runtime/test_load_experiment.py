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


def test_loads_experiment_subclass(session, tmp_path):
    path = _write_experiment(tmp_path, """\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class MyExperiment(Experiment):
            voltage: float = param(1.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """)
    cls = session.load_experiment(str(path))
    assert issubclass(cls, Experiment)
    assert cls.__name__ == "MyExperiment"
    assert "voltage" in cls._parameters


def test_raises_import_error_for_missing_file(session):
    with pytest.raises(ImportError):
        session.load_experiment("/nonexistent/path.py")


def test_raises_value_error_when_no_subclass(session, tmp_path):
    path = _write_experiment(tmp_path, "x = 42\n")
    with pytest.raises(ValueError, match="No Experiment subclass"):
        session.load_experiment(str(path))


def test_reloads_same_path(session, tmp_path):
    path = _write_experiment(tmp_path, """\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class First(Experiment):
            a: float = param(1.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """)
    cls1 = session.load_experiment(str(path))
    assert cls1.__name__ == "First"

    path.write_text(textwrap.dedent("""\
        import pandas as pd
        from h2pcontrol.controller.framework.experiment import Experiment, Context
        from h2pcontrol.controller.framework.parameters import param

        class Second(Experiment):
            b: float = param(2.0)
            async def shot(self, ctx: Context) -> pd.DataFrame:
                return pd.DataFrame()
    """))
    cls2 = session.load_experiment(str(path))
    assert cls2.__name__ == "Second"