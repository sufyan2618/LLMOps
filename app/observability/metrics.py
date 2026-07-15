"""Prometheus custom LLM metrics."""

from __future__ import annotations

from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

CHAT_REQUESTS = Counter(
    "llm_chat_requests_total",
    "Total chat requests",
    ["status"],
)
CHAT_LATENCY = Histogram(
    "llm_chat_latency_seconds",
    "Chat end-to-end latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Token usage reported by llama.cpp",
    ["direction"],
)


def setup_metrics(app, enabled: bool = True) -> None:
    if not enabled:
        return
    Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics", "/health", "/ready"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
