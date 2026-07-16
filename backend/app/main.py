"""FastAPI LLM chat service with Prometheus, OTel, Loki logs, and Langfuse."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, nullcontext
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.llm import LLMService, ModelNotReadyError
from app.observability import (
    flush_langfuse,
    get_langfuse,
    get_tracer,
    init_langfuse,
    setup_logging,
    setup_metrics,
    setup_otel,
)
from app.observability.metrics import CHAT_LATENCY, CHAT_REQUESTS, LLM_TOKENS
from app.schemas import ChatRequest, ChatResponse

settings = get_settings()
setup_logging(settings.log_level, settings.app_name)
logger = logging.getLogger(__name__)

llm_service = LLMService(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_langfuse(settings)
    if not settings.lazy_load_model:
        try:
            await asyncio.to_thread(llm_service.load)
        except ModelNotReadyError:
            logger.warning("Model not ready at startup; /ready will stay unhealthy until loaded")
    yield
    flush_langfuse()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
setup_otel(settings, app)
setup_metrics(app, settings.metrics_enabled)


@app.get("/health")
async def health() -> dict[str, str]:
    # Must stay non-blocking so k8s liveness never times out during /chat inference.
    return {"status": "ok", "version": settings.app_version}


@app.get("/ready")
async def ready() -> JSONResponse:
    if llm_service.ready:
        return JSONResponse({"status": "ready", "model": settings.model_path})
    try:
        await asyncio.to_thread(llm_service.load)
        return JSONResponse({"status": "ready", "model": settings.model_path})
    except ModelNotReadyError as exc:
        return JSONResponse({"status": "not_ready", "detail": str(exc)}, status_code=503)


def _generation_context(langfuse: Any, request: ChatRequest):
    if langfuse is None:
        return nullcontext(None)
    return langfuse.start_as_current_observation(
        as_type="generation",
        name="chat-response",
        model=settings.model_path.rsplit("/", 1)[-1],
        input=request.message,
        metadata={"env": settings.app_env, "version": settings.app_version},
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    tracer = get_tracer()
    started = time.perf_counter()
    langfuse = get_langfuse()
    trace_id: str | None = None
    model_name = settings.model_path.rsplit("/", 1)[-1]

    with tracer.start_as_current_span("chat") as span:
        span.set_attribute("user.message_length", len(request.message))
        if request.session_id:
            span.set_attribute("session.id", request.session_id)
        if request.user_id:
            span.set_attribute("user.id", request.user_id)

        with _generation_context(langfuse, request) as observation:
            if langfuse is not None and (request.session_id or request.user_id):
                try:
                    langfuse.update_current_trace(
                        session_id=request.session_id,
                        user_id=request.user_id,
                        tags=["chat", settings.app_env],
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("langfuse update_current_trace skipped", exc_info=True)

            try:
                # Run blocking llama.cpp off the event loop so /health keeps answering
                # (otherwise k8s liveness kills the pod mid-request → curl empty reply).
                result = await asyncio.to_thread(
                    llm_service.chat,
                    request.message,
                    settings.model_max_tokens,
                )
                latency_ms = (time.perf_counter() - started) * 1000

                CHAT_REQUESTS.labels(status="ok").inc()
                CHAT_LATENCY.observe(latency_ms / 1000)
                LLM_TOKENS.labels(direction="prompt").inc(result["usage"].get("prompt_tokens", 0))
                LLM_TOKENS.labels(direction="completion").inc(result["usage"].get("completion_tokens", 0))

                if observation is not None:
                    try:
                        observation.update(
                            output=result["response"],
                            usage_details={
                                "input": result["usage"].get("prompt_tokens", 0),
                                "output": result["usage"].get("completion_tokens", 0),
                                "total": result["usage"].get("total_tokens", 0),
                            },
                        )
                        trace_id = str(getattr(observation, "trace_id", "") or "") or None
                    except Exception:  # noqa: BLE001
                        logger.debug("langfuse observation update skipped", exc_info=True)

                logger.info(
                    "chat_completed",
                    extra={
                        "latency_ms": round(latency_ms, 2),
                        "prompt_tokens": result["usage"].get("prompt_tokens", 0),
                        "completion_tokens": result["usage"].get("completion_tokens", 0),
                        "request_id": http_request.headers.get("x-request-id"),
                    },
                )

                return ChatResponse(
                    response=result["response"],
                    model=result.get("model", model_name),
                    usage=result["usage"],
                    latency_ms=round(latency_ms, 2),
                    trace_id=trace_id,
                )
            except ModelNotReadyError as exc:
                CHAT_REQUESTS.labels(status="not_ready").inc()
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                CHAT_REQUESTS.labels(status="error").inc()
                logger.exception("chat_failed")
                if observation is not None:
                    try:
                        observation.update(level="ERROR", status_message=str(exc))
                    except Exception:  # noqa: BLE001
                        pass
                raise HTTPException(status_code=500, detail=str(exc)) from exc
