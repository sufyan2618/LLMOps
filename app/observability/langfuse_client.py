"""Langfuse client bootstrap (traces + scores)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)
_client: Any = None


def init_langfuse(settings: Settings) -> Any:
    global _client
    if not settings.langfuse_enabled:
        logger.info("Langfuse disabled")
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse enabled but keys missing; skipping init")
        return None

    from langfuse import Langfuse

    _client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
    )
    logger.info("Langfuse client initialized", extra={"base_url": settings.langfuse_base_url})
    return _client


def get_langfuse() -> Any:
    return _client


def flush_langfuse() -> None:
    if _client is not None:
        _client.flush()
