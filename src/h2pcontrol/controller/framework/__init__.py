"""The experiment authoring API.

Everything needed to write an experiment is re-exported here, so experiments import
from one place:

```python
from h2pcontrol.controller.framework import Context, Experiment, param, result
```

The submodules remain importable, but this list is the public surface — a symbol moving
between submodules is not a breaking change, a symbol leaving `__all__` is.
"""

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParameterError, param
from h2pcontrol.controller.framework.results import ResultError, Results, result
from h2pcontrol.controller.framework.scan import Axis, Scan
from h2pcontrol.controller.framework.stubs import service_stub
from h2pcontrol.controller.framework.views import ViewHandle, ViewKind, view

__all__ = [
    "Axis",
    "Context",
    "Experiment",
    "ParameterError",
    "ResultError",
    "Results",
    "Scan",
    "ViewHandle",
    "ViewKind",
    "param",
    "result",
    "service_stub",
    "view",
]
