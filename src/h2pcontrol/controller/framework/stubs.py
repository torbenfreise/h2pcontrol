from dataclasses import dataclass
from typing import Any


@dataclass
class StubSpec:
    service_name: str
    stub_class: type


def service_stub(service_name: str, stub_class: type) -> Any:
    """Declare a gRPC service stub on an Experiment class.

    The framework resolves and connects the stub once before the shot loop,
    so you can use it inside shot() as a typed attribute.
    """
    return StubSpec(service_name=service_name, stub_class=stub_class)
