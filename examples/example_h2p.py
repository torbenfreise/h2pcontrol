"""
Example experiment that tests the full h2pcontrol ecosystem.
Requires the h2pcontrol manager and a ExampleService to be running.
an ExampleService implementation can be found here: https://github.com/torbenfreise/h2pcontrol-server-template
"""
from typing import Literal, TYPE_CHECKING

from h2pcontrol.example.v1.example_pb2 import SayHelloRequest
import pandas as pd

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.framework.stubs import service_stub
from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceStub

if TYPE_CHECKING:
    from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceAsyncStub


class ExampleExperiment(Experiment):
    name = "Example h2pcontrol"
    sender_name = param("Torben")
    example: "ExampleServiceAsyncStub" = service_stub("example-service", ExampleServiceStub)

    async def shot(self, ctx: Context) -> pd.DataFrame:
        response = await self.example.SayHello(SayHelloRequest(name=self.sender_name))
        return pd.DataFrame({"response": [response.message]})
