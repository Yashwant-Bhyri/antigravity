from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

import backend.main  # noqa: F401 - load project env
from backend.models.llm_router import _load_json_lenient


MODELS = [
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
]

PROMPTS = [
    {
        "name": "plain_product_question",
        "response_format": None,
        "max_tokens": 500,
        "system": "You are a senior product analytics interviewer.",
        "user": (
            "A Product Analyst says they improved trial-to-subscription conversion from 27% to 42% "
            "by reducing a trial from 7 days to 1 day. Ask one sharp interview question and explain "
            "in two short bullets what a strong answer should cover."
        ),
    },
    {
        "name": "strict_json_small",
        "response_format": {"type": "json_object"},
        "max_tokens": 700,
        "system": "Return valid JSON only.",
        "user": (
            "Create one interview question for a Product Analyst and three scoring dimensions. "
            'Return exactly: {"question":"...", "dimensions":[{"id":"...", "label":"...", "weight":2.0}]}'
        ),
    },
    {
        "name": "json_repair_small",
        "response_format": {"type": "json_object"},
        "max_tokens": 700,
        "system": "You are a JSON repair utility. Preserve content. Return one valid JSON object only.",
        "user": (
            "Repair this malformed JSON:\n"
            "```json\n"
            "{\n"
            '  "ready": true,\n'
            '  "overall_score": 8.1,\n'
            '  "issues": ["opener too broad"],\n'
            '  "repair_targets": [{"focus_key":"event_taxonomy", "path":"opener"}]\n'
            "```\n"
        ),
    },
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def _usage_dict(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        total = usage.get("total_tokens")
    else:
        prompt = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
        completion = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
        total = getattr(usage, "total_tokens", None)
    if total is None and prompt is not None and completion is not None:
        total = int(prompt) + int(completion)
    return {
        "prompt_tokens": int(prompt) if prompt is not None else None,
        "completion_tokens": int(completion) if completion is not None else None,
        "total_tokens": int(total) if total is not None else None,
    }


def _validate(prompt: dict[str, Any], raw: str) -> tuple[bool, list[str], str]:
    failures: list[str] = []
    parsed_type = ""
    if prompt.get("response_format"):
        parsed = _load_json_lenient(raw)
        parsed_type = type(parsed).__name__ if parsed is not None else "None"
        if not isinstance(parsed, dict):
            failures.append("not_json_object")
        elif prompt["name"] == "strict_json_small":
            if not str(parsed.get("question") or "").strip():
                failures.append("missing_question")
            dims = parsed.get("dimensions")
            if not isinstance(dims, list) or len(dims) != 3:
                failures.append("bad_dimensions")
        elif prompt["name"] == "json_repair_small":
            for key in ("ready", "overall_score", "issues", "repair_targets"):
                if key not in parsed:
                    failures.append(f"missing_{key}")
            if not isinstance(parsed.get("repair_targets"), list):
                failures.append("repair_targets_not_list")
    else:
        parsed_type = "text"
        text = raw.strip()
        if len(text.split()) < 18:
            failures.append("too_short")
        if not any(term in text.lower() for term in ("conversion", "trial", "denominator", "guardrail", "cohort")):
            failures.append("not_grounded")
    return not failures, failures, parsed_type


async def _call_once(
    client: AsyncOpenAI,
    *,
    model: str,
    prompt: dict[str, Any],
    repeat: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": prompt["max_tokens"],
        "messages": [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
    }
    if prompt.get("response_format"):
        payload["response_format"] = prompt["response_format"]

    started = time.perf_counter()
    try:
        response = await client.chat.completions.create(**payload)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        raw = (response.choices[0].message.content or "").strip()
        ok, failures, parsed_type = _validate(prompt, raw)
        return {
            "model": model,
            "prompt": prompt["name"],
            "repeat": repeat,
            "ok": ok,
            "failures": failures,
            "elapsed_ms": elapsed_ms,
            "raw_chars": len(raw),
            "parsed_type": parsed_type,
            "usage": _usage_dict(response),
            "preview": raw[:700],
        }
    except Exception as exc:
        return {
            "model": model,
            "prompt": prompt["name"],
            "repeat": repeat,
            "ok": False,
            "failures": [f"{type(exc).__name__}: {str(exc)[:240]}"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "raw_chars": 0,
            "parsed_type": "error",
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
            "preview": "",
        }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["model"], []).append(row)

    summary: dict[str, Any] = {}
    for model, items in groups.items():
        latencies = [float(item["elapsed_ms"]) for item in items]
        summary[model] = {
            "calls": len(items),
            "passed": sum(1 for item in items if item.get("ok")),
            "avg_ms": round(statistics.mean(latencies), 1) if latencies else 0,
            "median_ms": round(statistics.median(latencies), 1) if latencies else 0,
            "min_ms": round(min(latencies), 1) if latencies else 0,
            "p90_ms": round(_percentile(latencies, 0.9), 1),
            "max_ms": round(max(latencies), 1) if latencies else 0,
        }
        by_prompt: dict[str, Any] = {}
        for prompt_name in sorted({item["prompt"] for item in items}):
            prompt_items = [item for item in items if item["prompt"] == prompt_name]
            p_latencies = [float(item["elapsed_ms"]) for item in prompt_items]
            by_prompt[prompt_name] = {
                "calls": len(prompt_items),
                "passed": sum(1 for item in prompt_items if item.get("ok")),
                "avg_ms": round(statistics.mean(p_latencies), 1),
                "median_ms": round(statistics.median(p_latencies), 1),
                "min_ms": round(min(p_latencies), 1),
                "max_ms": round(max(p_latencies), 1),
            }
        summary[model]["by_prompt"] = by_prompt
    return summary


def _write_reports(rows: list[dict[str, Any]], summary: dict[str, Any], output_prefix: Path) -> None:
    json_path = output_prefix.with_suffix(".json")
    md_path = output_prefix.with_suffix(".md")
    json_path.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    lines = [
        "# DeepSeek Latency Probe",
        "",
        "Direct OpenRouter calls only. No Antigravity agents/orchestrator.",
        "",
        "## Summary",
        "",
        "| Model | Passed | Calls | Avg ms | Median ms | Min ms | P90 ms | Max ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, info in summary.items():
        lines.append(
            f"| `{model}` | {info['passed']} | {info['calls']} | {info['avg_ms']} | "
            f"{info['median_ms']} | {info['min_ms']} | {info['p90_ms']} | {info['max_ms']} |"
        )
    lines.extend(["", "## By Prompt", ""])
    for model, info in summary.items():
        lines.append(f"### `{model}`")
        lines.append("| Prompt | Passed | Calls | Avg ms | Median ms | Min ms | Max ms |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for prompt_name, prompt_info in info["by_prompt"].items():
            lines.append(
                f"| `{prompt_name}` | {prompt_info['passed']} | {prompt_info['calls']} | "
                f"{prompt_info['avg_ms']} | {prompt_info['median_ms']} | "
                f"{prompt_info['min_ms']} | {prompt_info['max_ms']} |"
            )
        lines.append("")
    lines.extend(["", f"JSON: `{json_path}`"])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[DeepSeekLatency] Wrote {json_path}")
    print(f"[DeepSeekLatency] Wrote {md_path}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=int(os.environ.get("DEEPSEEK_PROBE_REPEATS", "3")))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("DEEPSEEK_PROBE_TIMEOUT", "90")))
    parser.add_argument(
        "--output-prefix",
        default=os.environ.get("DEEPSEEK_PROBE_OUTPUT_PREFIX", "/tmp/antigravity_deepseek_latency_probe"),
    )
    args = parser.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        timeout=args.timeout,
    )

    rows: list[dict[str, Any]] = []
    for model in MODELS:
        for prompt in PROMPTS:
            for repeat in range(1, args.repeats + 1):
                print(f"[DeepSeekLatency] {model} :: {prompt['name']} repeat {repeat}/{args.repeats}", flush=True)
                row = await _call_once(client, model=model, prompt=prompt, repeat=repeat)
                rows.append(row)
                print(
                    f"  -> ok={row['ok']} elapsed={row['elapsed_ms']}ms failures={row['failures']}",
                    flush=True,
                )

    summary = _summarize(rows)
    _write_reports(rows, summary, Path(args.output_prefix))
    for model, info in summary.items():
        print(
            f"[DeepSeekLatency] {model}: {info['passed']}/{info['calls']} "
            f"avg={info['avg_ms']}ms median={info['median_ms']}ms p90={info['p90_ms']}ms",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
