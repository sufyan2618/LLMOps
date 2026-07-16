"""Lazy GGUF model loader (volume-mounted path)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


class ModelNotReadyError(RuntimeError):
    pass


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm: Any = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    @property
    def ready(self) -> bool:
        return self._llm is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        with self._lock:
            if self._llm is not None:
                return
            if self._load_error:
                raise ModelNotReadyError(self._load_error)
            try:
                from llama_cpp import Llama

                logger.info("Loading GGUF model", extra={"path": self._settings.model_path})
                self._llm = Llama(
                    model_path=self._settings.model_path,
                    n_ctx=self._settings.model_n_ctx,
                    n_threads=self._settings.model_n_threads,
                    n_batch=256,
                    verbose=False,
                )
                logger.info("GGUF model loaded")
            except Exception as exc:  # noqa: BLE001
                self._load_error = str(exc)
                logger.exception("Failed to load model")
                raise ModelNotReadyError(self._load_error) from exc

    def ensure_loaded(self) -> None:
        if self._llm is None:
            self.load()

    def chat(self, message: str, max_tokens: int = 128) -> dict[str, Any]:
        self.ensure_loaded()
        assert self._llm is not None
        # Qwen3: /no_think skips long chain-of-thought (saves RAM/time on CPU VPS).
        user_content = message if "/no_think" in message or "/think" in message else f"{message}\n/no_think"
        completion = self._llm.create_chat_completion(
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        content = completion["choices"][0]["message"]["content"]
        usage = completion.get("usage") or {}
        return {
            "response": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "model": self._settings.model_path.rsplit("/", 1)[-1],
        }
