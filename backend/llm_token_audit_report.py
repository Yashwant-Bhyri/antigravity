from __future__ import annotations

import argparse
import json
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.llm_usage import load_usage_records


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(round(_num(value)))


def _sum(records: list[dict[str, Any]], key: str) -> int:
    return _int(sum(_num(record.get(key)) for record in records))


def _group(records: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "unknown")].append(record)
    return dict(grouped)


def _summarize_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls": len(records),
        "billable_prompt_tokens": _sum(records, "billable_prompt_tokens"),
        "billable_completion_tokens": _sum(records, "billable_completion_tokens"),
        "billable_total_tokens": _sum(records, "billable_total_tokens"),
        "actual_prompt_tokens": _sum(records, "actual_prompt_tokens"),
        "actual_completion_tokens": _sum(records, "actual_completion_tokens"),
        "actual_total_tokens": _sum(records, "actual_total_tokens"),
        "estimated_prompt_tokens": _sum(records, "estimated_prompt_tokens"),
        "estimated_completion_tokens": _sum(records, "estimated_completion_tokens"),
        "estimated_total_tokens": _sum(records, "estimated_total_tokens"),
        "max_tokens_requested": _sum(records, "max_tokens_requested"),
        "elapsed_ms": round(sum(_num(record.get("elapsed_ms")) for record in records), 3),
        "retries": sum(1 for record in records if record.get("retried")),
        "provider_usage_calls": sum(1 for record in records if record.get("usage_source") == "provider"),
    }


def _fetch_openrouter_pricing(timeout_seconds: float = 8.0) -> dict[str, dict[str, float]]:
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    pricing: dict[str, dict[str, float]] = {}
    for item in payload.get("data", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        raw_pricing = item.get("pricing") or {}
        if not model_id or not isinstance(raw_pricing, dict):
            continue
        try:
            pricing[model_id] = {
                "prompt": float(raw_pricing.get("prompt") or 0.0),
                "completion": float(raw_pricing.get("completion") or 0.0),
            }
        except (TypeError, ValueError):
            continue
    return pricing


def _attach_costs(summary: dict[str, Any], records: list[dict[str, Any]], pricing: dict[str, dict[str, float]]) -> None:
    total_cost = 0.0
    by_model_cost: dict[str, float] = defaultdict(float)
    for record in records:
        model = str(record.get("model") or "")
        price = pricing.get(model)
        if not price:
            continue
        cost = (
            _num(record.get("billable_prompt_tokens")) * price["prompt"]
            + _num(record.get("billable_completion_tokens")) * price["completion"]
        )
        total_cost += cost
        by_model_cost[model] += cost
    summary["estimated_cost_usd"] = round(total_cost, 6)
    summary["estimated_cost_by_model_usd"] = {
        model: round(cost, 6)
        for model, cost in sorted(by_model_cost.items(), key=lambda item: item[1], reverse=True)
    }


def _top(records: list[dict[str, Any]], key: str, limit: int = 15) -> list[dict[str, Any]]:
    fields = [
        "call_site",
        "model",
        "tier",
        "session_id",
        "turn_id",
        "billable_total_tokens",
        "billable_prompt_tokens",
        "billable_completion_tokens",
        "max_tokens_requested",
        "completion_token_utilization",
        "attempt_count",
        "retried",
        "elapsed_ms",
        "usage_source",
    ]
    ranked = sorted(records, key=lambda record: _num(record.get(key)), reverse=True)
    return [{field: record.get(field) for field in fields if record.get(field) not in (None, "")} for record in ranked[:limit]]


def _low_utilization(records: list[dict[str, Any]], limit: int = 15) -> list[dict[str, Any]]:
    candidates = [
        record
        for record in records
        if _num(record.get("max_tokens_requested")) >= 500
        and _num(record.get("completion_token_utilization")) <= 0.2
    ]
    candidates.sort(
        key=lambda record: (
            _num(record.get("max_tokens_requested")) - _num(record.get("billable_completion_tokens")),
            _num(record.get("max_tokens_requested")),
        ),
        reverse=True,
    )
    return _top(candidates, "max_tokens_requested", limit=limit)


def build_report(records: list[dict[str, Any]], *, pricing: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    aggregate_records = [record for record in records if record.get("event") == "llm_call"]
    attempt_records = [record for record in records if record.get("event") == "llm_call_attempt"]
    call_records = aggregate_records or attempt_records

    summary = _summarize_group(call_records)
    retry_attempts = [record for record in attempt_records if record.get("retry_reason")]
    summary.update({
        "record_count": len(records),
        "aggregate_call_records": len(aggregate_records),
        "attempt_records": len(attempt_records),
        "retry_attempts": len(retry_attempts),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    if pricing:
        _attach_costs(summary, call_records, pricing)
    else:
        summary["estimated_cost_usd"] = None
        summary["estimated_cost_by_model_usd"] = {}

    by_model = {
        key: _summarize_group(items)
        for key, items in sorted(
            _group(call_records, "model").items(),
            key=lambda item: _sum(item[1], "billable_total_tokens"),
            reverse=True,
        )
    }
    by_tier = {
        key: _summarize_group(items)
        for key, items in sorted(
            _group(call_records, "tier").items(),
            key=lambda item: _sum(item[1], "billable_total_tokens"),
            reverse=True,
        )
    }
    by_call_site = {
        key: _summarize_group(items)
        for key, items in sorted(
            _group(call_records, "call_site").items(),
            key=lambda item: _sum(item[1], "billable_total_tokens"),
            reverse=True,
        )
    }
    by_session = {
        key: _summarize_group(items)
        for key, items in sorted(
            _group(call_records, "session_id").items(),
            key=lambda item: _sum(item[1], "billable_total_tokens"),
            reverse=True,
        )
    }

    warnings: list[dict[str, Any]] = []
    for record in _top(call_records, "billable_prompt_tokens", limit=10):
        if _num(record.get("billable_prompt_tokens")) >= 3000:
            warnings.append({"type": "large_prompt", **record})
    for record in _low_utilization(call_records, limit=10):
        warnings.append({"type": "low_completion_utilization", **record})

    return {
        "summary": summary,
        "by_model": by_model,
        "by_tier": by_tier,
        "by_call_site": by_call_site,
        "by_session": by_session,
        "retry_overhead": _summarize_group(retry_attempts),
        "top_token_consumers": _top(call_records, "billable_total_tokens"),
        "top_prompt_consumers": _top(call_records, "billable_prompt_tokens"),
        "low_completion_utilization": _low_utilization(call_records),
        "warnings": warnings,
        "event_counts": dict(Counter(str(record.get("event") or "unknown") for record in records)),
    }


def _md_table(rows: list[tuple[Any, ...]], headers: tuple[str, ...]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Antigravity LLM Token Audit",
        "",
        f"Generated: `{summary.get('generated_at')}`",
        "",
        "## Summary",
        "",
        *(_md_table([
            ("Calls", summary["calls"]),
            ("Billable prompt tokens", summary["billable_prompt_tokens"]),
            ("Billable completion tokens", summary["billable_completion_tokens"]),
            ("Billable total tokens", summary["billable_total_tokens"]),
            ("Retries", summary["retries"]),
            ("Retry attempts", summary["retry_attempts"]),
            ("Provider usage calls", summary["provider_usage_calls"]),
            ("Estimated cost USD", summary["estimated_cost_usd"]),
        ], ("Metric", "Value"))),
        "",
        "## By Model",
        "",
    ]
    lines.extend(_md_table(
        [
            (
                model,
                data["calls"],
                data["billable_prompt_tokens"],
                data["billable_completion_tokens"],
                data["billable_total_tokens"],
                data["retries"],
            )
            for model, data in list(report["by_model"].items())[:15]
        ],
        ("Model", "Calls", "Prompt", "Completion", "Total", "Retries"),
    ))
    lines.extend(["", "## Top Token Consumers", ""])
    lines.extend(_md_table(
        [
            (
                item.get("call_site", ""),
                item.get("model", ""),
                item.get("tier", ""),
                item.get("billable_total_tokens", ""),
                item.get("max_tokens_requested", ""),
                item.get("completion_token_utilization", ""),
            )
            for item in report["top_token_consumers"][:15]
        ],
        ("Call Site", "Model", "Tier", "Tokens", "Max Requested", "Utilization"),
    ))
    lines.extend(["", "## Low Completion Utilization", ""])
    lines.extend(_md_table(
        [
            (
                item.get("call_site", ""),
                item.get("model", ""),
                item.get("billable_completion_tokens", ""),
                item.get("max_tokens_requested", ""),
                item.get("completion_token_utilization", ""),
            )
            for item in report["low_completion_utilization"][:15]
        ],
        ("Call Site", "Model", "Completion", "Max Requested", "Utilization"),
    ))
    lines.extend(["", "## Retry Overhead", ""])
    retry = report["retry_overhead"]
    lines.extend(_md_table([
        ("Retry attempts", retry["calls"]),
        ("Retry prompt tokens", retry["billable_prompt_tokens"]),
        ("Retry completion tokens", retry["billable_completion_tokens"]),
        ("Retry total tokens", retry["billable_total_tokens"]),
    ], ("Metric", "Value")))
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(_md_table(
            [
                (
                    item.get("type", ""),
                    item.get("call_site", ""),
                    item.get("model", ""),
                    item.get("billable_total_tokens", ""),
                    item.get("max_tokens_requested", ""),
                )
                for item in report["warnings"][:20]
            ],
            ("Type", "Call Site", "Model", "Tokens", "Max Requested"),
        ))
    else:
        lines.append("No automatic warnings from the available usage records.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an Antigravity LLM token audit report.")
    parser.add_argument("--usage-dir", default="", help="Directory or JSONL file containing LLM usage logs.")
    parser.add_argument("--out-prefix", default="/tmp/antigravity_llm_token_audit", help="Output prefix without extension.")
    parser.add_argument("--fetch-pricing", action="store_true", help="Fetch current OpenRouter pricing for cost estimates.")
    args = parser.parse_args()

    records = load_usage_records(args.usage_dir or None)
    pricing: dict[str, dict[str, float]] = {}
    if args.fetch_pricing:
        try:
            pricing = _fetch_openrouter_pricing()
        except Exception as exc:
            print(f"Pricing fetch failed; continuing with token-only report: {exc}")

    report = build_report(records, pricing=pricing)
    out_prefix = Path(args.out_prefix)
    timestamped_prefix = out_prefix.with_name(f"{out_prefix.name}_{int(time.time())}")
    json_path = timestamped_prefix.with_suffix(".json")
    md_path = timestamped_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
