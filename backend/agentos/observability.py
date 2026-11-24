"""Opt-in OpenTelemetry export of metadata only; no raw prompts or auth headers."""

import hashlib
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def tracer():
    if os.getenv("OTEL_ENABLED", "false") != "true":
        return None
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": "agentos"}))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()
    else:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("agentos", "0.2.0")


def emit(kind, workspace, run_id, payload):
    current = tracer()
    if not current:
        return
    with current.start_as_current_span("agentos." + kind) as span:
        span.set_attribute(
            "agentos.workspace_hash", hashlib.sha256(workspace.encode()).hexdigest()[:16]
        )
        span.set_attribute("agentos.run_id", run_id or "none")
        for key in [
            "provider",
            "model",
            "schema",
            "prompt_version",
            "seconds",
            "input_tokens",
            "output_tokens",
            "estimated_cost_usd",
            "error",
            "tool",
            "method",
            "namespace",
            "status",
        ]:
            if payload.get(key) is not None:
                span.set_attribute("agentos." + key, payload[key])
