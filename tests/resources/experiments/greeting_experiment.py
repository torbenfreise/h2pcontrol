from typing import TYPE_CHECKING

from h2pcontrol.example.v1.example_pb2 import SayHelloRequest
from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceStub

from h2pcontrol.controller.framework import (
    Context,
    Experiment,
    Results,
    param,
    result,
    service_stub,
)

if TYPE_CHECKING:
    from h2pcontrol.example.v1.example_pb2_grpc import ExampleServiceAsyncStub


class GreetingExperiment(Experiment):
    name = "Greeting"
    sender = param("World")
    example: "ExampleServiceAsyncStub" = service_stub("example-service", ExampleServiceStub)

    class Record(Results):
        greeting: str = result(description="Service greeting")

    async def shot(self, ctx: Context) -> list[Record]:
        response = await self.example.SayHello(SayHelloRequest(name=self.sender))
        return [self.Record(greeting=response.message)]
