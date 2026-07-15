#!/usr/bin/env python3
"""
CI evaluation quality gate.

Flow:
  Deploy → run dataset → generate responses → score → push to Langfuse → gate

Fails the process if avg accuracy < EVAL_MIN_AVG_SCORE or p95 latency > EVAL_MAX_P95_LATENCY_MS.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.judges import (  # noqa: E402
    contains_match,
    latency_gate,
    llm_judge_heuristic,
)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def load_dataset(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def call_chat(client: httpx.Client, base_url: str, prompt: str) -> tuple[str, float, str | None]:
    started = time.perf_counter()
    resp = client.post(f"{base_url.rstrip('/')}/chat", json={"message": prompt}, timeout=120.0)
    latency_ms = (time.perf_counter() - started) * 1000
    resp.raise_for_status()
    body = resp.json()
    return body.get("response", ""), latency_ms, body.get("trace_id")


def push_score_langfuse(
    *,
    enabled: bool,
    name: str,
    value: float,
    trace_id: str | None,
    comment: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not enabled:
        return
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        return
    try:
        from langfuse import get_client

        lf = get_client()
        # Prefer attaching to a known trace; otherwise create a scored event span
        if trace_id:
            lf.create_score(name=name, value=value, trace_id=trace_id, comment=comment)
        else:
            with lf.start_as_current_observation(as_type="span", name="ci-eval-item") as span:
                span.update(metadata=metadata or {})
                span.score(name=name, value=value, comment=comment)
        lf.flush()
    except Exception as exc:  # noqa: BLE001
        print(f"warn: failed to push Langfuse score '{name}': {exc}", file=sys.stderr)


def run_experiment_sdk(dataset: list[dict[str, Any]], base_url: str, max_latency_ms: float) -> dict[str, Any] | None:
    """Use Langfuse experiment runner when credentials are present."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        return None

    try:
        from langfuse import Evaluation, get_client
    except ImportError:
        return None

    lf = get_client()
    data = [
        {
            "input": item["input"],
            "expected_output": item.get("expected_output"),
            "metadata": {"id": item.get("id"), "max_latency_ms": max_latency_ms},
        }
        for item in dataset
    ]

    def task(*, item, **kwargs):  # type: ignore[no-untyped-def]
        with httpx.Client() as client:
            response, latency_ms, _trace_id = call_chat(client, base_url, item["input"])
        # Attach latency into metadata for latency_gate via kwargs not available;
        # return structured payload and unwrap in evaluators via output string.
        return json.dumps({"response": response, "latency_ms": latency_ms})

    def accuracy_eval(*, input, output, expected_output, metadata, **kwargs):  # type: ignore[no-untyped-def]
        payload = json.loads(output) if isinstance(output, str) and output.startswith("{") else {"response": output}
        result = contains_match(
            input=input,
            output=payload.get("response", output),
            expected_output=expected_output,
            metadata=metadata,
        )
        return Evaluation(name=result["name"], value=result["value"], comment=result["comment"])

    def latency_eval(*, input, output, expected_output, metadata, **kwargs):  # type: ignore[no-untyped-def]
        payload = json.loads(output) if isinstance(output, str) and output.startswith("{") else {"latency_ms": 0}
        meta = dict(metadata or {})
        meta["latency_ms"] = payload.get("latency_ms", 0)
        meta["max_latency_ms"] = meta.get("max_latency_ms", max_latency_ms)
        result = latency_gate(input=input, output=payload.get("response", ""), metadata=meta)
        return Evaluation(name=result["name"], value=result["value"], comment=result["comment"])

    def judge_eval(*, input, output, expected_output, metadata, **kwargs):  # type: ignore[no-untyped-def]
        payload = json.loads(output) if isinstance(output, str) and output.startswith("{") else {"response": output}
        result = llm_judge_heuristic(
            input=input,
            output=payload.get("response", output),
            expected_output=expected_output,
            metadata=metadata,
        )
        return Evaluation(name=result["name"], value=result["value"], comment=result["comment"])

    def avg_accuracy(*, item_results, **kwargs):  # type: ignore[no-untyped-def]
        values = [
            float(e.value) for r in item_results for e in r.evaluations if e.name == "accuracy" and e.value is not None
        ]
        avg = sum(values) / len(values) if values else 0.0
        return Evaluation(name="avg_accuracy", value=avg, comment=f"n={len(values)}")

    result = lf.run_experiment(
        name="ci-evaluation",
        description="Automated quality gate after deploy",
        data=data,
        task=task,
        evaluators=[accuracy_eval, latency_eval, judge_eval],
        run_evaluators=[avg_accuracy],
        metadata={"base_url": base_url, "ci": True},
    )
    lf.flush()
    print(result.format())
    return {"sdk": True, "result": result}


def run_local(
    dataset: list[dict[str, Any]],
    base_url: str,
    min_avg: float,
    max_p95_ms: float,
    push_scores: bool,
) -> int:
    latencies: list[float] = []
    accuracy_scores: list[float] = []
    judge_scores: list[float] = []
    results: list[dict[str, Any]] = []

    with httpx.Client() as client:
        # Health first
        health = client.get(f"{base_url.rstrip('/')}/health", timeout=30.0)
        health.raise_for_status()

        for item in dataset:
            try:
                response, latency_ms, trace_id = call_chat(client, base_url, item["input"])
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR item={item.get('id')}: {exc}", file=sys.stderr)
                accuracy_scores.append(0.0)
                judge_scores.append(0.0)
                latencies.append(max_p95_ms * 2)
                results.append({"id": item.get("id"), "error": str(exc), "accuracy": 0.0})
                continue

            latencies.append(latency_ms)
            meta = {"latency_ms": latency_ms, "max_latency_ms": max_p95_ms, "id": item.get("id")}
            acc = contains_match(
                input=item["input"],
                output=response,
                expected_output=item.get("expected_output"),
                metadata=meta,
            )
            lat = latency_gate(input=item["input"], output=response, metadata=meta)
            judge = llm_judge_heuristic(
                input=item["input"],
                output=response,
                expected_output=item.get("expected_output"),
                metadata=meta,
            )
            accuracy_scores.append(float(acc["value"]))
            judge_scores.append(float(judge["value"]))

            for score in (acc, lat, judge):
                push_score_langfuse(
                    enabled=push_scores,
                    name=score["name"],
                    value=float(score["value"]),
                    trace_id=trace_id,
                    comment=score["comment"],
                    metadata=meta,
                )

            results.append(
                {
                    "id": item.get("id"),
                    "latency_ms": round(latency_ms, 2),
                    "accuracy": acc["value"],
                    "latency_ok": lat["value"],
                    "judge_quality": judge["value"],
                    "trace_id": trace_id,
                    "response_preview": response[:200],
                }
            )
            print(f"✓ {item.get('id')}: accuracy={acc['value']} latency_ms={latency_ms:.0f} judge={judge['value']}")

    avg_accuracy = statistics.fmean(accuracy_scores) if accuracy_scores else 0.0
    avg_judge = statistics.fmean(judge_scores) if judge_scores else 0.0
    p95 = percentile(latencies, 95)

    summary = {
        "n": len(dataset),
        "avg_accuracy": round(avg_accuracy, 4),
        "avg_judge_quality": round(avg_judge, 4),
        "p95_latency_ms": round(p95, 2),
        "min_avg_score_gate": min_avg,
        "max_p95_latency_ms_gate": max_p95_ms,
        "items": results,
    }

    out_dir = ROOT / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "items"}, indent=2))

    # Also push run-level aggregates
    push_score_langfuse(
        enabled=push_scores,
        name="avg_accuracy",
        value=avg_accuracy,
        trace_id=None,
        comment="CI run aggregate",
        metadata=summary,
    )

    failed = False
    if avg_accuracy < min_avg:
        print(f"FAIL: avg_accuracy {avg_accuracy:.3f} < {min_avg}", file=sys.stderr)
        failed = True
    if p95 > max_p95_ms:
        print(f"FAIL: p95 latency {p95:.0f}ms > {max_p95_ms:.0f}ms", file=sys.stderr)
        failed = True

    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Langfuse-backed evaluation quality gate")
    parser.add_argument("--base-url", default=os.getenv("EVAL_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument(
        "--dataset",
        default=os.getenv("EVAL_DATASET_PATH", str(ROOT / "evaluation" / "dataset.json")),
    )
    parser.add_argument("--min-avg-score", type=float, default=float(os.getenv("EVAL_MIN_AVG_SCORE", "0.9")))
    parser.add_argument(
        "--max-p95-latency-ms",
        type=float,
        default=float(os.getenv("EVAL_MAX_P95_LATENCY_MS", "2000")),
    )
    parser.add_argument("--use-sdk-experiment", action="store_true")
    parser.add_argument("--no-langfuse", action="store_true")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset))
    push_scores = not args.no_langfuse

    if args.use_sdk_experiment:
        sdk = run_experiment_sdk(dataset, args.base_url, args.max_p95_latency_ms)
        if sdk is not None:
            print("Langfuse SDK experiment completed; running local gate on HTTP responses as well...")

    return run_local(
        dataset=dataset,
        base_url=args.base_url,
        min_avg=args.min_avg_score,
        max_p95_ms=args.max_p95_latency_ms,
        push_scores=push_scores,
    )


if __name__ == "__main__":
    raise SystemExit(main())
