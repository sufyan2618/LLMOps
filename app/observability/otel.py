"""OpenTelemetry tracing → OTLP collector (and Langfuse via OTEL/SDK)."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

logger = logging.getLogger(__name__)


def setup_otel(settings: Settings, app=None) -> None:
    if not settings.otel_enabled:
        logger.info("OpenTelemetry disabled")
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.app_env,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics,ready")

    logger.info(
        "OpenTelemetry configured",
        extra={"endpoint": settings.otel_exporter_otlp_endpoint},
    )


def get_tracer(name: str = "llmops"):
    return trace.get_tracer(name)
