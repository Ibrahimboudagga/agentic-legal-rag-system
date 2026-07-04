import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.attributes import service_attributes
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.runtime import OpenTelemetryConfig, Runtime, TelemetryConfig


def _get_otlp_endpoint() -> str:
    return os.getenv("OTEL_ENDPOINT", "http://localhost:4317")


def setup_tracing(service_name: str = "contract-review-worker") -> TracingInterceptor:
    endpoint = _get_otlp_endpoint()
    resource = Resource.create({service_attributes.SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(service_name)
    return TracingInterceptor(tracer=tracer)


def setup_temporal_runtime() -> Runtime:
    endpoint = _get_otlp_endpoint()
    return Runtime(
        telemetry=TelemetryConfig(
            metrics=OpenTelemetryConfig(
                url=endpoint,
                http=False,
                durations_as_seconds=True,
            )
        )
    )
