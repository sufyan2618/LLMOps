"""Item-level and run-level evaluators; scores are sent to Langfuse."""

from __future__ import annotations

import re
from typing import Any


def contains_match(
    *,
    input: Any,
    output: Any,
    expected_output: Any,
    metadata: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deterministic exact/contains match for portfolio CI gates."""
    out = (output or "").strip().lower()
    expected = (expected_output or "").strip().lower()
    ok = bool(expected) and expected in out
    return {
        "name": "accuracy",
        "value": 1.0 if ok else 0.0,
        "comment": "contains match" if ok else f"expected '{expected}' not in output",
    }


def latency_gate(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Score 1.0 if per-item latency is under the threshold (ms) in metadata."""
    meta = metadata or {}
    latency_ms = float(meta.get("latency_ms", 0))
    max_ms = float(meta.get("max_latency_ms", 2000))
    ok = latency_ms <= max_ms
    return {
        "name": "latency_ok",
        "value": 1.0 if ok else 0.0,
        "comment": f"latency={latency_ms:.0f}ms threshold={max_ms:.0f}ms",
    }


def llm_judge_heuristic(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Lightweight stand-in for LLM-as-a-judge when no judge API key is configured.
    Prefer a real judge in production and still push scores to Langfuse.
    """
    text = (output or "").strip()
    if not text:
        return {"name": "judge_quality", "value": 0.0, "comment": "empty response"}
    if len(text) < 2:
        return {"name": "judge_quality", "value": 0.2, "comment": "too short"}
    if re.search(r"\b(error|exception|traceback)\b", text, re.I):
        return {"name": "judge_quality", "value": 0.0, "comment": "looks like an error"}
    score = 0.7
    if expected_output and str(expected_output).lower() in text.lower():
        score = 1.0
    return {"name": "judge_quality", "value": score, "comment": "heuristic judge"}


def average_named(score_name: str):
    def _avg(*, item_results: list[Any], **kwargs: Any) -> dict[str, Any]:
        values: list[float] = []
        for result in item_results:
            evaluations = getattr(result, "evaluations", None) or result.get("evaluations", [])
            for ev in evaluations:
                name = getattr(ev, "name", None) or ev.get("name")
                value = getattr(ev, "value", None) if hasattr(ev, "value") else ev.get("value")
                if name == score_name and value is not None:
                    values.append(float(value))
        if not values:
            return {"name": f"avg_{score_name}", "value": 0.0, "comment": "no scores"}
        avg = sum(values) / len(values)
        return {
            "name": f"avg_{score_name}",
            "value": avg,
            "comment": f"n={len(values)} avg={avg:.3f}",
        }

    return _avg
