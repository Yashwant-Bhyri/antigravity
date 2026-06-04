from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.llm_usage import load_quality_records, load_usage_records


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _group(records: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "unknown")].append(record)
    return dict(grouped)


def _agent_family(call_site: str) -> str:
    call_site = call_site or "unknown"
    patterns = [
        ("resume_agent", "ResumeAgent"),
        ("concept_agent", "ConceptAgent"),
        ("weakness_agent", "WeaknessAgent"),
        ("discrepancy_agent", "DiscrepancyAgent"),
        ("reasoning_behavior_agent", "ReasoningBehaviorAgent"),
        ("application_agent", "ApplicationAgent"),
        ("followup_agent", "FollowUpAgent"),
        ("evaluation_agent", "EvaluationAgent"),
        ("interview_map", "InterviewMap"),
        ("orchestrator", "Orchestrator"),
        ("simulation_service", "SimulationService"),
        ("inventory_simulation_service", "InventorySimulationService"),
    ]
    for needle, label in patterns:
        if needle in call_site:
            return label
    return "Other"


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text or ""))


def _text_quality_flags(record: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    output = str(record.get("cleaned_output") or record.get("raw_output") or "")
    if not output:
        return flags
    lower = output.lower()
    if "as an ai" in lower or "i cannot" in lower or "i can't" in lower:
        flags.append("model_refusal_or_meta")
    if "here is" in lower[:80] or "json" in lower[:80] or "```" in output:
        flags.append("formatting_noise")
    if _word_count(output) > 120 and str(record.get("response_format") or "") != "json_object":
        flags.append("verbose_question_output")
    if output.count("?") > 1 and "followup_agent" in str(record.get("call_site") or ""):
        flags.append("multi_question_followup")
    return flags


def _summarize(records: list[dict[str, Any]], usage_by_call_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    call_ids = {str(record.get("call_id") or "") for record in records if record.get("call_id")}
    usage_records = [usage_by_call_id[call_id] for call_id in call_ids if call_id in usage_by_call_id]
    all_flags = Counter()
    for record in records:
        all_flags.update(str(flag) for flag in (record.get("flags") or []))
        all_flags.update(_text_quality_flags(record))
    return {
        "records": len(records),
        "call_ids": len(call_ids),
        "attempts": sum(1 for record in records if record.get("event") == "llm_quality_attempt"),
        "aggregate_calls": sum(1 for record in records if record.get("event") == "llm_quality_call"),
        "retries": sum(1 for record in records if record.get("retried") or record.get("retry_reason")),
        "parse_failures": sum(
            1
            for record in records
            if record.get("event") == "llm_quality_attempt"
            and str(record.get("response_format") or "")
            and not bool(record.get("parse_success"))
        ),
        "provider_errors": sum(1 for record in records if record.get("error_type")),
        "flag_counts": dict(all_flags),
        "usage_billable_total_tokens": int(sum(_num(record.get("billable_total_tokens")) for record in usage_records)),
        "usage_billable_prompt_tokens": int(sum(_num(record.get("billable_prompt_tokens")) for record in usage_records)),
        "usage_billable_completion_tokens": int(sum(_num(record.get("billable_completion_tokens")) for record in usage_records)),
        "elapsed_ms": round(sum(_num(record.get("elapsed_ms")) for record in records), 3),
    }


def _top_flagged(records: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        flags = list(record.get("flags") or []) + _text_quality_flags(record)
        if not flags:
            continue
        rows.append({
            "call_id": record.get("call_id"),
            "attempt_number": record.get("attempt_number"),
            "call_site": record.get("call_site"),
            "agent_family": _agent_family(str(record.get("call_site") or "")),
            "model": record.get("model"),
            "tier": record.get("tier"),
            "flags": sorted(set(flags)),
            "response_format": record.get("response_format"),
            "parse_success": record.get("parse_success"),
            "raw_output_chars": record.get("raw_output_chars"),
            "cleaned_output_chars": record.get("cleaned_output_chars"),
            "elapsed_ms": record.get("elapsed_ms"),
            "output_preview": str(record.get("cleaned_output") or record.get("raw_output") or "")[:500],
        })
    rows.sort(key=lambda item: (len(item["flags"]), _num(item.get("cleaned_output_chars"))), reverse=True)
    return rows[:limit]


def _repeated_prompts(records: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    attempts = [record for record in records if record.get("event") == "llm_quality_attempt"]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in attempts:
        key = (
            str(record.get("call_site") or "unknown"),
            str(record.get("system_hash") or ""),
            str(record.get("user_hash") or ""),
        )
        grouped[key].append(record)
    rows: list[dict[str, Any]] = []
    for (call_site, system_hash, user_hash), items in grouped.items():
        if len(items) < 2:
            continue
        rows.append({
            "call_site": call_site,
            "agent_family": _agent_family(call_site),
            "repeat_count": len(items),
            "system_hash": system_hash,
            "user_hash": user_hash,
            "models": sorted({str(item.get("model") or "") for item in items}),
            "session_ids": sorted({str(item.get("session_id") or "") for item in items if item.get("session_id")})[:8],
            "turn_ids": sorted({str(item.get("turn_id") or "") for item in items if item.get("turn_id")})[:8],
        })
    rows.sort(key=lambda item: item["repeat_count"], reverse=True)
    return rows[:limit]


def _call_details(records: list[dict[str, Any]], usage_by_call_id: dict[str, dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    aggregates = [record for record in records if record.get("event") == "llm_quality_call"]
    if not aggregates:
        aggregates = records
    rows: list[dict[str, Any]] = []
    for record in aggregates:
        call_id = str(record.get("call_id") or "")
        usage = usage_by_call_id.get(call_id, {})
        rows.append({
            "call_id": call_id,
            "call_site": record.get("call_site"),
            "agent_family": _agent_family(str(record.get("call_site") or "")),
            "model": record.get("model"),
            "tier": record.get("tier"),
            "session_id": record.get("session_id"),
            "turn_id": record.get("turn_id"),
            "attempt_count": record.get("attempt_count"),
            "retried": record.get("retried"),
            "retry_succeeded": record.get("retry_succeeded"),
            "flags": record.get("flags") or [],
            "billable_total_tokens": usage.get("billable_total_tokens"),
            "billable_prompt_tokens": usage.get("billable_prompt_tokens"),
            "billable_completion_tokens": usage.get("billable_completion_tokens"),
            "max_tokens_requested": usage.get("max_tokens_requested") or record.get("max_tokens_requested"),
            "completion_token_utilization": usage.get("completion_token_utilization"),
            "elapsed_ms": record.get("elapsed_ms"),
        })
    rows.sort(key=lambda item: _num(item.get("billable_total_tokens")), reverse=True)
    return rows[:limit]


def build_quality_report(
    quality_records: list[dict[str, Any]],
    usage_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    quality_records = [
        record
        for record in quality_records
        if str(record.get("event") or "").startswith("llm_quality_")
    ]
    usage_records = usage_records or []
    usage_by_call_id = {
        str(record.get("call_id")): record
        for record in usage_records
        if record.get("event") == "llm_call" and record.get("call_id")
    }
    aggregate_quality = [record for record in quality_records if record.get("event") == "llm_quality_call"]
    attempt_quality = [record for record in quality_records if record.get("event") == "llm_quality_attempt"]
    grouped_by_agent = defaultdict(list)
    grouped_by_call_site = defaultdict(list)
    grouped_by_model = defaultdict(list)
    for record in quality_records:
        call_site = str(record.get("call_site") or "unknown")
        grouped_by_agent[_agent_family(call_site)].append(record)
        grouped_by_call_site[call_site].append(record)
        grouped_by_model[str(record.get("model") or "unknown")].append(record)

    return {
        "summary": {
            **_summarize(quality_records, usage_by_call_id),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "quality_records": len(quality_records),
            "quality_attempt_records": len(attempt_quality),
            "quality_aggregate_records": len(aggregate_quality),
            "usage_records_joined": len(usage_by_call_id),
            "full_text_records": sum(
                1
                for record in quality_records
                if record.get("system_prompt") or record.get("user_prompt") or record.get("raw_output")
            ),
        },
        "by_agent_family": {
            key: _summarize(items, usage_by_call_id)
            for key, items in sorted(grouped_by_agent.items())
        },
        "by_call_site": {
            key: _summarize(items, usage_by_call_id)
            for key, items in sorted(
                grouped_by_call_site.items(),
                key=lambda item: _summarize(item[1], usage_by_call_id)["usage_billable_total_tokens"],
                reverse=True,
            )
        },
        "by_model": {
            key: _summarize(items, usage_by_call_id)
            for key, items in sorted(grouped_by_model.items())
        },
        "top_flagged_outputs": _top_flagged(attempt_quality),
        "repeated_prompts": _repeated_prompts(quality_records),
        "top_call_details": _call_details(quality_records, usage_by_call_id),
        "event_counts": dict(Counter(str(record.get("event") or "unknown") for record in quality_records)),
    }


def _md_table(rows: list[tuple[Any, ...]], headers: tuple[str, ...]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item).replace("\n", " ")[:220] for item in row) + " |")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Antigravity LLM Quality Audit",
        "",
        f"Generated: `{summary.get('generated_at')}`",
        "",
        "## Summary",
        "",
        *(_md_table([
            ("Quality records", summary["quality_records"]),
            ("Aggregate calls", summary["quality_aggregate_records"]),
            ("Attempts", summary["quality_attempt_records"]),
            ("Full-text records", summary["full_text_records"]),
            ("Retries", summary["retries"]),
            ("Parse failures", summary["parse_failures"]),
            ("Provider errors", summary["provider_errors"]),
            ("Joined token records", summary["usage_records_joined"]),
            ("Joined billable tokens", summary["usage_billable_total_tokens"]),
        ], ("Metric", "Value"))),
        "",
        "## By Agent",
        "",
    ]
    lines.extend(_md_table(
        [
            (
                agent,
                data["call_ids"],
                data["attempts"],
                data["retries"],
                data["parse_failures"],
                data["provider_errors"],
                data["usage_billable_total_tokens"],
                data["flag_counts"],
            )
            for agent, data in report["by_agent_family"].items()
        ],
        ("Agent", "Calls", "Attempts", "Retries", "Parse Failures", "Errors", "Tokens", "Flags"),
    ))
    lines.extend(["", "## Top Calls By Tokens", ""])
    lines.extend(_md_table(
        [
            (
                item.get("agent_family", ""),
                item.get("call_site", ""),
                item.get("model", ""),
                item.get("attempt_count", ""),
                item.get("billable_total_tokens", ""),
                item.get("completion_token_utilization", ""),
                item.get("flags", ""),
            )
            for item in report["top_call_details"][:20]
        ],
        ("Agent", "Call Site", "Model", "Attempts", "Tokens", "Utilization", "Flags"),
    ))
    lines.extend(["", "## Flagged Outputs", ""])
    if report["top_flagged_outputs"]:
        lines.extend(_md_table(
            [
                (
                    item.get("agent_family", ""),
                    item.get("call_site", ""),
                    item.get("model", ""),
                    item.get("flags", ""),
                    item.get("parse_success", ""),
                    item.get("output_preview", ""),
                )
                for item in report["top_flagged_outputs"][:20]
            ],
            ("Agent", "Call Site", "Model", "Flags", "Parse OK", "Output Preview"),
        ))
    else:
        lines.append("No flagged outputs found.")
    lines.extend(["", "## Repeated Prompt Hashes", ""])
    if report["repeated_prompts"]:
        lines.extend(_md_table(
            [
                (
                    item.get("agent_family", ""),
                    item.get("call_site", ""),
                    item.get("repeat_count", ""),
                    item.get("models", ""),
                    item.get("session_ids", ""),
                    item.get("turn_ids", ""),
                )
                for item in report["repeated_prompts"][:20]
            ],
            ("Agent", "Call Site", "Repeats", "Models", "Sessions", "Turns"),
        ))
    else:
        lines.append("No repeated prompt hashes found.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an Antigravity LLM quality audit report.")
    parser.add_argument("--quality-dir", default="", help="Directory or JSONL file containing LLM quality logs.")
    parser.add_argument("--usage-dir", default="", help="Optional token usage directory or JSONL file to join by call_id.")
    parser.add_argument("--out-prefix", default="/tmp/antigravity_llm_quality_audit", help="Output prefix without extension.")
    args = parser.parse_args()

    quality_records = load_quality_records(args.quality_dir or None)
    usage_records = load_usage_records(args.usage_dir or None) if args.usage_dir else load_usage_records(None)
    report = build_quality_report(quality_records, usage_records)
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
