from typing import TYPE_CHECKING

import pandas as pd
from h2pcontrol.example.v1.example_pb2 import SayHelloRequest
from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceStub

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.stubs import service_stub

if TYPE_CHECKING:
    from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceAsyncStub


class GreetingExperiment(Experiment):
    name = "Greeting"
    sender = param("World")
    example: "ExampleServiceAsyncStub" = service_stub("example-service", ExampleServiceStub)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        response = await self.example.SayHello(SayHelloRequest(name=self.sender))
        return pd.DataFrame({"greeting": [response.message]})
