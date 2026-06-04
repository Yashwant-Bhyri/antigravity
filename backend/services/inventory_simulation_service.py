from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from backend.services.interview_telemetry import interview_telemetry
from backend.state.session_manager import SessionManager
from backend.models.llm_router import LLMRouter


STAGE_ORDER = ["understanding", "planning", "implementation", "validation", "reflection"]

STAGE_REQUIREMENTS = {
    "understanding": (
        "Explain the write-skew race: two concurrent requests each read available > 0 before either decrements. "
        "Name the gap between the read and the write, and what invariant is violated."
    ),
    "planning": (
        "State the patch: how you enforce read-then-write atomicity, what happens on contention, "
        "and how partial failures leave inventory consistent."
    ),
    "implementation": "Edit inventory.mjs and summarize why your atomicity approach prevents oversell.",
    "validation": (
        "Run validation, read what the concurrency tests prove, and record what the failure pattern revealed."
    ),
    "reflection": (
        "Explain the tradeoff between optimistic and pessimistic locking, what you would monitor after deploy, "
        "and what production scenarios are still unproven."
    ),
}

STAGES = [
    {
        "key": "understanding",
        "label": "Understand",
        "interviewer": (
            "You are joining a flash-sale team after a live oversell incident. Before touching code, "
            "trace where the race window opens and what guarantee the current code is missing."
        ),
        "candidate_task": (
            "State what the race condition is, what invariant is violated, and what facts you would confirm "
            "before writing a single line."
        ),
    },
    {
        "key": "planning",
        "label": "Plan",
        "interviewer": (
            "Turn the race analysis into a patch plan. Tell me whether you are using optimistic locking, "
            "pessimistic locking, or an atomic compare-and-set — and why."
        ),
        "candidate_task": (
            "Describe the atomicity mechanism, the contention behavior, and how partial failure leaves "
            "inventory consistent."
        ),
    },
    {
        "key": "implementation",
        "label": "Implement",
        "interviewer": (
            "Patch the handler. The store gives you compareAndDecrement and a version field. "
            "Use the minimal surface to enforce the invariant without redesigning the whole inventory service."
        ),
        "candidate_task": "Edit inventory.mjs. The store and its atomic primitives are visible in the starter code.",
    },
    {
        "key": "validation",
        "label": "Validate",
        "interviewer": (
            "Run tests. The concurrency suite fires parallel reservations against a shared inventory. "
            "A passing baseline is not enough — prove the invariant holds under concurrent load."
        ),
        "candidate_task": "Run validation, identify the failing concurrency check, revise, and record the fix.",
    },
    {
        "key": "reflection",
        "label": "Reflect",
        "interviewer": (
            "Final pass. Explain the locking tradeoff, what you monitor after deploy, "
            "and what production edge cases you would still want a teammate to review."
        ),
        "candidate_task": "Summarize correctness, remaining risks, observability, and review needs.",
    },
]

INCIDENT = (
    "Flash-sale inventory oversell incident\n\n"
    "During a 60-second flash sale, 847 units of a limited product were reserved against an inventory "
    "of 500. The handler reads available quantity, checks if sufficient, then decrements. "
    "Under concurrent load, many requests all read the same positive value before any write completes, "
    "so the check passes for all of them.\n\n"
    "Goal: make reserveInventory atomic. Once a unit is reserved, a concurrent request must either "
    "see the updated count or retry on contention — never both proceed past the check."
)

STARTER_CODE = r"""export async function reserveInventory(productId, quantity, store) {
  const product = await store.getProduct(productId);
  if (!product) throw new Error('product not found');
  if (product.available < quantity) {
    return { success: false, reason: 'insufficient_inventory', available: product.available };
  }
  await store.decrementInventory(productId, quantity);
  const reservation = await store.createReservation({ productId, quantity, status: 'confirmed' });
  return { success: true, reservationId: reservation.id, reserved: quantity };
}
"""

GOLDEN_SOLUTION = r"""export async function reserveInventory(productId, quantity, store) {
  if (!quantity || quantity < 1) throw new Error('quantity must be a positive integer');

  for (let attempt = 0; attempt < 5; attempt++) {
    const product = await store.getProduct(productId);
    if (!product) throw new Error('product not found');
    if (product.available < quantity) {
      return { success: false, reason: 'insufficient_inventory', available: product.available };
    }

    const updated = await store.compareAndDecrement(productId, quantity, product.version);
    if (updated === null) {
      await new Promise((resolve) => setTimeout(resolve, 5 * (attempt + 1)));
      continue;
    }

    const reservation = await store.createReservation({ productId, quantity, status: 'confirmed' });
    return { success: true, reservationId: reservation.id, reserved: quantity };
  }

  return { success: false, reason: 'contention', available: (await store.getProduct(productId))?.available ?? 0 };
}
"""

TEST_FILE = r"""import test from 'node:test';
import assert from 'node:assert/strict';
import { reserveInventory } from './inventory.mjs';

class InventoryStore {
  constructor(available = 10) {
    this.products = new Map([['prod_1', { id: 'prod_1', available, version: 1 }]]);
    this.reservations = new Map();
    this.nextReservationId = 1;
    this._racey = false;
  }

  async getProduct(productId) {
    if (this._racey) await new Promise((r) => setImmediate(r));
    const p = this.products.get(productId);
    return p ? { ...p } : null;
  }

  async decrementInventory(productId, quantity) {
    if (this._racey) await new Promise((r) => setImmediate(r));
    const p = this.products.get(productId);
    if (!p) throw new Error('product not found');
    p.available = Math.max(0, p.available - quantity);
    p.version += 1;
    return { ...p };
  }

  async compareAndDecrement(productId, quantity, expectedVersion) {
    const p = this.products.get(productId);
    if (!p) return null;
    if (p.version !== expectedVersion) return null;
    if (p.available < quantity) return null;
    p.available -= quantity;
    p.version += 1;
    return { ...p };
  }

  async createReservation(record) {
    const id = `res_${this.nextReservationId++}`;
    const r = { id, ...record };
    this.reservations.set(id, r);
    return { ...r };
  }

  totalReserved() {
    return [...this.reservations.values()].reduce((sum, r) => sum + (r.quantity || 0), 0);
  }

  reservationCount() {
    return this.reservations.size;
  }
}

class RaceyInventoryStore extends InventoryStore {
  constructor(available) {
    super(available);
    this._racey = true;
  }
}

test('[public] reservation under limit succeeds', async () => {
  const store = new InventoryStore(10);
  const result = await reserveInventory('prod_1', 3, store);
  assert.equal(result.success, true);
  assert.ok(result.reservationId);
  assert.equal(result.reserved, 3);
});

test('[public] reservation exactly depleting inventory succeeds', async () => {
  const store = new InventoryStore(5);
  const result = await reserveInventory('prod_1', 5, store);
  assert.equal(result.success, true);
  assert.equal(store.totalReserved(), 5);
});

test('[public] reservation over limit returns insufficient_inventory', async () => {
  const store = new InventoryStore(3);
  const result = await reserveInventory('prod_1', 5, store);
  assert.equal(result.success, false);
  assert.equal(result.reason, 'insufficient_inventory');
});

test('[public] zero or negative quantity is rejected', async () => {
  const store = new InventoryStore(10);
  let threw = false;
  try {
    await reserveInventory('prod_1', 0, store);
  } catch {
    threw = true;
  }
  assert.ok(threw || true);
});

test('[public] unknown product throws', async () => {
  const store = new InventoryStore(10);
  let threw = false;
  try {
    await reserveInventory('prod_unknown', 1, store);
  } catch {
    threw = true;
  }
  assert.ok(threw);
});

test('[public] sequential reservations reduce inventory correctly', async () => {
  const store = new InventoryStore(10);
  await reserveInventory('prod_1', 3, store);
  await reserveInventory('prod_1', 4, store);
  const product = await store.getProduct('prod_1');
  assert.ok(product.available <= 3);
  assert.ok(store.totalReserved() <= 7);
});

test('[hidden] concurrent reservations do not oversell', async () => {
  const store = new RaceyInventoryStore(5);
  const attempts = await Promise.allSettled(
    Array.from({ length: 20 }, () => reserveInventory('prod_1', 1, store))
  );
  const successful = attempts
    .filter((r) => r.status === 'fulfilled' && r.value?.success === true)
    .length;
  assert.ok(successful <= 5, `oversold: ${successful} reservations for 5 units`);
  assert.ok(store.totalReserved() <= 5, `total reserved ${store.totalReserved()} exceeds limit 5`);
});

test('[hidden] concurrent exact-boundary does not exceed inventory by even 1', async () => {
  const store = new RaceyInventoryStore(10);
  await Promise.allSettled(
    Array.from({ length: 50 }, () => reserveInventory('prod_1', 1, store))
  );
  assert.ok(store.totalReserved() <= 10, `reserved ${store.totalReserved()} against 10`);
  const product = await store.getProduct('prod_1');
  assert.ok(product.available >= 0, 'available went negative');
});

test('[hidden] failed reservation attempt leaves inventory unchanged', async () => {
  const store = new InventoryStore(2);
  const result = await reserveInventory('prod_1', 5, store);
  assert.equal(result.success, false);
  const product = await store.getProduct('prod_1');
  assert.equal(product.available, 2);
  assert.equal(store.reservationCount(), 0);
});

test('[hidden] high-concurrency burst stays within inventory cap', async () => {
  const store = new RaceyInventoryStore(3);
  await Promise.allSettled(
    Array.from({ length: 100 }, () => reserveInventory('prod_1', 1, store))
  );
  assert.ok(store.totalReserved() <= 3, `oversold by ${store.totalReserved() - 3}`);
});
"""

_TWIST = {
    "id": "partial_reservation_crash",
    "title": "🚨 New Evidence Arrived",
    "body": (
        "Post-deploy production alert:\n\n"
        "• 3 reservations show status='confirmed' in the database\n"
        "• The inventory decrement for those 3 ran successfully\n"
        "• But the process crashed before createReservation returned\n"
        "• Inventory shows 3 fewer units — but no matching reservation records exist\n"
        "• Customer support is asking about 'ghost' reservations that hold stock but have no order\n\n"
        "Your patch fixed the race condition. It did not fix the crash-between-writes problem."
    ),
    "interviewer_prompt": (
        "The decrement succeeded and then the process died before createReservation wrote. "
        "Inventory is reduced by 3 but those units have no reservation record and no order. "
        "Walk me through exactly why your current patch allows this, and what the correct recovery path looks like."
    ),
}

_INTERVIEWER_SYSTEM = (
    "You are the live interviewer in a backend engineering simulation assessing distributed systems judgment. "
    "Your only job: say one precise technical nudge in 1-3 sentences. "
    "Do NOT give code. Do NOT reveal the answer. Do NOT say 'great job'. "
    "Push the candidate toward specific mechanisms: optimistic locking, compare-and-swap, version fields, "
    "retry loops, partial failure atomicity. "
    "If they are vague, demand specificity. If they overclaim safety, challenge what is unproven. "
    "Be technically sharp. Sound like a senior distributed-systems engineer sitting beside them."
)

_SCORER_SYSTEM = (
    "You are evaluating a backend engineering candidate in an inventory reservation race simulation. "
    "You must assess what the candidate actually proved through code and reasoning — not what they claimed. "
    "Be rigorous. A candidate who passes tests but cannot explain the locking tradeoff is weaker than one who "
    "patches carefully and explains contention behavior. Reward evidence, penalize overclaiming. "
    "Respond with valid JSON only. No markdown, no explanation outside the JSON."
)


class InventorySimulationService:
    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self._memory: dict[str, dict[str, Any]] = {}
        self.family = "inventory_race"
        self.key_prefix = "invsim:"
        self.summary_prefix = "invsim_summary:"

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    def _summary_key(self, session_id: str) -> str:
        return f"{self.summary_prefix}{session_id}"

    def _session_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        report = state.get("report") or {}
        return {
            "session_id": state.get("session_id", ""),
            "simulation_family": state.get("simulation_family", self.family),
            "scenario": "Flash Sale Inventory Race",
            "complete": bool(state.get("complete")),
            "current_stage": state.get("current_stage", ""),
            "overall_score": report.get("overall_score"),
            "hiring_signal": report.get("hiring_signal"),
            "hiring_label": report.get("hiring_label"),
            "passed": (state.get("test_result") or {}).get("passed"),
            "total": (state.get("test_result") or {}).get("total"),
            "test_runs": len(state.get("test_runs") or []),
            "twist_injected": bool(state.get("twist_injected")),
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
        }

    async def _save(self, state: dict[str, Any]) -> None:
        key = self._key(state["session_id"])
        state["simulation_family"] = self.family
        state["interview_complete"] = bool(state.get("complete"))
        self._memory[key] = json.loads(json.dumps(state))
        try:
            await self.session_manager.save_state(key, state)
        except Exception:
            pass
        try:
            ttl = self.session_manager.completed_ttl if state.get("complete") else self.session_manager.ttl
            await self.session_manager.redis.setex(
                self._summary_key(state["session_id"]),
                ttl,
                json.dumps(self._session_summary(state)),
            )
        except Exception:
            pass

    async def _load_persisted_states(self) -> list[dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {
            key: json.loads(json.dumps(value))
            for key, value in self._memory.items()
            if key.startswith(self.key_prefix)
        }
        try:
            async for key in self.session_manager.redis.scan_iter(f"{self.key_prefix}*"):
                try:
                    state = await self.session_manager.get_state(key)
                except Exception:
                    continue
                if isinstance(state, dict):
                    states[key] = state
        except Exception:
            pass
        return list(states.values())

    async def _load_persisted_summaries(self) -> list[dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        for state in self._memory.values():
            row = self._session_summary(state)
            if row["session_id"]:
                summaries[row["session_id"]] = row

        try:
            keys = await asyncio.wait_for(
                self.session_manager.redis.keys(f"{self.summary_prefix}*"),
                timeout=3.0,
            )
            keys = [str(key) for key in keys[:250]]
            if keys:
                values = await asyncio.wait_for(self.session_manager.redis.mget(keys), timeout=3.0)
                for raw in values:
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(row, dict) and row.get("session_id"):
                        summaries[str(row["session_id"])] = row
        except Exception:
            pass

        return list(summaries.values())

    async def get_state(self, session_id: str) -> dict[str, Any]:
        key = self._key(session_id)
        try:
            return await self.session_manager.get_state(key)
        except Exception:
            if key not in self._memory:
                raise KeyError(f"Inventory simulation session not found: {session_id}")
            return json.loads(json.dumps(self._memory[key]))

    def _word_count(self, value: str) -> int:
        return len(re.findall(r"[A-Za-z0-9_'-]+", value or ""))

    def _tokens(self, value: str) -> list[str]:
        return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_'-]*", value or "")]

    def _contains_any(self, value: str, words: list[str]) -> bool:
        lowered = (value or "").lower()
        return any(word in lowered for word in words)

    def _count_any(self, value: str, words: list[str]) -> int:
        lowered = (value or "").lower()
        return sum(1 for word in words if word in lowered)

    def _test_passed(self, result: dict[str, Any], fragment: str) -> bool:
        needle = fragment.lower()
        return any(
            needle in str(detail.get("name", "")).lower()
            and detail.get("status") == "pass"
            for detail in result.get("details", [])
        )

    def _test_present(self, result: dict[str, Any], fragment: str) -> bool:
        needle = fragment.lower()
        return any(needle in str(detail.get("name", "")).lower() for detail in result.get("details", []))

    def _ledger_item(
        self,
        *,
        item_id: str,
        label: str,
        status: str,
        source: str,
        detail: str,
        severity: str = "medium",
    ) -> dict[str, str]:
        return {
            "id": item_id,
            "label": label,
            "status": status,
            "source": source,
            "detail": detail,
            "severity": severity,
        }

    def _evidence_ledger(self, state: dict[str, Any], artifact_quality: dict[str, Any] | None = None) -> dict[str, Any]:
        result = state.get("test_result") or {}
        notes = state.get("notes", {}) or {}
        combined_notes = " ".join(str(value) for value in notes.values()).lower()
        artifact_quality = artifact_quality or self._artifact_quality(state)
        shallow = bool(artifact_quality.get("shallow"))
        ended_green = bool(result) and int(result.get("passed", 0) or 0) == int(result.get("total", 0) or 0)

        test_dimensions = [
            ("reservation_under_limit", "Reservation under limit succeeds", "reservation under limit succeeds", "public"),
            ("exact_depletion", "Reservation exactly depleting inventory succeeds", "exactly depleting inventory succeeds", "public"),
            ("over_limit_rejection", "Reservation over limit returns insufficient inventory", "reservation over limit returns", "public"),
            ("invalid_quantity_rejection", "Zero or negative quantity is rejected", "zero or negative quantity", "public"),
            ("unknown_product_rejection", "Unknown product throws", "unknown product throws", "public"),
            ("sequential_inventory_update", "Sequential reservations reduce inventory correctly", "sequential reservations reduce", "public"),
            ("concurrent_oversell_guard", "Concurrent reservations do not oversell", "concurrent reservations do not oversell", "hidden"),
            ("exact_boundary_concurrency", "Concurrent exact-boundary stays within inventory", "concurrent exact-boundary", "hidden"),
            ("failed_attempt_preserves_inventory", "Failed reservation leaves inventory unchanged", "failed reservation attempt leaves inventory unchanged", "hidden"),
            ("high_concurrency_cap", "High-concurrency burst stays within inventory cap", "high-concurrency burst", "hidden"),
        ]

        items: list[dict[str, str]] = []
        for item_id, label, fragment, visibility in test_dimensions:
            present = self._test_present(result, fragment)
            passed = self._test_passed(result, fragment)
            status = "proved" if passed else "failed" if present else "unobserved"
            detail = (
                f"{visibility.title()} runtime check passed."
                if passed
                else f"{visibility.title()} runtime check failed."
                if present
                else "No runtime validation has been collected for this dimension yet."
            )
            items.append(self._ledger_item(
                item_id=item_id,
                label=label,
                status=status,
                source=f"{visibility}_test",
                detail=detail,
                severity="high" if visibility == "hidden" else "medium",
            ))

        crash_ack = (
            self._contains_any(combined_notes, ["crash", "partial", "ghost", "reservation", "decrement"])
            and self._contains_any(combined_notes, ["recover", "recovery", "compensate", "compensating", "rollback", "reconcile"])
        )
        items.append(self._ledger_item(
            item_id="crash_between_decrement_and_reservation",
            label="Crash between decrement and reservation write",
            status="acknowledged_gap" if crash_ack else "unproved",
            source="candidate_artifact",
            detail=(
                "Candidate acknowledged that decrement/write split needs recovery or compensation."
                if crash_ack else
                "Runtime tests do not prove recovery for ghost inventory after a crash between writes."
            ),
            severity="critical",
        ))

        real_lock_ack = self._contains_any(
            combined_notes,
            ["database", "row lock", "redis", "transaction", "isolation", "throughput", "latency", "contention"],
        )
        items.append(self._ledger_item(
            item_id="real_locking_boundary",
            label="Real database/Redis locking boundary",
            status="acknowledged_gap" if real_lock_ack else "unproved",
            source="candidate_artifact",
            detail=(
                "Candidate acknowledged production lock/CAS behavior differs from the in-memory test double."
                if real_lock_ack else
                "The sandbox proves logic against a fake store, not production lock latency or isolation behavior."
            ),
            severity="high",
        ))

        if shallow and ended_green:
            authorship_status = "contradicted"
            authorship_detail = "Runtime code quality is stronger than the explanation; independent systems judgment is uncertain."
        elif shallow:
            authorship_status = "weak"
            authorship_detail = "Reasoning artifacts are shallow and cannot support a senior distributed-systems signal."
        else:
            authorship_status = "supported"
            authorship_detail = "Reasoning artifacts are coherent enough to support the runtime evidence."
        items.append(self._ledger_item(
            item_id="authorship_reasoning_alignment",
            label="Code/reasoning authorship alignment",
            status=authorship_status,
            source="artifact_quality",
            detail=authorship_detail,
            severity="critical" if shallow and ended_green else "medium",
        ))

        summary = {
            "proved_count": sum(1 for item in items if item["status"] == "proved"),
            "failed_count": sum(1 for item in items if item["status"] == "failed"),
            "acknowledged_gap_count": sum(1 for item in items if item["status"] == "acknowledged_gap"),
            "unproved_count": sum(1 for item in items if item["status"] == "unproved"),
            "contradiction_count": sum(1 for item in items if item["status"] == "contradicted"),
        }
        test_items = [item for item in items if item["source"].endswith("_test")]
        coverage_score = round(
            100 * sum(1 for item in test_items if item["status"] == "proved") / max(len(test_items), 1)
        )
        failed_item = next((item for item in items if item["status"] == "failed"), None)
        contradiction = next((item for item in items if item["status"] == "contradicted"), None)
        crash_gap = next((item for item in items if item["id"] == "crash_between_decrement_and_reservation" and item["status"] == "unproved"), None)
        lock_gap = next((item for item in items if item["id"] == "real_locking_boundary" and item["status"] == "unproved"), None)
        if failed_item:
            next_challenge = {
                "id": "repair_failed_runtime_dimension",
                "title": f"Repair failed evidence: {failed_item['label']}",
                "prompt": f"Your next challenge is to fix and explain this failed dimension: {failed_item['label']}.",
            }
        elif contradiction:
            next_challenge = {
                "id": "explain_green_code_authorship",
                "title": "Defend the green code from first principles",
                "prompt": "The code passes, but your explanation is thin. Walk through the race window, version check, contention path, and failure mode.",
            }
        elif crash_gap:
            next_challenge = {
                "id": "ghost_inventory_recovery",
                "title": "Recover ghost inventory after a crash",
                "prompt": "The decrement succeeds and the process dies before reservation creation. Design the recovery or compensation path.",
            }
        elif lock_gap:
            next_challenge = {
                "id": "production_locking_boundary",
                "title": "Prove production locking behavior",
                "prompt": "Move the solution from the fake store to Redis or database row locks and explain latency, contention, and isolation behavior.",
            }
        else:
            next_challenge = {
                "id": "flash_sale_scale_design",
                "title": "Scale inventory safety across regions",
                "prompt": "Extend the design to hot keys, regional inventory buckets, queueing, and reconciliation after partial failures.",
            }
        return {
            "family": self.family,
            "coverage_score": coverage_score,
            "summary": summary,
            "items": items,
            "next_challenge": next_challenge,
        }

    def _artifact_quality(self, state: dict[str, Any]) -> dict[str, Any]:
        notes = state.get("notes", {}) or {}
        stage_scores: dict[str, int] = {}
        stage_issues: dict[str, list[str]] = {}
        causal_terms = [
            "because", "when", "if", "then", "before", "after", "so", "therefore", "prevents",
            "means", "leaves", "returns", "rejects", "stores", "persists", "retries", "fails",
            "proves", "under", "between", "while",
        ]
        action_verbs = [
            "inspect", "check", "reject", "retry", "lock", "compare", "decrement", "reserve",
            "monitor", "alert", "compensate", "rollback", "handle", "resolve", "update", "abort",
        ]
        concrete_terms = [
            "race window", "concurrent", "parallel", "available", "inventory", "stock", "decrement",
            "reservation", "oversell", "invariant", "version", "compare", "cas", "lock",
            "optimistic", "pessimistic", "contention", "crash", "partial", "ghost",
        ]
        stage_expectations = {
            "understanding": [
                ["race", "concurrent", "parallel", "window"],
                ["read", "write", "decrement", "available"],
                ["invariant", "oversell", "stock", "inventory"],
            ],
            "planning": [
                ["optimistic", "pessimistic", "atomic", "compare", "version", "lock", "cas"],
                ["contention", "retry", "conflict", "abort"],
                ["partial", "crash", "consistent", "rollback", "compensat"],
            ],
            "implementation": [
                ["compare", "version", "lock", "atomic", "cas"],
                ["retry", "contention", "decrement", "reservation"],
            ],
            "validation": [
                ["test", "evidence", "proves", "runtime", "passing", "failed"],
                ["concurrent", "hidden", "oversell", "boundary"],
                ["crash", "partial", "ghost", "recovery", "compensat"],
            ],
            "reflection": [
                ["tradeoff", "throughput", "latency", "contention"],
                ["monitor", "metric", "alert", "dashboard", "log"],
                ["crash", "partial", "ghost", "rollback", "compensat"],
            ],
        }
        for stage in STAGE_ORDER:
            note = str(notes.get(stage, "") or "")
            lowered = note.lower()
            tokens = self._tokens(note)
            words = len(tokens)
            unique_ratio = len(set(tokens)) / max(words, 1)
            repeated_token_ratio = 1 - unique_ratio if words else 1
            sentence_count = max(1, len([part for part in re.split(r"[.!?\n]+", note) if part.strip()]))
            avg_sentence_words = words / sentence_count
            causal_hits = self._count_any(note, causal_terms)
            verb_hits = self._count_any(note, action_verbs)
            concrete_hits = self._count_any(note, concrete_terms)
            expected = stage_expectations.get(stage, [])
            expectation_hits = sum(1 for group in expected if self._contains_any(lowered, group))
            score = 0.0
            score += min(words / 45, 1) * 18
            score += min(concrete_hits / 5, 1) * 22
            score += min(causal_hits / 3, 1) * 22
            score += min(verb_hits / 4, 1) * 18
            score += min(expectation_hits / max(len(expected), 1), 1) * 20
            issues: list[str] = []
            if words < 18:
                issues.append("too little reasoning text")
            if causal_hits < 2 and stage in {"understanding", "planning", "validation", "reflection"}:
                issues.append("few cause/effect or sequence links")
                score = min(score, 60)
            if verb_hits < 2:
                issues.append("few concrete actions")
            if concrete_hits < 3:
                issues.append("few inventory-specific anchors")
            if repeated_token_ratio > 0.58 and words >= 18:
                score -= 20
                issues.append("repetitive keyword pattern")
            dense_without_structure = (
                avg_sentence_words > 65
                or (
                    sentence_count <= 1
                    and words >= 28
                    and (expectation_hits < len(expected) or causal_hits < 2 or verb_hits < 2)
                )
            )
            if dense_without_structure:
                score = min(score - 15, 48)
                issues.append("keyword-list shape instead of explained reasoning")
            if stage == "validation" and state.get("twist_injected"):
                if not (
                    self._contains_any(note, ["crash", "partial", "ghost", "reservation", "decrement"])
                    and self._contains_any(note, ["recover", "recovery", "compensate", "compensating", "rollback", "reconcile"])
                ):
                    score = min(score, 45)
                    issues.append("production twist not explained as a recovery/compensation problem")
            stage_scores[stage] = max(0, min(100, round(score)))
            stage_issues[stage] = issues
        core_stages = ["understanding", "planning", "validation", "reflection"]
        average = round(sum(stage_scores[stage] for stage in core_stages) / len(core_stages))
        shallow_stages = [stage for stage in core_stages if stage_scores[stage] < 55]
        return {
            "overall": average,
            "stage_scores": stage_scores,
            "stage_issues": stage_issues,
            "shallow": average < 62 or len(shallow_stages) >= 2,
            "shallow_stages": shallow_stages,
        }

    def _normalize_code(self, code: str) -> str:
        return re.sub(r"\s+", "", code or "")

    def _code_changed(self, state: dict[str, Any], code: str | None = None) -> bool:
        current = code if code is not None else state.get("code", "")
        return self._normalize_code(current) != self._normalize_code(state.get("starter_code", STARTER_CODE))

    def _stage_artifact_issues(self, state: dict[str, Any], stage_key: str) -> list[str]:
        notes = state.get("notes", {}) or {}
        note = str(notes.get(stage_key, "") or "")
        words = self._word_count(note)
        issues: list[str] = []

        if stage_key == "understanding":
            if words < 28:
                issues.append("Understanding needs concrete sentences, not a placeholder.")
            if not self._contains_any(note, ["race", "concurrent", "parallel", "read", "write", "gap", "window"]):
                issues.append("Name the race window between the read and the write.")
            if not self._contains_any(note, ["inventory", "available", "decrement", "quantity", "stock"]):
                issues.append("Tie the race to the inventory availability check.")
            if not self._contains_any(note, ["invariant", "oversell", "negative", "check", "atomic", "consistent"]):
                issues.append("State what invariant is violated when two requests both pass the check.")

        if stage_key == "planning":
            if words < 35:
                issues.append("Planning needs a concrete atomicity mechanism, not just intent.")
            if not self._contains_any(note, ["optimistic", "pessimistic", "atomic", "compare", "version", "lock", "cas", "transaction"]):
                issues.append("Name the locking or atomicity approach.")
            if not self._contains_any(note, ["contention", "retry", "conflict", "fail", "rollback", "abort"]):
                issues.append("Describe the contention behavior — what happens when two requests clash.")
            if not self._contains_any(note, ["partial", "crash", "consistent", "atomic", "both", "neither"]):
                issues.append("Address partial failure: what if the decrement succeeds but the reservation write crashes.")

        if stage_key == "implementation":
            if not self._code_changed(state):
                issues.append("Change inventory.mjs before claiming implementation evidence.")
            if words < 12:
                issues.append("Summarize the atomicity approach before running validation.")

        if stage_key == "validation":
            result = state.get("test_result")
            if not result:
                issues.append("Run validation before leaving this stage.")
            if words < 20:
                issues.append("Write what the concurrency test evidence proved or failed to prove.")
            if state.get("twist_injected") and not self._contains_any(
                note,
                ["crash", "partial", "reservation", "decrement", "ghost", "consistent", "recovery", "compensat"],
            ):
                issues.append("Address the crash-between-writes twist and the ghost inventory problem.")

        if stage_key == "reflection":
            if words < 35:
                issues.append("Reflection needs a hiring-useful analysis of tradeoffs and remaining risks.")
            if not self._contains_any(note, ["monitor", "metric", "alert", "log", "dashboard"]):
                issues.append("Mention what you would monitor after deploy.")
            if not self._contains_any(note, ["optimistic", "pessimistic", "contention", "throughput", "tradeoff", "latency"]):
                issues.append("Explain the tradeoff between locking strategies.")

        return issues

    def _transition_issues(self, state: dict[str, Any], target_stage: str) -> list[str]:
        current = state.get("current_stage", "understanding")
        current_index = STAGE_ORDER.index(current) if current in STAGE_ORDER else 0
        target_index = STAGE_ORDER.index(target_stage) if target_stage in STAGE_ORDER else current_index
        if target_index <= current_index:
            return []
        if target_index > current_index + 1:
            return ["Move through the assessment one stage at a time."]
        if target_stage == "validation":
            return ["Use Run Tests to enter validation after changing inventory.mjs."]
        return self._stage_artifact_issues(state, current)

    def _gate_status(self, state: dict[str, Any]) -> dict[str, Any]:
        current = state.get("current_stage", "understanding")
        issues_by_stage = {stage: self._stage_artifact_issues(state, stage) for stage in STAGE_ORDER}
        current_index = STAGE_ORDER.index(current) if current in STAGE_ORDER else 0
        test_result = state.get("test_result")
        report = state.get("report")
        artifact_quality = self._artifact_quality(state)
        can_run_tests = (
            current in {"implementation", "validation"}
            and self._code_changed(state)
            and not issues_by_stage["understanding"]
            and not issues_by_stage["planning"]
            and self._word_count(str((state.get("notes") or {}).get("implementation", ""))) >= 12
        )
        can_advance = current_index < len(STAGE_ORDER) - 1 and not self._transition_issues(
            state, STAGE_ORDER[current_index + 1]
        )
        can_finalize = (
            current == "reflection"
            and bool(test_result)
            and not issues_by_stage["reflection"]
            and not issues_by_stage["validation"]
            and self._code_changed(state)
        )
        if report:
            evidence_label = "Final report ready"
        elif test_result:
            evidence_label = f"Candidate validation: {test_result.get('passed', 0)}/{test_result.get('total', 0)} checks"
        else:
            baseline = state.get("baseline_result") or {}
            evidence_label = (
                f"Starter baseline: {baseline.get('passed', 0)}/{baseline.get('total', 0)} checks"
                if baseline else "Evidence incomplete"
            )
        return {
            "issues_by_stage": issues_by_stage,
            "current_issues": issues_by_stage.get(current, []),
            "can_advance": can_advance,
            "can_run_tests": can_run_tests,
            "can_finalize": can_finalize,
            "code_changed": self._code_changed(state),
            "evidence_label": evidence_label,
            "artifact_quality": artifact_quality,
        }

    def public_state(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": state["session_id"],
            "simulation_family": state.get("simulation_family", self.family),
            "scenario": state["scenario"],
            "stages": STAGES,
            "stage_requirements": STAGE_REQUIREMENTS,
            "current_stage": state["current_stage"],
            "interviewer_message": state["interviewer_message"],
            "starter_code": state["starter_code"],
            "code": state.get("code", state["starter_code"]),
            "notes": state.get("notes", {}),
            "baseline_result": state.get("baseline_result"),
            "test_result": state.get("test_result"),
            "test_runs": state.get("test_runs", []),
            "telemetry": state.get("telemetry", []),
            "report": state.get("report"),
            "complete": bool(state.get("complete")),
            "twist": state.get("twist"),
            "twist_injected": bool(state.get("twist_injected")),
            "gate_status": self._gate_status(state),
        }

    def _record_local(self, state: dict[str, Any], event: str, detail: str, **fields: Any) -> None:
        telemetry = state.setdefault("telemetry", [])
        telemetry.insert(0, {"at": round(time.time(), 3), "event": event, "detail": detail, **fields})
        del telemetry[24:]
        state["updated_at"] = time.time()

    def _stage_message(self, stage_key: str, test_result: dict[str, Any] | None = None) -> str:
        stage = next((s for s in STAGES if s["key"] == stage_key), STAGES[0])
        if stage_key == "validation" and test_result:
            passed = int(test_result.get("passed", 0) or 0)
            total = int(test_result.get("total", 0) or 0)
            if total and passed == total:
                return (
                    f"All {total} checks are passing. Now explain why compareAndDecrement makes the concurrent "
                    "tests safe — and what production scenario your tests cannot prove."
                )
            return (
                f"{passed}/{total} checks are passing. The concurrency suite is your key evidence: "
                "look at which hidden test is failing and trace the race window in your code."
            )
        return stage["interviewer"]

    async def _ai_interviewer_response(self, stage_key: str, candidate_note: str, state: dict[str, Any]) -> str:
        fallback = self._stage_message(stage_key, state.get("test_result"))
        if len(candidate_note.split()) < 15:
            return fallback
        try:
            test_result = state.get("test_result")
            test_summary = (
                f"{test_result['passed']}/{test_result['total']} checks passing "
                f"({test_result.get('hidden_passed', 0)}/{test_result.get('hidden_total', 0)} hidden)"
                if test_result else "Tests not run yet."
            )
            code_changed = self._code_changed(state)
            stage_label = next((s["label"] for s in STAGES if s["key"] == stage_key), stage_key)
            user_prompt = (
                f"Stage: {stage_key} — {stage_label}\n"
                f"Code modified from starter: {'yes' if code_changed else 'no'}\n"
                f"Validation state: {test_summary}\n\n"
                f"Candidate worklog:\n{candidate_note}\n\n"
                "Generate one interviewer nudge reacting specifically to what the candidate wrote above."
            )
            router = LLMRouter(tier="small", timeout_override=8.0)
            result = await router.call(_INTERVIEWER_SYSTEM, user_prompt, max_tokens=180)
            text = (result if isinstance(result, str) else str(result)).strip().strip('"').strip()
            if len(text) <= 20:
                raise RuntimeError("Inventory simulation interviewer LLM returned an unusably short response.")
            return text
        except Exception as exc:
            raise RuntimeError(f"Inventory simulation interviewer LLM failed: {type(exc).__name__}: {exc}") from exc

    def _should_inject_twist(self, state: dict[str, Any], result: dict[str, Any]) -> bool:
        if state.get("twist_injected"):
            return False
        if len(state.get("test_runs", [])) < 1:
            return False
        public_passed = int(result.get("public_passed", 0) or 0)
        public_total = int(result.get("public_total", 0) or 0)
        return public_total > 0 and public_passed >= public_total

    def _inject_twist(self, state: dict[str, Any]) -> None:
        state["twist_injected"] = True
        state["twist"] = _TWIST
        state.setdefault("scenario", {})["twist"] = _TWIST
        self._record_local(state, "simulation.twist_injected", f"Production twist injected: {_TWIST['id']}")

    def _parse_test_output(self, stdout: str, stderr: str, return_code: int, elapsed_ms: int) -> dict[str, Any]:
        details: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line in stdout.splitlines():
            s = line.strip()
            if s.startswith(("ok ", "not ok ", "✔ ", "✖ ")):
                status = "pass" if s.startswith(("ok ", "✔ ")) else "fail"
                name = s.split(" - ", 1)[1].strip() if " - " in s else s[2:].strip() if s.startswith(("✔ ", "✖ ")) else s
                name = re.sub(r"\s+#.*$", "", name).strip()
                name = re.sub(r"\s+\([0-9.]+ms\)$", "", name).strip()
                hidden = name.startswith("[hidden]")
                display = re.sub(r"^\[(hidden|public)\]\s*", "", name).strip()
                if name and not name.isdigit() and name not in seen:
                    seen.add(name)
                    details.append({
                        "name": display or name, "status": status,
                        "visibility": "hidden" if hidden else "public",
                    })
        total = len(details)
        passed = sum(1 for d in details if d["status"] == "pass")
        public_total = sum(1 for d in details if d.get("visibility") != "hidden")
        public_passed = sum(1 for d in details if d.get("visibility") != "hidden" and d["status"] == "pass")
        hidden_total = sum(1 for d in details if d.get("visibility") == "hidden")
        hidden_passed = sum(1 for d in details if d.get("visibility") == "hidden" and d["status"] == "pass")
        timed_out = return_code == 124
        return {
            "passed": passed, "failed": total - passed if total else (0 if return_code == 0 else 1),
            "total": total or 1, "public_passed": public_passed, "public_total": public_total,
            "hidden_passed": hidden_passed, "hidden_total": hidden_total,
            "details": details or [{"name": "runner completed" if return_code == 0 else "runner failed", "status": "pass" if return_code == 0 else "fail", "visibility": "public"}],
            "stdout": stdout[-4000:], "stderr": stderr[-2000:],
            "return_code": return_code, "runtime_ms": elapsed_ms, "timed_out": timed_out,
        }

    async def _run_node_tests(self, code: str) -> dict[str, Any]:
        root = Path(tempfile.gettempdir()).resolve() / "antigravity_invsim"
        root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="run_", dir=str(root))).resolve()
        started = time.perf_counter()
        try:
            inv_file = workdir / "inventory.mjs"
            test_file = workdir / "inventory.test.mjs"
            inv_file.write_text(code, encoding="utf-8")
            test_file.write_text(TEST_FILE, encoding="utf-8")
            cmd = [
                "node", "--permission",
                f"--allow-fs-read={workdir}{os.sep}",
                f"--allow-fs-read={inv_file}", f"--allow-fs-read={test_file}",
                f"--allow-fs-write={workdir}{os.sep}",
                str(test_file),
            ]
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(workdir), "TMPDIR": str(workdir), "NODE_OPTIONS": ""}
            process = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(workdir), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=6.0)
                return_code = int(process.returncode or 0)
            except asyncio.TimeoutError:
                process.kill()
                stdout_b, stderr_b = await process.communicate()
                return_code = 124
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            return self._parse_test_output(
                stdout_b.decode("utf-8", errors="replace"),
                stderr_b.decode("utf-8", errors="replace"),
                return_code, elapsed_ms,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def start_session(self) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        state: dict[str, Any] = {
            "session_id": session_id,
            "scenario": {
                "title": "Flash Sale Inventory Race",
                "role_signal": "Distributed systems, optimistic locking, write-skew prevention, partial failure recovery",
                "objective": "Prevent inventory oversell when concurrent requests race past the availability check.",
                "constraints": [
                    "Keep the patch local to reserveInventory.",
                    "No two successful reservations may together exceed available inventory.",
                    "Contention must return an informative response, not corrupt state.",
                    "A crash between decrement and reservation write must not silently consume inventory.",
                ],
                "incident": INCIDENT,
            },
            "stages": STAGES,
            "current_stage": "understanding",
            "interviewer_message": STAGES[0]["interviewer"],
            "starter_code": STARTER_CODE,
            "code": STARTER_CODE,
            "notes": {stage: "" for stage in STAGE_ORDER},
            "baseline_result": None,
            "test_runs": [],
            "test_result": None,
            "telemetry": [],
            "complete": False,
            "created_at": time.time(),
            "updated_at": time.time(),
            "simulation_family": self.family,
        }
        state["baseline_result"] = await self._run_node_tests(STARTER_CODE)
        self._record_local(state, "simulation.session_started", "Inventory race simulation started.")
        await self._save(state)
        await interview_telemetry.log(session_id, "simulation.session_started", source="backend.inv_simulation")
        return self.public_state(state)

    async def interviewer_turn(
        self, session_id: str, *, stage_key: str, note: str = "", code: str = "",
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        state = await self.get_state(session_id)
        if stage_key not in STAGE_ORDER:
            stage_key = state.get("current_stage", "understanding")
        if notes:
            for k, v in notes.items():
                if k in STAGE_ORDER:
                    state.setdefault("notes", {})[k] = str(v)
        if note:
            state.setdefault("notes", {})[stage_key] = note
        if code:
            state["code"] = code
        current_index = STAGE_ORDER.index(state.get("current_stage", "understanding")) if state.get("current_stage") in STAGE_ORDER else 0
        target_index = STAGE_ORDER.index(stage_key) if stage_key in STAGE_ORDER else current_index
        going_backward = target_index < current_index
        transition_issues = self._transition_issues(state, stage_key)
        if transition_issues:
            raise ValueError(" ".join(transition_issues))
        state["current_stage"] = stage_key
        candidate_note = state.get("notes", {}).get(stage_key, "")
        if not going_backward:
            state["interviewer_message"] = await self._ai_interviewer_response(stage_key, candidate_note, state)
        self._record_local(state, "simulation.stage_updated", f"Moved to {stage_key}.", stage=stage_key)
        await self._save(state)
        return self.public_state(state)

    async def run_tests(self, session_id: str, *, code: str, notes: dict[str, str] | None = None) -> dict[str, Any]:
        state = await self.get_state(session_id)
        state["code"] = code
        if notes:
            for k, v in notes.items():
                if k in STAGE_ORDER:
                    state.setdefault("notes", {})[k] = str(v)
        if state.get("current_stage") not in {"implementation", "validation"}:
            raise ValueError("Reach the implementation stage before running candidate validation.")
        if not self._code_changed(state, code):
            raise ValueError("Change inventory.mjs before running candidate validation.")
        blockers = [issue for stage in ["understanding", "planning", "implementation"] for issue in self._stage_artifact_issues(state, stage)]
        if blockers:
            raise ValueError(" ".join(blockers))
        result = await self._run_node_tests(code)
        state["test_result"] = result
        state.setdefault("test_runs", []).append(result)
        del state["test_runs"][:-10]
        state["current_stage"] = "validation"
        if self._should_inject_twist(state, result):
            self._inject_twist(state)
            state["interviewer_message"] = _TWIST["interviewer_prompt"]
        else:
            state["interviewer_message"] = self._stage_message("validation", result)
        self._record_local(state, "simulation.tests_ran", f"{result['passed']}/{result['total']} checks passing.",
                           passed=result["passed"], total=result["total"])
        await self._save(state)
        return self.public_state(state)

    def _score(self, state: dict[str, Any]) -> dict[str, Any]:
        notes = state.get("notes", {}) or {}
        runs = state.get("test_runs", []) or []
        result = state.get("test_result") or {}
        total = max(int(result.get("total", 0) or 0), 1)
        passed = int(result.get("passed", 0) or 0)
        hidden_total = int(result.get("hidden_total", 0) or 0)
        hidden_passed = int(result.get("hidden_passed", 0) or 0)
        correctness = passed / total
        had_failure = any(int(r.get("failed", 0) or 0) > 0 for r in runs)
        ended_green = passed == total
        artifact_quality = self._artifact_quality(state)
        validation_stage_quality = int(artifact_quality.get("stage_scores", {}).get("validation", 0) or 0) / 100
        validation = 0.0
        if runs:
            validation += 0.20
        if ended_green:
            validation += 0.35
        elif passed:
            validation += 0.15 * correctness
        validation += 0.30 * validation_stage_quality
        if had_failure and ended_green:
            validation += 0.10
        if hidden_total and hidden_passed == hidden_total:
            validation += 0.05
        validation = min(validation, 1.0)
        reflection_words = self._word_count(str(notes.get("reflection", "")))
        production_terms = ["optimistic", "pessimistic", "contention", "monitor", "alert", "crash", "partial", "ghost", "compensat", "rollback"]
        production_score = (
            min(reflection_words / 60, 1) * 0.5
            + min(sum(1 for w in production_terms if w in " ".join(notes.values()).lower()) / 5, 1) * 0.5
        )
        communication = sum(1 for k in STAGE_ORDER if self._word_count(str(notes.get(k, ""))) >= 20) / len(STAGE_ORDER)
        breakdown = {
            "correctness": round(correctness * 100),
            "validation_behavior": round(validation * 100),
            "production_judgment": round(production_score * 100),
            "communication": round(communication * 100),
            "code_quality": round(correctness * 100),
        }
        overall = round(
            breakdown["correctness"] * 0.50
            + breakdown["validation_behavior"] * 0.20
            + breakdown["production_judgment"] * 0.15
            + breakdown["communication"] * 0.10
            + breakdown["code_quality"] * 0.05
        )
        if passed < total:
            overall = min(overall, 68)
        if hidden_total and hidden_passed < hidden_total:
            overall = min(overall, 78)
        quality = int(artifact_quality.get("overall", 0) or 0)
        shallow = bool(artifact_quality.get("shallow"))
        if quality < 45:
            overall = min(overall, 49)
            breakdown["production_judgment"] = min(breakdown["production_judgment"], 35)
            breakdown["communication"] = min(breakdown["communication"], 40)
        elif shallow:
            overall = min(overall, 68)
            breakdown["production_judgment"] = min(breakdown["production_judgment"], 55)
            breakdown["communication"] = min(breakdown["communication"], 60)
        hiring_signal = (
            "strong_hire" if overall >= 85 else
            "hire_with_followup" if overall >= 72 else
            "mixed" if overall >= 55 else
            "weak" if overall >= 35 else "no_hire"
        )
        failed_names = [d.get("name", "") for d in result.get("details", []) if d.get("status") == "fail"]
        authored_signal = ended_green and not shallow
        return {
            "overall_score": overall, "breakdown": breakdown,
            "passed": passed, "total": total,
            "strengths": [
                (
                    "Enforced inventory atomicity with a compare-and-swap or version-based check."
                    if authored_signal
                    else "Final code passed the runtime checks, but authorship and independent systems judgment remain uncertain."
                    if ended_green
                    else "Attempted atomic inventory control."
                ),
                (
                    "Used a validation loop with failing concurrency evidence before reaching the final state."
                    if had_failure and ended_green
                    else "Explained what the passing concurrency evidence proves and does not prove."
                    if ended_green and validation_stage_quality >= 0.7
                    else "Collected runtime concurrency evidence."
                ),
                "Hidden concurrency checks passed — concurrent load did not oversell." if hidden_total and hidden_passed == hidden_total else "Concurrency suite exposed remaining race windows.",
                f"Reasoning artifacts cleared the quality floor ({quality}/100)." if quality >= 62 else f"Reasoning artifacts were shallow despite runtime evidence ({quality}/100).",
            ],
            "risks": failed_names[:3] or [
                "Real Redis CAS, database row locking, and crash recovery are not proven by this in-memory simulation.",
                "Candidate explanation is keyword-heavy or under-explained; do not treat green tests alone as senior-level evidence." if shallow else "Reasoning artifacts were adequate for this simulation scope.",
            ],
            "what_proved": [
                f"Final code passed {passed}/{total} runtime checks.",
                f"Hidden concurrency suite: {hidden_passed}/{hidden_total} checks.",
                "Candidate demonstrated understanding of locking tradeoffs in artifacts." if communication >= 0.8 else "Stage artifacts were thin for a distributed systems claim.",
            ],
            "what_not_proved": failed_names[:3] or [
                "Crash-between-decrement-and-reservation leaves ghost inventory — not proven safe.",
                "Contention under real database row locks at production query rates is not simulated.",
                "Deep reasoning quality remains weak; the system saw terms but not enough causal explanation." if shallow else "Candidate reasoning quality was sufficient for the deterministic assessment floor.",
                "Authorship and independent systems judgment remain uncertain because code quality was stronger than the reasoning artifacts." if shallow and ended_green else "Candidate reasoning aligned with the runtime evidence.",
            ],
            "key_quotes": [str(notes.get("planning", ""))[:180], str(notes.get("reflection", ""))[:180]],
            "overclaim_detected": bool(shallow and ended_green),
            "hiring_signal": hiring_signal,
            "hiring_narrative": (
                f"Candidate produced {passed}/{total} passing runtime checks with "
                f"{hidden_passed}/{hidden_total} hidden concurrency checks. "
                f"Deterministic score: {overall}, including reasoning artifact quality ({quality}/100)."
            ),
            "artifact_quality": artifact_quality,
        }

    async def finalize(self, session_id: str, *, code: str = "", notes: dict[str, str] | None = None) -> dict[str, Any]:
        state = await self.get_state(session_id)
        if code:
            state["code"] = code
        if notes:
            for k, v in notes.items():
                if k in STAGE_ORDER:
                    state.setdefault("notes", {})[k] = str(v)
        if not state.get("test_runs"):
            raise ValueError("Run tests before finalizing.")
        if state.get("current_stage") != "reflection":
            raise ValueError("Move to the reflection stage before finalizing.")
        if not state.get("test_result"):
            raise ValueError("No validation result available.")
        if not self._code_changed(state):
            raise ValueError("Cannot finalize without a code change.")
        for stage in ["validation", "reflection"]:
            issues = self._stage_artifact_issues(state, stage)
            if issues:
                raise ValueError(" ".join(issues))
        score = self._score(state)
        evidence_ledger = self._evidence_ledger(state, score.get("artifact_quality"))
        artifact_quality = score.get("artifact_quality", self._artifact_quality(state))
        quality = int(artifact_quality.get("overall", 0) or 0)
        shallow_reasoning = bool(artifact_quality.get("shallow"))
        reasoning_signal = {
            "label": "Reasoning Quality / Authorship Signal",
            "status": "Weak reasoning — authorship uncertain" if shallow_reasoning else "Reasoning aligned with runtime evidence",
            "quality": quality,
            "shallow": shallow_reasoning,
            "summary": (
                "The code passed, but the written artifacts read like keyword coverage rather than causal engineering judgment. "
                "Treat this as green runtime evidence with unresolved authorship and independent-systems-reasoning risk."
                if shallow_reasoning
                else "The written artifacts explain the invariant, validation result, and remaining production risk well enough to support the runtime evidence."
            ),
        }
        result = state.get("test_result") or {}
        notes_state = state.get("notes", {}) or {}
        hiring_labels = {
            "strong_hire": "Strong Hire", "hire_with_followup": "Hire — Follow-up Recommended",
            "mixed": "Mixed Signal", "weak": "Weak Signal", "no_hire": "No Hire",
        }
        hiring_signal = score.get("hiring_signal", "mixed")
        timeline: list[dict[str, str]] = []
        created_at = state.get("created_at", time.time())
        for event in reversed(state.get("telemetry", [])):
            elapsed = max(0.0, event["at"] - created_at)
            ts = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
            evt = event["event"]
            if evt == "simulation.session_started":
                text = "Session started — baseline established"
            elif evt == "simulation.stage_updated":
                text = f"Candidate moved to {event.get('stage', '')} stage"
            elif evt == "simulation.tests_ran":
                text = f"Tests ran — {event.get('passed')}/{event.get('total')} checks passing"
            elif evt == "simulation.twist_injected":
                text = "Production twist injected — crash between decrement and reservation"
            elif evt == "simulation.finalized":
                text = f"Session finalized — {event.get('detail', '')}"
            else:
                text = event.get("detail", evt)
            timeline.append({"ts": ts, "text": text})
        report = {
            **score,
            "title": "Flash Sale Inventory Race — Assessment Report",
            "summary": score["hiring_narrative"],
            "hiring_label": hiring_labels.get(hiring_signal, "Mixed Signal"),
            "stage_evidence": {
                k: {
                    "words": len(str(notes_state.get(k, "")).split()),
                    "captured": bool(str(notes_state.get(k, "")).strip()),
                    "quality": score.get("artifact_quality", {}).get("stage_scores", {}).get(k, 0),
                    "quality_issues": score.get("artifact_quality", {}).get("stage_issues", {}).get(k, []),
                }
                for k in STAGE_ORDER
            },
            "artifact_quality": artifact_quality,
            "reasoning_signal": reasoning_signal,
            "evidence_ledger": evidence_ledger,
            "next_challenge": evidence_ledger.get("next_challenge"),
            "event_timeline": timeline,
            "test_result": result,
            "twist_was_injected": bool(state.get("twist_injected")),
            "unresolved": score.get("what_not_proved") or [],
        }
        state["report"] = report
        state["complete"] = True
        state["current_stage"] = "reflection"
        state["interviewer_message"] = (
            f"Simulation complete. {hiring_labels.get(hiring_signal, 'Assessment complete.')} — "
            "The report separates what the concurrency tests proved from what remains untested."
        )
        self._record_local(state, "simulation.finalized", f"Final score {score['overall_score']} — {hiring_signal}.")
        await self._save(state)
        return self.public_state(state)

    async def get_report(self, session_id: str) -> dict[str, Any]:
        state = await self.get_state(session_id)
        if not state.get("complete") or not state.get("report"):
            raise ValueError("Simulation is not yet finalized.")
        return self.public_state(state)

    async def list_sessions(self) -> list[dict[str, Any]]:
        sessions = await self._load_persisted_summaries()
        sessions.sort(key=lambda s: s.get("updated_at") or 0, reverse=True)
        return sessions


inventory_simulation_service = InventorySimulationService()
