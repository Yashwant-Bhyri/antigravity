import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.simulation_service import GOLDEN_SOLUTION, STARTER_CODE, simulation_service


SYNTAX_ERROR = "export async function createPayment(input, store, gateway) {"

INFINITE_LOOP = """
export async function createPayment(input, store, gateway) {
  while (true) {}
}
"""

FS_ESCAPE = """
import fs from "node:fs";
export async function createPayment(input, store, gateway) {
  fs.readFileSync("/etc/passwd", "utf8");
  return { status: "completed" };
}
"""

GOOD_NOTES = {
    "understanding": (
        "The failure is a retry after a mobile timeout creating duplicate money movement. I would inspect the "
        "client operation id or idempotency key, the payment row status, whether the gateway charge id is persisted, "
        "and how the handler behaves when an existing payment record is pending or completed."
    ),
    "planning": (
        "I will require an idempotency key, check existing records before charging, reject same-key requests with "
        "different amount or currency as conflicts, reuse completed or pending attempts, persist pending state before "
        "the gateway call, pass the key to the gateway, and leave timeout failures recoverable."
    ),
    "implementation": (
        "I changed createPayment to resolve existing idempotency records first, insert a pending record with the key, "
        "handle unique-key races, pass the key to the gateway, and mark failures as recoverable."
    ),
    "validation": (
        "The test evidence proves duplicate completed retries, pending reuse, conflict rejection, timeout recovery, "
        "hidden concurrent retries, cross-user conflicts, and gateway idempotency propagation. The webhook twist still "
        "requires reconciliation so an original timeout charge is not ignored or double-refunded."
    ),
    "reflection": (
        "The tradeoff is a stricter payment state machine and more persistence complexity in exchange for safer money "
        "movement. After deploy I would monitor duplicate-key rates, conflict rejections, pending and failed recovery "
        "age, gateway webhook mismatches, refund/reconciliation events, and alert on crash or timeout gaps that leave "
        "charges without a completed local record."
    ),
}

KEYWORD_SALAD_NOTES = {
    "understanding": (
        "retry timeout duplicate idempotency gateway charge payment status record inspect retry timeout duplicate "
        "idempotency gateway charge payment status record inspect retry timeout duplicate idempotency gateway charge "
        "payment row status inspect persisted record client operation money movement"
    ),
    "planning": (
        "idempotency key conflict amount currency pending completed reuse existing gateway timeout recoverable failure "
        "before after sequence reject persist pass idempotency key conflict pending completed gateway timeout recoverable "
        "same key different amount currency existing record pending completed failure recovery"
    ),
    "implementation": (
        "changed idempotency pending gateway recoverable unique insert store pass resolve idempotency pending gateway"
    ),
    "validation": (
        "test evidence proves duplicate conflict timeout concurrent hidden webhook reconcile original refund test evidence "
        "proves duplicate conflict timeout concurrent hidden webhook reconcile original refund"
    ),
    "reflection": (
        "monitor alert metric webhook reconcile refund crash timeout remaining risk tradeoff complexity monitor alert "
        "metric webhook reconcile refund crash timeout remaining risk tradeoff complexity deploy production dashboard "
        "log gateway mismatch pending failed age customer complaint review"
    ),
}

CONCISE_STRONG_NOTES = {
    "understanding": (
        "This is a retry timeout problem where one client operation can create duplicate payment rows and gateway "
        "charges. I would inspect the idempotency key, persisted row status, existing gateway charge id, and whether "
        "a completed or pending record is reused before another charge happens."
    ),
    "planning": (
        "Require the idempotency key first, then check existing records before the gateway call. If the same key has "
        "a different amount or currency I reject it as a conflict. If the attempt is pending or completed I reuse it, "
        "and if the gateway times out I leave a recoverable failure state."
    ),
    "implementation": (
        "The handler now resolves existing attempts first, writes a pending record with the key, handles unique races, "
        "passes the key to the gateway, and stores recoverable failure state."
    ),
    "validation": (
        "The passing tests prove missing-key rejection, duplicate completed reuse, pending reuse, conflict rejection, "
        "timeout recovery, hidden concurrency, cross-user conflict checks, and gateway idempotency propagation. They do "
        "not prove webhook reconciliation for an original timeout that later succeeds."
    ),
    "reflection": (
        "The tradeoff is extra state-machine complexity for safer money movement. I would monitor duplicate-key rates, "
        "conflict rejects, old pending or failed records, gateway webhook mismatches, refunds, reconciliation events, "
        "and crash or timeout gaps where the gateway has a charge but our local row is not completed."
    ),
}


async def main() -> None:
    starter = await simulation_service._run_node_tests(STARTER_CODE)
    assert starter["passed"] < starter["total"], starter

    golden = await simulation_service._run_node_tests(GOLDEN_SOLUTION)
    assert golden["passed"] == golden["total"], golden

    syntax = await simulation_service._run_node_tests(SYNTAX_ERROR)
    assert syntax["failed"] >= 1 and syntax["return_code"] != 0, syntax

    timeout = await simulation_service._run_node_tests(INFINITE_LOOP)
    assert timeout["timed_out"] is True, timeout

    escape = await simulation_service._run_node_tests(FS_ESCAPE)
    assert escape["failed"] >= 1 and escape["return_code"] != 0, escape

    state = await simulation_service.start_session()
    assert state["session_id"]
    try:
        await simulation_service.interviewer_turn(state["session_id"], stage_key="planning", notes={})
        raise AssertionError("empty progression should be blocked")
    except ValueError:
        pass
    try:
        await simulation_service.run_tests(state["session_id"], code=STARTER_CODE, notes=GOOD_NOTES)
        raise AssertionError("starter-code validation should be blocked")
    except ValueError:
        pass

    state = await simulation_service.interviewer_turn(
        state["session_id"],
        stage_key="planning",
        notes={"understanding": GOOD_NOTES["understanding"]},
    )
    state = await simulation_service.interviewer_turn(
        state["session_id"],
        stage_key="implementation",
        notes={**GOOD_NOTES, "validation": "", "reflection": ""},
    )
    state = await simulation_service.run_tests(state["session_id"], code=GOLDEN_SOLUTION, notes=GOOD_NOTES)
    assert state["test_result"]["passed"] == state["test_result"]["total"], state["test_result"]
    state = await simulation_service.interviewer_turn(
        state["session_id"],
        stage_key="reflection",
        code=GOLDEN_SOLUTION,
        notes=GOOD_NOTES,
    )
    state = await simulation_service.finalize(state["session_id"], code=GOLDEN_SOLUTION, notes=GOOD_NOTES)
    assert state["report"]["overall_score"] >= 85, state["report"]
    assert state["report"]["hiring_signal"] == "strong_hire", state["report"]
    assert state["report"]["breakdown"]["validation_behavior"] >= 80, state["report"]
    assert state["report"]["evidence_ledger"]["coverage_score"] == 100, state["report"]["evidence_ledger"]
    assert state["report"]["evidence_ledger"]["summary"]["proved_count"] >= 10, state["report"]["evidence_ledger"]
    assert state["report"]["next_challenge"]["id"] in {
        "production_transaction_boundary",
        "scale_idempotency_retention",
    }, state["report"]["next_challenge"]
    listed = await simulation_service.list_sessions()
    assert any(item["session_id"] == state["session_id"] for item in listed), listed

    concise = await simulation_service.start_session()
    concise = await simulation_service.interviewer_turn(
        concise["session_id"],
        stage_key="planning",
        notes={"understanding": CONCISE_STRONG_NOTES["understanding"]},
    )
    concise = await simulation_service.interviewer_turn(
        concise["session_id"],
        stage_key="implementation",
        notes={**CONCISE_STRONG_NOTES, "validation": "", "reflection": ""},
    )
    concise = await simulation_service.run_tests(
        concise["session_id"],
        code=GOLDEN_SOLUTION,
        notes=CONCISE_STRONG_NOTES,
    )
    concise = await simulation_service.interviewer_turn(
        concise["session_id"],
        stage_key="reflection",
        code=GOLDEN_SOLUTION,
        notes=CONCISE_STRONG_NOTES,
    )
    concise = await simulation_service.finalize(
        concise["session_id"],
        code=GOLDEN_SOLUTION,
        notes=CONCISE_STRONG_NOTES,
    )
    assert concise["report"]["artifact_quality"]["shallow"] is False, concise["report"]
    assert concise["report"]["overall_score"] >= 85, concise["report"]
    assert concise["report"]["hiring_signal"] == "strong_hire", concise["report"]

    shallow = await simulation_service.start_session()
    shallow = await simulation_service.interviewer_turn(
        shallow["session_id"],
        stage_key="planning",
        notes={"understanding": KEYWORD_SALAD_NOTES["understanding"]},
    )
    shallow = await simulation_service.interviewer_turn(
        shallow["session_id"],
        stage_key="implementation",
        notes={**KEYWORD_SALAD_NOTES, "validation": "", "reflection": ""},
    )
    shallow = await simulation_service.run_tests(shallow["session_id"], code=GOLDEN_SOLUTION, notes=KEYWORD_SALAD_NOTES)
    shallow = await simulation_service.interviewer_turn(
        shallow["session_id"],
        stage_key="reflection",
        code=GOLDEN_SOLUTION,
        notes=KEYWORD_SALAD_NOTES,
    )
    shallow = await simulation_service.finalize(
        shallow["session_id"],
        code=GOLDEN_SOLUTION,
        notes=KEYWORD_SALAD_NOTES,
    )
    assert shallow["report"]["test_result"]["passed"] == shallow["report"]["test_result"]["total"], shallow["report"]
    assert shallow["report"]["overall_score"] <= 68, shallow["report"]
    assert shallow["report"]["hiring_signal"] != "strong_hire", shallow["report"]
    assert shallow["report"]["artifact_quality"]["shallow"] is True, shallow["report"]
    assert shallow["report"]["evidence_ledger"]["summary"]["contradiction_count"] >= 1, shallow["report"]["evidence_ledger"]
    assert shallow["report"]["next_challenge"]["id"] == "explain_green_code_authorship", shallow["report"]["next_challenge"]

    print("simulation_service tests passed")


if __name__ == "__main__":
    asyncio.run(main())
