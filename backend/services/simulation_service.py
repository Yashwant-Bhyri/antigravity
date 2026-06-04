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
        "Explain the duplicate-charge risk using concrete system words: retry/client operation, gateway/charge, "
        "and persisted payment state."
    ),
    "planning": (
        "State the patch invariants: idempotency key, conflict handling, pending/completed reuse, and gateway "
        "failure recovery."
    ),
    "implementation": "Change payment.mjs and summarize the implementation choice before running validation.",
    "validation": (
        "Run validation and write what the failing or passing evidence proves. If the production twist appears, "
        "address webhook/reconciliation risk explicitly."
    ),
    "reflection": "Explain tradeoffs, monitoring, reconciliation, and remaining production risks before finalizing.",
}

STAGES = [
    {
        "key": "understanding",
        "label": "Understand",
        "interviewer": (
            "You are joining a checkout team mid-incident. Before touching code, build the mental model: "
            "where can duplicate money movement happen, and what facts would you inspect first?"
        ),
        "candidate_task": (
            "State your clarifying questions, assumptions, and the risk you think this endpoint currently carries."
        ),
    },
    {
        "key": "planning",
        "label": "Plan",
        "interviewer": (
            "Turn that mental model into a patch plan. I want the order of operations, the invariants, and the "
            "failure cases you will prove before you call it safe."
        ),
        "candidate_task": (
            "Describe the smallest safe patch and the validation evidence you expect to collect."
        ),
    },
    {
        "key": "implementation",
        "label": "Implement",
        "interviewer": (
            "Patch the handler now. Keep the surface small: solve idempotency, conflict detection, and gateway "
            "failure recovery without redesigning the whole payment service."
        ),
        "candidate_task": "Edit payment.mjs. You can use the store and gateway APIs visible in the starter code.",
    },
    {
        "key": "validation",
        "label": "Validate",
        "interviewer": (
            "Run the tests and treat failures as signal. I care about whether you can prove safety, not whether "
            "the first patch is lucky."
        ),
        "candidate_task": "Run validation, inspect failed checks, revise the patch, and record what changed.",
    },
    {
        "key": "reflection",
        "label": "Reflect",
        "interviewer": (
            "Final pass. Explain the tradeoff you made, what you would monitor after deploy, and what you would "
            "ask a teammate to review."
        ),
        "candidate_task": "Summarize correctness, remaining risks, observability, and review needs.",
    },
]

INCIDENT = (
    "Checkout duplicate-charge incident\n\n"
    "Customers sometimes retry POST /payments after a mobile timeout. The current handler creates a new "
    "payment row, calls the gateway, then marks it completed. Under retries, two gateway charges can be "
    "created for the same client operation.\n\n"
    "Goal: make the endpoint idempotent. A repeated request with the same idempotency key should return "
    "the original result or safely continue the pending attempt."
)

STARTER_CODE = """export async function createPayment(input, store, gateway) {
  const payment = await store.insert({
    userId: input.userId,
    amountCents: input.amountCents,
    currency: input.currency,
    status: "created",
  });

  const charge = await gateway.charge({
    amountCents: input.amountCents,
    currency: input.currency,
    reference: payment.id,
  });

  await store.update(payment.id, {
    status: "completed",
    gatewayChargeId: charge.id,
  });

  return { paymentId: payment.id, status: "completed" };
}
"""


GOLDEN_SOLUTION = """export async function createPayment(input, store, gateway) {
  if (!input.idempotencyKey) {
    throw new Error("idempotency key required");
  }

  const resolveExisting = async (existing) => {
    if (existing.userId !== input.userId || existing.amountCents !== input.amountCents || existing.currency !== input.currency) {
      throw new Error("idempotency conflict");
    }
    if (existing.status === "completed") {
      return { paymentId: existing.id, status: "completed", gatewayChargeId: existing.gatewayChargeId };
    }
    if (existing.status === "pending" && existing.gatewayChargeId) {
      return { paymentId: existing.id, status: "pending", gatewayChargeId: existing.gatewayChargeId };
    }
    if (existing.status === "failed") {
      return { paymentId: existing.id, status: "failed_recoverable" };
    }
    return { paymentId: existing.id, status: "pending" };
  };

  const existing = await store.findByIdempotencyKey(input.idempotencyKey);
  if (existing) return resolveExisting(existing);

  let payment;
  try {
    payment = await store.insert({
      userId: input.userId,
      amountCents: input.amountCents,
      currency: input.currency,
      idempotencyKey: input.idempotencyKey,
      status: "pending",
    });
  } catch (error) {
    if (error?.code !== "UNIQUE_CONSTRAINT") throw error;
    const raced = await store.findByIdempotencyKey(input.idempotencyKey);
    if (!raced) throw error;
    return resolveExisting(raced);
  }

  try {
    const charge = await gateway.charge({
      amountCents: input.amountCents,
      currency: input.currency,
      reference: payment.id,
      idempotencyKey: input.idempotencyKey,
    });
    await store.update(payment.id, {
      status: "completed",
      gatewayChargeId: charge.id,
    });
    return { paymentId: payment.id, status: "completed", gatewayChargeId: charge.id };
  } catch (error) {
    await store.update(payment.id, { status: "failed", failureReason: String(error.message || error) });
    throw error;
  }
}
"""


TEST_FILE = r"""import test from 'node:test';
import assert from 'node:assert/strict';
import { createPayment } from './payment.mjs';

class PaymentStore {
  constructor() {
    this.payments = new Map();
    this.byKey = new Map();
    this.nextId = 1;
  }

  async insert(record) {
    if (record.idempotencyKey && this.byKey.has(record.idempotencyKey)) {
      const error = new Error('duplicate idempotency key');
      error.code = 'UNIQUE_CONSTRAINT';
      throw error;
    }
    const payment = { id: `pay_${this.nextId++}`, ...record };
    this.payments.set(payment.id, payment);
    if (payment.idempotencyKey) this.byKey.set(payment.idempotencyKey, payment.id);
    return { ...payment };
  }

  async update(id, patch) {
    const current = this.payments.get(id);
    if (!current) throw new Error(`missing payment ${id}`);
    const next = { ...current, ...patch };
    this.payments.set(id, next);
    if (next.idempotencyKey) this.byKey.set(next.idempotencyKey, id);
    return { ...next };
  }

  async findByIdempotencyKey(key) {
    const id = this.byKey.get(key);
    if (!id) return null;
    return { ...this.payments.get(id) };
  }

  async getByIdempotencyKey(key) {
    return this.findByIdempotencyKey(key);
  }

  countByIdempotencyKey(key) {
    return [...this.payments.values()].filter((payment) => payment.idempotencyKey === key).length;
  }

  all() {
    return [...this.payments.values()].map((payment) => ({ ...payment }));
  }
}

class Gateway {
  constructor() {
    this.charges = [];
    this.failNext = false;
    this.delayMs = 0;
  }

  async charge(payload) {
    if (this.delayMs) await new Promise((resolve) => setTimeout(resolve, this.delayMs));
    if (this.failNext) {
      this.failNext = false;
      throw new Error('gateway timeout');
    }
    const charge = { id: `ch_${this.charges.length + 1}`, ...payload };
    this.charges.push(charge);
    return charge;
  }
}

const baseInput = (overrides = {}) => ({
  userId: 'user_1',
  amountCents: 4200,
  currency: 'USD',
  idempotencyKey: 'idem_1',
  ...overrides,
});

class RaceyPaymentStore extends PaymentStore {
  async findByIdempotencyKey(key) {
    await new Promise((resolve) => setTimeout(resolve, 4));
    return super.findByIdempotencyKey(key);
  }
}

test('[public] missing idempotency key is rejected without a gateway charge', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  let rejected = false;
  try {
    const result = await createPayment(baseInput({ idempotencyKey: undefined }), store, gateway);
    rejected = ['rejected', 'invalid', 'failed'].includes(String(result?.status || '').toLowerCase());
  } catch {
    rejected = true;
  }
  assert.equal(gateway.charges.length, 0);
  assert.equal(rejected, true);
});

test('[public] first request creates exactly one completed charge', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  const result = await createPayment(baseInput(), store, gateway);
  const stored = await store.findByIdempotencyKey('idem_1');
  assert.equal(gateway.charges.length, 1);
  assert.equal(stored?.status, 'completed');
  assert.equal(stored?.gatewayChargeId, 'ch_1');
  assert.equal(result?.status, 'completed');
});

test('[public] duplicate completed request returns the original attempt without a second charge', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  const first = await createPayment(baseInput(), store, gateway);
  const second = await createPayment(baseInput(), store, gateway);
  assert.equal(gateway.charges.length, 1);
  assert.equal(store.countByIdempotencyKey('idem_1'), 1);
  if (first?.paymentId && second?.paymentId) assert.equal(second.paymentId, first.paymentId);
});

test('[public] duplicate pending request reuses the existing pending attempt', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  await store.insert({
    userId: 'user_1',
    amountCents: 4200,
    currency: 'USD',
    idempotencyKey: 'pending_key',
    status: 'pending',
  });
  await createPayment(baseInput({ idempotencyKey: 'pending_key' }), store, gateway).catch(() => {});
  assert.equal(store.countByIdempotencyKey('pending_key'), 1);
  assert.ok(gateway.charges.length <= 1);
});

test('[public] same idempotency key with different amount or currency is rejected as conflict', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  await createPayment(baseInput(), store, gateway);
  let conflicted = false;
  try {
    const result = await createPayment(baseInput({ amountCents: 9900 }), store, gateway);
    conflicted = ['conflict', 'rejected', 'invalid', 'failed'].includes(String(result?.status || '').toLowerCase());
  } catch {
    conflicted = true;
  }
  assert.equal(conflicted, true);
  assert.equal(gateway.charges.length, 1);
  assert.equal(store.countByIdempotencyKey('idem_1'), 1);
});

test('[public] gateway timeout leaves a recoverable non-completed state', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  gateway.failNext = true;
  let completed = false;
  try {
    const result = await createPayment(baseInput({ idempotencyKey: 'fail_key' }), store, gateway);
    completed = String(result?.status || '').toLowerCase() === 'completed';
  } catch {
    completed = false;
  }
  const stored = await store.findByIdempotencyKey('fail_key');
  assert.notEqual(completed, true);
  assert.notEqual(stored?.status, 'completed');
});

test('[hidden] concurrent duplicate retries collapse to one payment and one gateway charge', async () => {
  const store = new RaceyPaymentStore();
  const gateway = new Gateway();
  gateway.delayMs = 8;
  const attempts = await Promise.allSettled(
    Array.from({ length: 12 }, () => createPayment(baseInput({ idempotencyKey: 'race_key' }), store, gateway))
  );
  assert.equal(store.countByIdempotencyKey('race_key'), 1);
  assert.equal(gateway.charges.length, 1);
  assert.equal(attempts.some((attempt) => attempt.status === 'fulfilled'), true);
});

test('[hidden] same idempotency key cannot be reused by a different user', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  await createPayment(baseInput({ idempotencyKey: 'cross_user_key', userId: 'user_1' }), store, gateway);
  let conflicted = false;
  try {
    await createPayment(baseInput({ idempotencyKey: 'cross_user_key', userId: 'user_2' }), store, gateway);
  } catch {
    conflicted = true;
  }
  assert.equal(conflicted, true);
  assert.equal(gateway.charges.length, 1);
  assert.equal(store.countByIdempotencyKey('cross_user_key'), 1);
});

test('[hidden] gateway receives the client operation id as an idempotency key', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  await createPayment(baseInput({ idempotencyKey: 'gateway_key' }), store, gateway);
  assert.equal(gateway.charges.length, 1);
  assert.equal(gateway.charges[0]?.idempotencyKey, 'gateway_key');
});

test('[hidden] retry after recoverable gateway failure does not blindly create a second charge', async () => {
  const store = new PaymentStore();
  const gateway = new Gateway();
  gateway.failNext = true;
  await createPayment(baseInput({ idempotencyKey: 'recoverable_key' }), store, gateway).catch(() => {});
  await createPayment(baseInput({ idempotencyKey: 'recoverable_key' }), store, gateway).catch(() => {});
  assert.equal(store.countByIdempotencyKey('recoverable_key'), 1);
  assert.equal(gateway.charges.length, 0);
  const stored = await store.findByIdempotencyKey('recoverable_key');
  assert.notEqual(stored?.status, 'completed');
});
"""


class SimulationService:
    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self._memory: dict[str, dict[str, Any]] = {}
        self.family = "payment_retry_safety"
        self.key_prefix = "sim:"
        self.summary_prefix = "sim_summary:"

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    def _summary_key(self, session_id: str) -> str:
        return f"{self.summary_prefix}{session_id}"

    def _session_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        report = state.get("report") or {}
        return {
            "session_id": state.get("session_id", ""),
            "simulation_family": state.get("simulation_family", self.family),
            "scenario": (state.get("scenario") or {}).get("title", "Unknown"),
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
                raise KeyError(f"Simulation session not found: {session_id}")
            return json.loads(json.dumps(self._memory[key]))

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

    async def start_session(self) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        state = {
            "session_id": session_id,
            "scenario": {
                "title": "Payment Retry Safety",
                "role_signal": "Backend reliability, idempotency, failure recovery",
                "objective": "Prevent duplicate gateway charges under client retries and gateway timeouts.",
                "constraints": [
                    "Keep the patch local to createPayment.",
                    "A repeated idempotency key must not create a second charge.",
                    "Conflicting payloads for the same key must be rejected.",
                    "Gateway failure must leave a recoverable state.",
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
        self._record_local(state, "simulation.session_started", "Payment retry safety simulation started.")
        await self._save(state)
        await interview_telemetry.log(session_id, "simulation.session_started", source="backend.simulation")
        return self.public_state(state)

    def _record_local(self, state: dict[str, Any], event: str, detail: str, **fields: Any) -> None:
        telemetry = state.setdefault("telemetry", [])
        telemetry.insert(0, {
            "at": round(time.time(), 3),
            "event": event,
            "detail": detail,
            **fields,
        })
        del telemetry[24:]
        state["updated_at"] = time.time()

    def _normalize_code(self, code: str) -> str:
        return re.sub(r"\s+", "", code or "")

    def _code_changed(self, state: dict[str, Any], code: str | None = None) -> bool:
        current = code if code is not None else state.get("code", "")
        return self._normalize_code(current) != self._normalize_code(state.get("starter_code", STARTER_CODE))

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
            ("missing_key_rejection", "Missing idempotency key is rejected", "missing idempotency key", "public"),
            ("first_charge_completion", "First request creates one completed charge", "first request creates exactly one completed charge", "public"),
            ("duplicate_completed_reuse", "Duplicate completed request reuses original result", "duplicate completed request returns the original attempt", "public"),
            ("pending_attempt_reuse", "Duplicate pending request is safely reused", "duplicate pending request reuses", "public"),
            ("payload_conflict_rejection", "Same key with different payload is rejected", "different amount or currency is rejected", "public"),
            ("gateway_timeout_recoverable", "Gateway timeout leaves recoverable non-completed state", "gateway timeout leaves a recoverable", "public"),
            ("concurrent_retry_collapse", "Concurrent duplicate retries collapse to one charge", "concurrent duplicate retries collapse", "hidden"),
            ("cross_user_conflict", "Idempotency key cannot cross users", "different user", "hidden"),
            ("gateway_idempotency_propagation", "Gateway receives operation id as idempotency key", "gateway receives the client operation id", "hidden"),
            ("recoverable_retry_guard", "Recoverable retry does not blindly create a second charge", "recoverable gateway failure does not blindly create", "hidden"),
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

        webhook_ack = (
            self._contains_any(combined_notes, ["webhook", "charge.succeeded", "original"])
            and self._contains_any(combined_notes, ["reconcile", "reconciliation", "refund", "state machine"])
        )
        items.append(self._ledger_item(
            item_id="webhook_reconciliation",
            label="Delayed gateway success/webhook reconciliation",
            status="acknowledged_gap" if webhook_ack else "unproved",
            source="candidate_artifact",
            detail=(
                "Candidate explicitly acknowledged that delayed gateway success needs reconciliation/refund handling."
                if webhook_ack else
                "Runtime tests do not prove the delayed webhook success path, and the candidate did not adequately account for it."
            ),
            severity="critical",
        ))

        transaction_ack = self._contains_any(
            combined_notes,
            ["transaction", "atomic", "crash", "boundary", "recovery", "outbox", "reconcile"],
        )
        items.append(self._ledger_item(
            item_id="db_transaction_boundary",
            label="Real database transaction/crash boundary",
            status="acknowledged_gap" if transaction_ack else "unproved",
            source="candidate_artifact",
            detail=(
                "Candidate acknowledged that the in-memory store does not prove a production transaction boundary."
                if transaction_ack else
                "The sandbox simulates persistence; it does not prove production database crash behavior."
            ),
            severity="high",
        ))

        if shallow and ended_green:
            authorship_status = "contradicted"
            authorship_detail = "Runtime code quality is stronger than the explanation; independent authorship/judgment is uncertain."
        elif shallow:
            authorship_status = "weak"
            authorship_detail = "Reasoning artifacts are shallow and cannot support a senior signal."
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
        webhook_gap = next((item for item in items if item["id"] == "webhook_reconciliation" and item["status"] == "unproved"), None)
        transaction_gap = next((item for item in items if item["id"] == "db_transaction_boundary" and item["status"] == "unproved"), None)
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
                "prompt": "The code passes, but your explanation is thin. Walk through the invariant and each safety branch without reading the code.",
            }
        elif webhook_gap:
            next_challenge = {
                "id": "delayed_webhook_reconciliation",
                "title": "Handle delayed gateway success",
                "prompt": "A timed-out gateway call later emits charge.succeeded after a retry already completed. Design the reconciliation and refund/void path.",
            }
        elif transaction_gap:
            next_challenge = {
                "id": "production_transaction_boundary",
                "title": "Prove the production transaction boundary",
                "prompt": "Show how the handler survives a crash between local persistence and the gateway call in a real database-backed service.",
            }
        else:
            next_challenge = {
                "id": "scale_idempotency_retention",
                "title": "Scale idempotency beyond the handler",
                "prompt": "Extend the design to idempotency-key retention, replay windows, audit trails, and multi-region gateway behavior.",
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
            "means", "leaves", "returns", "rejects", "stores", "persists", "reuses", "marks",
            "fails", "proves", "under", "between",
        ]
        action_verbs = [
            "inspect", "check", "reject", "reuse", "persist", "store", "pass", "mark", "monitor",
            "alert", "reconcile", "refund", "handle", "resolve", "insert", "update", "compare",
        ]
        concrete_terms = [
            "idempotency key", "client operation", "payment row", "status", "gateway charge id",
            "gateway", "charge", "pending", "completed", "failed", "timeout", "conflict",
            "amount", "currency", "webhook", "reconciliation", "refund", "duplicate", "unique",
        ]
        stage_expectations = {
            "understanding": [
                ["retry", "timeout", "client operation", "duplicate"],
                ["gateway", "charge", "money"],
                ["row", "record", "status", "persist", "inspect"],
            ],
            "planning": [
                ["before", "after", "first", "then", "sequence", "order"],
                ["reject", "conflict", "amount", "currency"],
                ["pending", "completed", "reuse", "existing"],
                ["gateway", "timeout", "recoverable", "failure"],
            ],
            "implementation": [
                ["changed", "insert", "resolve", "unique", "store", "pass"],
                ["pending", "idempotency", "gateway", "recoverable"],
            ],
            "validation": [
                ["test", "evidence", "proves", "failed", "passing", "runtime"],
                ["duplicate", "conflict", "timeout", "concurrent", "hidden"],
                ["webhook", "reconcile", "reconciliation", "original", "refund"],
            ],
            "reflection": [
                ["tradeoff", "complexity", "risk", "remaining"],
                ["monitor", "metric", "alert", "dashboard", "log"],
                ["webhook", "reconcile", "reconciliation", "refund", "crash", "timeout"],
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
            expectation_hits = sum(
                1 for group in stage_expectations.get(stage, []) if self._contains_any(lowered, group)
            )

            score = 0
            score += min(words / 45, 1) * 18
            score += min(concrete_hits / 5, 1) * 22
            score += min(causal_hits / 3, 1) * 22
            score += min(verb_hits / 4, 1) * 18
            score += min(expectation_hits / max(len(stage_expectations.get(stage, [])), 1), 1) * 20

            issues: list[str] = []
            if words < 18:
                issues.append("too little reasoning text")
            if causal_hits < 2 and stage in {"understanding", "planning", "validation", "reflection"}:
                issues.append("few cause/effect or sequence links")
                score = min(score, 60)
            if verb_hits < 2:
                issues.append("few concrete actions")
            if concrete_hits < 3:
                issues.append("few payment-specific anchors")
            if repeated_token_ratio > 0.58 and words >= 18:
                score -= 20
                issues.append("repetitive keyword pattern")
            dense_without_structure = (
                avg_sentence_words > 65
                or (
                    sentence_count <= 1
                    and words >= 28
                    and (
                        expectation_hits < len(stage_expectations.get(stage, []))
                        or causal_hits < 2
                        or verb_hits < 2
                    )
                )
            )
            if dense_without_structure:
                score = min(score - 15, 48)
                issues.append("keyword-list shape instead of explained reasoning")
            if stage == "validation" and state.get("twist_injected"):
                if not (
                    self._contains_any(note, ["webhook", "charge.succeeded", "original"])
                    and self._contains_any(note, ["reconcile", "reconciliation", "refund", "state machine"])
                ):
                    score = min(score, 45)
                    issues.append("production twist not explained as a reconciliation problem")

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

    def _stage_artifact_issues(self, state: dict[str, Any], stage_key: str) -> list[str]:
        notes = state.get("notes", {}) or {}
        note = str(notes.get(stage_key, "") or "")
        words = self._word_count(note)
        issues: list[str] = []

        if stage_key == "understanding":
            if words < 28:
                issues.append("Give me a concrete incident read before we move on; a placeholder is not enough to assess.")
            if not self._contains_any(note, ["retry", "timeout", "duplicate", "client operation", "idempotency"]):
                issues.append("Call out the retry/idempotency failure mode explicitly.")
            if not self._contains_any(note, ["gateway", "charge", "money", "payment"]):
                issues.append("Connect the bug to money movement through the gateway.")
            if not self._contains_any(note, ["state", "row", "persist", "record", "status", "inspect"]):
                issues.append("Name the persisted state you would inspect: row, status, charge id, or record history.")

        if stage_key == "planning":
            if words < 35:
                issues.append("Before coding, lay out the patch sequence and the invariants it protects.")
            if not self._contains_any(note, ["idempotency", "idempotency key", "key"]):
                issues.append("State the idempotency-key invariant.")
            if not self._contains_any(note, ["conflict", "same key", "different amount", "currency"]):
                issues.append("Tell me how same-key payload conflicts are handled.")
            if not self._contains_any(note, ["pending", "completed", "reuse", "existing"]):
                issues.append("Explain how existing pending or completed attempts are reused.")
            if not self._contains_any(note, ["failure", "timeout", "recoverable", "gateway"]):
                issues.append("Define the gateway timeout/failure recovery behavior.")

        if stage_key == "implementation":
            if not self._code_changed(state):
                issues.append("Change payment.mjs before claiming implementation evidence.")
            if words < 12:
                issues.append("Summarize the implementation choice before validation.")

        if stage_key == "validation":
            result = state.get("test_result")
            if not result:
                issues.append("Run the tests before we leave validation.")
            if words < 20:
                issues.append("Tell me what the test result proves and what it still does not prove.")
            if state.get("twist_injected") and not self._contains_any(
                note,
                ["webhook", "reconcile", "reconciliation", "refund", "original", "timeout", "charge.succeeded"],
            ):
                issues.append("Address the timeout-then-webhook twist as a reconciliation problem.")

        if stage_key == "reflection":
            if words < 35:
                issues.append("Give me the production-risk read a hiring panel could actually use.")
            if not self._contains_any(note, ["monitor", "metric", "alert", "dashboard", "log"]):
                issues.append("Name what you would monitor after deploy.")
            if not self._contains_any(note, ["reconcile", "webhook", "refund", "crash", "remaining", "risk"]):
                issues.append("Name the remaining production risks or reconciliation gaps.")

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
            return ["Use Run Tests to enter validation after changing payment.mjs."]
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
            state,
            STAGE_ORDER[current_index + 1],
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
            if baseline:
                evidence_label = f"Starter baseline: {baseline.get('passed', 0)}/{baseline.get('total', 0)} checks"
            else:
                evidence_label = "Evidence incomplete"
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

    _INTERVIEWER_SYSTEM = (
        "You are the live interviewer in a backend engineering simulation assessing payment reliability judgment. "
        "Your only job: say one precise technical nudge in 1-3 sentences. "
        "Do NOT give code. Do NOT reveal the answer. Do NOT say 'great job'. "
        "Push the candidate toward specific mechanisms, failure modes, or test evidence. "
        "If they are vague, demand specificity. If they overclaim safety, challenge what is unproven. "
        "If they are stuck, hint at the next useful observation — not the solution. "
        "Be technically sharp. Sound like a senior payments engineer sitting beside them."
    )

    _TWIST = {
        "id": "gateway_timeout_webhook",
        "title": "🚨 New Evidence Arrived",
        "body": (
            "Production alert — 8 minutes ago:\n\n"
            "• gateway.charge() returned a network timeout for payment attempt pay_a7f3\n"
            "• Your endpoint marked that payment status='failed' and returned an error to the client\n"
            "• Mobile client retried — your patched endpoint handled the retry and created a new charge\n"
            "• A charge.succeeded webhook just arrived for the *original* timed-out request\n"
            "• Gateway shows: two charges exist for the same user operation\n"
            "• Customer just filed a duplicate-charge complaint\n\n"
            "Your current patch did not prevent this. Why not, and what is the safest recovery path?"
        ),
        "interviewer_prompt": (
            "A charge.succeeded webhook just arrived for a payment your code marked as 'failed' after a timeout. "
            "The retry already created a second gateway charge. "
            "Your patch handled the duplicate-request case — but not the gateway-timeout-then-webhook case. "
            "Walk me through exactly what your code does when it receives this webhook, and what the correct state machine should look like."
        ),
    }

    def _stage_message(self, stage_key: str, test_result: dict[str, Any] | None = None) -> str:
        stage = next((item for item in STAGES if item["key"] == stage_key), STAGES[0])
        if stage_key == "validation" and test_result:
            passed = int(test_result.get("passed", 0) or 0)
            total = int(test_result.get("total", 0) or 0)
            if total and passed == total:
                return (
                    f"All {total} checks are passing. Now do the senior-engineer part: explain why these tests prove "
                    "idempotency, and what production signal you would still monitor."
                )
            return (
                f"{passed}/{total} checks are passing. Pick the highest-signal failure first and revise from the "
                "failure mode, not from guesswork."
            )
        return stage["interviewer"]

    async def _ai_interviewer_response(
        self,
        stage_key: str,
        candidate_note: str,
        state: dict[str, Any],
    ) -> str:
        fallback = self._stage_message(stage_key, state.get("test_result"))
        note_words = len(candidate_note.split()) if candidate_note else 0
        if note_words < 15:
            return fallback
        try:
            test_result = state.get("test_result")
            test_summary = (
                f"{test_result['passed']}/{test_result['total']} checks passing "
                f"({test_result.get('hidden_passed', 0)}/{test_result.get('hidden_total', 0)} hidden)"
                if test_result else "Tests not run yet."
            )
            starter = state.get("starter_code", "")
            current_code = state.get("code", "")
            code_changed = current_code.strip() != starter.strip()
            stage_label = next((s["label"] for s in STAGES if s["key"] == stage_key), stage_key)
            user_prompt = (
                f"Stage: {stage_key} — {stage_label}\n"
                f"Code modified from starter: {'yes' if code_changed else 'no'}\n"
                f"Validation state: {test_summary}\n\n"
                f"Candidate worklog for this stage:\n{candidate_note}\n\n"
                "Generate one interviewer nudge reacting specifically to what the candidate wrote above."
            )
            router = LLMRouter(tier="small", timeout_override=8.0)
            result = await router.call(self._INTERVIEWER_SYSTEM, user_prompt, max_tokens=180)
            text = result if isinstance(result, str) else str(result)
            text = text.strip().strip('"').strip()
            if len(text) <= 20:
                raise RuntimeError("Simulation interviewer LLM returned an unusably short response.")
            return text
        except Exception as exc:
            raise RuntimeError(f"Simulation interviewer LLM failed: {type(exc).__name__}: {exc}") from exc

    def _should_inject_twist(self, state: dict[str, Any], result: dict[str, Any]) -> bool:
        if state.get("twist_injected"):
            return False
        runs = state.get("test_runs", [])
        if len(runs) < 1:
            return False
        public_passed = int(result.get("public_passed", 0) or 0)
        public_total = int(result.get("public_total", 0) or 0)
        return public_total > 0 and public_passed >= public_total

    def _inject_twist(self, state: dict[str, Any]) -> None:
        twist = self._TWIST
        state["twist_injected"] = True
        state["twist"] = twist
        state.setdefault("scenario", {})["twist"] = twist
        self._record_local(state, "simulation.twist_injected", f"Production twist injected: {twist['id']}")

    async def interviewer_turn(
        self,
        session_id: str,
        *,
        stage_key: str,
        note: str = "",
        code: str = "",
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        state = await self.get_state(session_id)
        if stage_key not in STAGE_ORDER:
            stage_key = state.get("current_stage", "understanding")
        if notes:
            for key, value in notes.items():
                if key in STAGE_ORDER:
                    state.setdefault("notes", {})[key] = str(value)
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
        # When going backward, keep the existing interviewer_message for that stage (already in state from first visit)
        self._record_local(state, "simulation.stage_updated", f"Moved to {stage_key}.", stage=stage_key)
        await self._save(state)
        await interview_telemetry.log(session_id, "simulation.stage_updated", source="backend.simulation", stage=stage_key)
        return self.public_state(state)

    def _parse_test_output(self, stdout: str, stderr: str, return_code: int, elapsed_ms: int) -> dict[str, Any]:
        details: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for line in stdout.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith("ok ")
                or stripped.startswith("not ok ")
                or stripped.startswith("✔ ")
                or stripped.startswith("✖ ")
            ):
                status = "pass" if stripped.startswith(("ok ", "✔ ")) else "fail"
                name = stripped
                if " - " in stripped:
                    name = stripped.split(" - ", 1)[1].strip()
                if stripped.startswith(("✔ ", "✖ ")):
                    name = stripped[2:].strip()
                name = re.sub(r"\s+#.*$", "", name).strip()
                name = re.sub(r"\s+\([0-9.]+ms\)$", "", name).strip()
                hidden = name.startswith("[hidden]")
                public = name.startswith("[public]")
                display_name = re.sub(r"^\[(hidden|public)\]\s*", "", name).strip()
                if name and not name.isdigit() and name != "failing tests:" and name not in seen_names:
                    seen_names.add(name)
                    details.append({
                        "name": display_name or name,
                        "status": status,
                        "visibility": "hidden" if hidden else "public" if public else "public",
                    })

        total = len(details)
        passed = sum(1 for item in details if item["status"] == "pass")
        failed = sum(1 for item in details if item["status"] == "fail")
        public_total = sum(1 for item in details if item.get("visibility") != "hidden")
        public_passed = sum(1 for item in details if item.get("visibility") != "hidden" and item["status"] == "pass")
        hidden_total = sum(1 for item in details if item.get("visibility") == "hidden")
        hidden_passed = sum(1 for item in details if item.get("visibility") == "hidden" and item["status"] == "pass")
        timed_out = return_code == 124
        return {
            "passed": passed,
            "failed": failed if total else (1 if return_code else 0),
            "total": total or 1,
            "public_passed": public_passed,
            "public_total": public_total,
            "hidden_passed": hidden_passed,
            "hidden_total": hidden_total,
            "details": details or [{
                "name": "runner completed" if return_code == 0 else "runner failed before tests completed",
                "status": "pass" if return_code == 0 else "fail",
                "visibility": "public",
            }],
            "stdout": stdout[-4000:],
            "stderr": stderr[-2000:],
            "return_code": return_code,
            "runtime_ms": elapsed_ms,
            "timed_out": timed_out,
        }

    async def _run_node_tests(self, code: str) -> dict[str, Any]:
        root = Path(tempfile.gettempdir()).resolve() / "antigravity_sim"
        root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="run_", dir=str(root))).resolve()
        started = time.perf_counter()
        try:
            payment_file = workdir / "payment.mjs"
            test_file = workdir / "payment.test.mjs"
            payment_file.write_text(code, encoding="utf-8")
            test_file.write_text(TEST_FILE, encoding="utf-8")

            cmd = [
                "node",
                "--permission",
                f"--allow-fs-read={workdir}{os.sep}",
                f"--allow-fs-read={payment_file}",
                f"--allow-fs-read={test_file}",
                f"--allow-fs-write={workdir}{os.sep}",
                str(test_file),
            ]
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(workdir),
                "TMPDIR": str(workdir),
                "NODE_OPTIONS": "",
            }
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=4.0)
                return_code = int(process.returncode or 0)
            except asyncio.TimeoutError:
                process.kill()
                stdout_b, stderr_b = await process.communicate()
                return_code = 124
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            return self._parse_test_output(
                stdout_b.decode("utf-8", errors="replace"),
                stderr_b.decode("utf-8", errors="replace"),
                return_code,
                elapsed_ms,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def run_tests(
        self,
        session_id: str,
        *,
        code: str,
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        state = await self.get_state(session_id)
        state["code"] = code
        if notes:
            for key, value in notes.items():
                if key in STAGE_ORDER:
                    state.setdefault("notes", {})[key] = str(value)
        if state.get("current_stage") not in {"implementation", "validation"}:
            raise ValueError("Reach the implementation stage before running candidate validation.")
        if not self._code_changed(state, code):
            raise ValueError("Change payment.mjs before running candidate validation. The starter baseline is not candidate signal.")
        blocker_stages = ["understanding", "planning", "implementation"]
        blockers = [issue for stage in blocker_stages for issue in self._stage_artifact_issues(state, stage)]
        if blockers:
            raise ValueError(" ".join(blockers))
        result = await self._run_node_tests(code)
        state["test_result"] = result
        state.setdefault("test_runs", []).append(result)
        del state["test_runs"][:-10]
        state["current_stage"] = "validation"

        if self._should_inject_twist(state, result):
            self._inject_twist(state)
            state["interviewer_message"] = self._TWIST["interviewer_prompt"]
        else:
            state["interviewer_message"] = self._stage_message("validation", result)

        self._record_local(
            state,
            "simulation.tests_ran",
            f"{result['passed']}/{result['total']} checks passing.",
            passed=result["passed"],
            total=result["total"],
        )
        await self._save(state)
        await interview_telemetry.log(
            session_id,
            "simulation.tests_ran",
            source="backend.simulation",
            passed=result["passed"],
            total=result["total"],
            failed=result["failed"],
            runtime_ms=result["runtime_ms"],
            timed_out=result["timed_out"],
        )
        return self.public_state(state)

    def _score_baseline(self, state: dict[str, Any]) -> dict[str, Any]:
        notes = state.get("notes", {}) or {}
        runs = state.get("test_runs", []) or []
        result = state.get("test_result") or {}
        total = max(int(result.get("total", 0) or 0), 1)
        passed = int(result.get("passed", 0) or 0)
        hidden_total = int(result.get("hidden_total", 0) or 0)
        hidden_passed = int(result.get("hidden_passed", 0) or 0)
        correctness = passed / total
        had_failure = any(int(run.get("failed", 0) or 0) > 0 for run in runs)
        ended_green = passed == total
        artifact_quality = self._artifact_quality(state)
        validation_stage_quality = (
            int(artifact_quality.get("stage_scores", {}).get("validation", 0) or 0) / 100
        )
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
        planning_model = (
            min(self._word_count(str(notes.get("understanding", ""))) / 45, 1) * 0.45
            + min(self._word_count(str(notes.get("planning", ""))) / 55, 1) * 0.55
        )
        reflection = min(self._word_count(str(notes.get("reflection", ""))) / 60, 1)
        validation_note = str(notes.get("validation", ""))
        production_terms = ["webhook", "reconcile", "refund", "monitor", "alert", "crash", "timeout", "pending"]
        production_judgment = (
            reflection * 0.55
            + min(sum(1 for word in production_terms if word in (validation_note + " " + str(notes.get("reflection", ""))).lower()) / 5, 1) * 0.45
        )
        communication = sum(1 for key in STAGE_ORDER if self._word_count(str(notes.get(key, ""))) >= 20) / len(STAGE_ORDER)
        code_quality = correctness
        breakdown = {
            "correctness": round(correctness * 100),
            "validation_behavior": round(validation * 100),
            "production_judgment": round(production_judgment * 100),
            "communication": round(communication * 100),
            "code_quality": round(code_quality * 100),
        }
        weighted = (
            breakdown["correctness"] * 0.50
            + breakdown["validation_behavior"] * 0.20
            + breakdown["production_judgment"] * 0.15
            + breakdown["communication"] * 0.10
            + breakdown["code_quality"] * 0.05
        ) / 100
        overall = round(weighted * 100)
        if passed < total:
            overall = min(overall, 68)
        if hidden_total and hidden_passed < hidden_total:
            overall = min(overall, 78)
        quality = int(artifact_quality.get("overall", 0) or 0)
        if quality < 45:
            overall = min(overall, 49)
            breakdown["production_judgment"] = min(breakdown["production_judgment"], 35)
            breakdown["communication"] = min(breakdown["communication"], 40)
        elif artifact_quality.get("shallow"):
            overall = min(overall, 68)
            breakdown["production_judgment"] = min(breakdown["production_judgment"], 55)
            breakdown["communication"] = min(breakdown["communication"], 60)
        if overall >= 85:
            hiring_signal = "strong_hire"
        elif overall >= 72:
            hiring_signal = "hire_with_followup"
        elif overall >= 55:
            hiring_signal = "mixed"
        elif overall >= 35:
            hiring_signal = "weak"
        else:
            hiring_signal = "no_hire"
        failed = [item.get("name", "") for item in result.get("details", []) if item.get("status") == "fail"]
        shallow = bool(artifact_quality.get("shallow"))
        authored_signal = ended_green and not shallow
        return {
            "overall_score": overall,
            "breakdown": breakdown,
            "passed": passed,
            "total": total,
            "strengths": [
                (
                    "Converted the idempotency requirement into executable payment-handler behavior."
                    if authored_signal
                    else "Final code passed the runtime checks, but authorship and independent reasoning remain uncertain."
                    if ended_green
                    else "Produced a runnable implementation attempt."
                ),
                (
                    "Used a validation loop with a failing attempt before reaching the final state."
                    if had_failure and ended_green
                    else "Explained what the passing validation evidence proves and does not prove."
                    if ended_green and validation_stage_quality >= 0.7
                    else "Collected runtime evidence for the implementation."
                ),
                "Addressed hidden safety checks around concurrency, cross-user conflicts, and gateway idempotency." if hidden_total and hidden_passed == hidden_total else "Hidden checks exposed remaining production risk.",
                f"Reasoning artifacts cleared the quality floor ({quality}/100)." if quality >= 62 else f"Reasoning artifacts were shallow despite runtime evidence ({quality}/100).",
            ],
            "risks": failed[:3] or [
                "Runtime tests are green, but real gateway webhooks, refunds, and crash recovery still need production design.",
                "Candidate explanation is keyword-heavy or under-explained; do not treat green tests alone as senior-level evidence." if shallow else "Reasoning artifacts were adequate for this simulation scope.",
            ],
            "what_proved": [
                f"Final code passed {passed}/{total} runtime checks.",
                f"Hidden suite result: {hidden_passed}/{hidden_total}.",
                "Candidate recorded validation and reflection artifacts." if communication >= 0.8 else "Some stage artifacts were thin.",
            ],
            "what_not_proved": failed[:3] or [
                "Full webhook reconciliation and refund workflow behavior are not implemented in this V1 sandbox.",
                "A real database transaction boundary was simulated, not proven against production Postgres.",
                "Deep reasoning quality remains weak; the system saw terms but not enough causal explanation." if shallow else "Candidate reasoning quality was sufficient for the deterministic assessment floor.",
                "Authorship and independent judgment remain uncertain because code quality was stronger than the reasoning artifacts." if shallow and ended_green else "Candidate reasoning aligned with the runtime evidence.",
            ],
            "key_quotes": [
                str(notes.get("planning", ""))[:180],
                str(notes.get("reflection", ""))[:180],
            ],
            "overclaim_detected": bool(shallow and ended_green),
            "hiring_signal": hiring_signal,
            "hiring_narrative": (
                f"Candidate produced {passed}/{total} passing runtime checks with {hidden_passed}/{hidden_total} hidden checks. "
                f"The deterministic score is {overall}, driven by code correctness, validation behavior, production judgment, communication evidence, and reasoning artifact quality ({quality}/100)."
            ),
            "artifact_quality": artifact_quality,
        }

    _SCORER_SYSTEM = (
        "You are evaluating a backend engineering candidate in a payment idempotency simulation. "
        "You must assess what the candidate actually proved through code and reasoning — not what they claimed. "
        "Be rigorous. A candidate who passes tests but cannot explain the invariants is weaker than one who "
        "patches carefully and explains remaining uncertainty. Reward evidence, penalize overclaiming. "
        "Respond with valid JSON only. No markdown, no explanation outside the JSON."
    )

    async def _semantic_score(self, state: dict[str, Any]) -> dict[str, Any]:
        baseline = self._score_baseline(state)
        if os.environ.get("SIMULATION_USE_LLM_SCORER", "").strip() != "1":
            return baseline
        try:
            notes = state.get("notes", {}) or {}
            runs = state.get("test_runs", []) or []
            result = state.get("test_result") or {}
            passed = int(result.get("passed", 0) or 0)
            total = int(result.get("total", 0) or 0)
            hidden_passed = int(result.get("hidden_passed", 0) or 0)
            hidden_total = int(result.get("hidden_total", 0) or 0)
            code = state.get("code", "")
            starter = state.get("starter_code", "")
            twist_handled = state.get("twist_injected", False)
            full_notes = "\n\n".join(
                f"[{k.upper()}]\n{v}" for k, v in notes.items() if v and v.strip()
            )
            user_prompt = (
                f"Test results: {passed}/{total} checks passing, {hidden_passed}/{hidden_total} hidden checks passing\n"
                f"Number of test runs: {len(runs)}\n"
                f"Production twist was injected: {twist_handled}\n\n"
                f"Candidate notes across all stages:\n{full_notes or '(none)'}\n\n"
                f"Candidate's final code:\n{code}\n\n"
                f"Original starter code:\n{starter}\n\n"
                "Evaluate this candidate. Return JSON with this exact structure:\n"
                "{\n"
                '  "scores": {\n'
                '    "correctness": <0-100>,\n'
                '    "validation_behavior": <0-100>,\n'
                '    "production_judgment": <0-100>,\n'
                '    "communication": <0-100>,\n'
                '    "code_quality": <0-100>\n'
                "  },\n"
                '  "overall_score": <0-100>,\n'
                '  "strengths": [<2-4 specific evidence-backed observations>],\n'
                '  "risks": [<2-3 specific gaps or unproven claims>],\n'
                '  "what_proved": [<2-4 things the candidate demonstrably proved>],\n'
                '  "what_not_proved": [<2-3 things that remain unproven>],\n'
                '  "key_quotes": [<1-3 verbatim short quotes from their notes that reveal their thinking>],\n'
                '  "overclaim_detected": <true|false>,\n'
                '  "hiring_signal": <"strong_hire"|"hire_with_followup"|"mixed"|"weak"|"no_hire">,\n'
                '  "hiring_narrative": <2-3 sentence plain-English verdict a hiring manager would trust>\n'
                "}"
            )
            router = LLMRouter(tier="medium", timeout_override=30.0)
            raw = await router.call(self._SCORER_SYSTEM, user_prompt, max_tokens=900)
            if not isinstance(raw, dict):
                raise RuntimeError("Simulation scorer LLM returned non-JSON output.")
            scores = raw.get("scores", {})
            def _bounded(value: Any, fallback: int = 0) -> int:
                try:
                    return max(0, min(100, int(value)))
                except Exception:
                    return fallback

            runtime_correctness = round((passed / max(total, 1)) * 100)
            breakdown = {
                "correctness": runtime_correctness,
                "validation_behavior": _bounded(scores.get("validation_behavior"), baseline["breakdown"]["validation_behavior"]),
                "production_judgment": _bounded(scores.get("production_judgment"), 0),
                "communication": _bounded(scores.get("communication"), baseline["breakdown"]["communication"]),
                "code_quality": _bounded(scores.get("code_quality"), 0),
            }
            if passed < total:
                breakdown["production_judgment"] = min(breakdown["production_judgment"], 70)
                breakdown["code_quality"] = min(breakdown["code_quality"], runtime_correctness + 20)
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
            return {
                "overall_score": overall,
                "breakdown": breakdown,
                "passed": passed,
                "total": total,
                "strengths": raw.get("strengths", []),
                "risks": raw.get("risks", []),
                "what_proved": raw.get("what_proved", []),
                "what_not_proved": raw.get("what_not_proved", []),
                "key_quotes": raw.get("key_quotes", []),
                "overclaim_detected": bool(raw.get("overclaim_detected", False)),
                "hiring_signal": raw.get("hiring_signal", "mixed"),
                "hiring_narrative": raw.get("hiring_narrative", ""),
                "artifact_quality": baseline.get("artifact_quality", self._artifact_quality(state)),
            }
        except Exception as exc:
            raise RuntimeError(f"Simulation scorer LLM failed: {type(exc).__name__}: {exc}") from exc

    def _build_event_timeline(self, state: dict[str, Any]) -> list[dict[str, str]]:
        raw = list(reversed(state.get("telemetry", [])))
        if not raw:
            return []
        created_at = state.get("created_at", raw[0]["at"])
        timeline = []
        for event in raw:
            elapsed = max(0.0, event["at"] - created_at)
            ts = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
            evt = event["event"]
            detail = event.get("detail", "")
            passed = event.get("passed")
            total = event.get("total")
            stage = event.get("stage", "")
            if evt == "simulation.session_started":
                text = "Session started — baseline established"
            elif evt == "simulation.stage_updated":
                text = f"Candidate moved to {stage or 'unknown'} stage"
            elif evt == "simulation.tests_ran":
                text = f"Tests ran — {passed}/{total} checks passing"
                if passed == total:
                    text += " ✓ all green"
            elif evt == "simulation.twist_injected":
                text = "Production twist injected — gateway timeout with delayed webhook"
            elif evt == "simulation.finalized":
                text = f"Session finalized — {detail}"
            else:
                text = detail or evt
            timeline.append({"ts": ts, "text": text})
        return timeline

    async def finalize(
        self,
        session_id: str,
        *,
        code: str = "",
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        state = await self.get_state(session_id)
        if code:
            state["code"] = code
        if notes:
            for key, value in notes.items():
                if key in STAGE_ORDER:
                    state.setdefault("notes", {})[key] = str(value)
        if not state.get("test_runs"):
            raise ValueError("Run tests before finalizing the simulation.")
        if state.get("current_stage") != "reflection":
            raise ValueError("Move to the reflection stage before finalizing the simulation.")
        if not state.get("test_result"):
            raise ValueError("No validation result is available to finalize.")
        if not self._code_changed(state):
            raise ValueError("Cannot finalize without a candidate code change.")
        validation_issues = self._stage_artifact_issues(state, "validation")
        if validation_issues:
            raise ValueError(" ".join(validation_issues))
        reflection_issues = self._stage_artifact_issues(state, "reflection")
        if reflection_issues:
            raise ValueError(" ".join(reflection_issues))
        score = await self._semantic_score(state)
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
                "Treat this as green runtime evidence with unresolved authorship and independent-reasoning risk."
                if shallow_reasoning
                else "The written artifacts explain the invariant, validation result, and remaining production risk well enough to support the runtime evidence."
            ),
        }
        result = state.get("test_result") or {}
        notes_state = state.get("notes", {}) or {}
        failed = [item.get("name", "") for item in result.get("details", []) if item.get("status") == "fail"]
        hidden_total = int(result.get("hidden_total", 0) or 0)
        hidden_passed = int(result.get("hidden_passed", 0) or 0)
        twist_injected = bool(state.get("twist_injected"))

        hiring_signal = score.get("hiring_signal", "mixed")
        hiring_labels = {
            "strong_hire": "Strong Hire",
            "hire_with_followup": "Hire — Follow-up Recommended",
            "mixed": "Mixed Signal",
            "weak": "Weak Signal",
            "no_hire": "No Hire",
        }

        report = {
            **score,
            "title": "Payment Retry Safety — Assessment Report",
            "summary": score.get("hiring_narrative") or (
                f"Candidate passed {score['passed']}/{score['total']} runtime checks "
                f"({hidden_passed}/{hidden_total} hidden safety checks)."
            ),
            "hiring_label": hiring_labels.get(hiring_signal, "Mixed Signal"),
            "stage_evidence": {
                key: {
                    "words": len(str(notes_state.get(key, "")).split()),
                    "captured": bool(str(notes_state.get(key, "")).strip()),
                    "quality": score.get("artifact_quality", {}).get("stage_scores", {}).get(key, 0),
                    "quality_issues": score.get("artifact_quality", {}).get("stage_issues", {}).get(key, []),
                }
                for key in STAGE_ORDER
            },
            "artifact_quality": artifact_quality,
            "reasoning_signal": reasoning_signal,
            "evidence_ledger": evidence_ledger,
            "next_challenge": evidence_ledger.get("next_challenge"),
            "event_timeline": self._build_event_timeline(state),
            "test_result": result,
            "twist_was_injected": twist_injected,
            "unresolved": score.get("what_not_proved") or failed or [
                "Gateway webhook reconciliation, crash-after-charge recovery, and real DB transaction races "
                "remain out of scope for this simulation."
            ],
        }
        state["report"] = report
        state["complete"] = True
        state["current_stage"] = "reflection"
        state["interviewer_message"] = (
            f"Simulation complete. {hiring_labels.get(hiring_signal, 'Assessment complete.')} — "
            "The report separates what the code proved from what remains untested."
        )
        self._record_local(state, "simulation.finalized", f"Final score {score['overall_score']} — {hiring_signal}.")
        await self._save(state)
        await interview_telemetry.log(
            session_id,
            "simulation.finalized",
            source="backend.simulation",
            overall_score=score["overall_score"],
            passed=score["passed"],
            total=score["total"],
        )
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


simulation_service = SimulationService()
