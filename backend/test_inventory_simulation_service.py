import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.inventory_simulation_service import GOLDEN_SOLUTION, STARTER_CODE, inventory_simulation_service


BAD_PATCH = """
export async function reserveInventory(productId, quantity, store) {
  if (!quantity || quantity < 1) throw new Error('quantity must be positive');
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

GOOD_NOTES = {
    "understanding": (
        "This is a concurrent read/write race. Many requests can read available inventory before any decrement writes, "
        "so each request believes stock exists and the system oversells. I would inspect the inventory row, version, "
        "reservation records, and the invariant that confirmed reservations must never exceed available stock."
    ),
    "planning": (
        "I will use optimistic locking with a versioned compare-and-decrement operation. First I read the product and "
        "check available quantity, then the decrement only succeeds if the version still matches. On contention I retry "
        "or return a contention response, and partial crash behavior needs compensation or reconciliation."
    ),
    "implementation": (
        "The handler now uses compareAndDecrement with the observed version, retries contention a few times, rejects "
        "invalid quantity, and only creates a reservation after the atomic decrement succeeds."
    ),
    "validation": (
        "The passing tests prove normal reservations, insufficient inventory handling, concurrent oversell protection, "
        "exact-boundary concurrency, failed reservation invariants, and high-concurrency bursts. The crash twist still "
        "does not prove recovery for a decrement that succeeds before the reservation write."
    ),
    "reflection": (
        "The tradeoff is optimistic locking gives better throughput than a broad pessimistic lock, but high contention "
        "can create retries and latency. I would monitor contention rates, retry counts, old pending or ghost inventory, "
        "reservation/write mismatches, alerts on negative availability, and crash recovery or compensation events."
    ),
}

KEYWORD_SALAD_NOTES = {
    "understanding": (
        "race concurrent parallel read write gap window inventory available decrement quantity stock invariant oversell "
        "atomic consistent race concurrent parallel read write gap window inventory available decrement quantity stock"
    ),
    "planning": (
        "optimistic pessimistic atomic compare version lock cas transaction contention retry conflict fail rollback abort "
        "partial crash consistent both neither optimistic pessimistic atomic compare version lock cas transaction "
        "contention retry conflict fail rollback abort partial crash consistent atomic compare version lock"
    ),
    "implementation": (
        "compare version atomic retry contention decrement reservation compare version atomic retry "
        "lock cas update store conflict handling"
    ),
    "validation": (
        "test evidence proves concurrent hidden oversell boundary crash partial ghost recovery test evidence proves "
        "concurrent hidden oversell boundary crash partial ghost recovery"
    ),
    "reflection": (
        "monitor metric alert log dashboard optimistic pessimistic contention throughput tradeoff latency crash partial "
        "ghost rollback compensate monitor metric alert log dashboard optimistic pessimistic contention throughput "
        "tradeoff latency remaining risk production review incident recovery consistent inventory reservation"
    ),
}


async def main() -> None:
    starter = await inventory_simulation_service._run_node_tests(STARTER_CODE)
    assert starter["passed"] < starter["total"], starter

    golden = await inventory_simulation_service._run_node_tests(GOLDEN_SOLUTION)
    assert golden["passed"] == golden["total"], golden

    state = await inventory_simulation_service.start_session()
    assert state["simulation_family"] == "inventory_race", state
    try:
        await inventory_simulation_service.interviewer_turn(state["session_id"], stage_key="planning", notes={})
        raise AssertionError("empty inventory progression should be blocked")
    except ValueError:
        pass
    try:
        await inventory_simulation_service.run_tests(state["session_id"], code=STARTER_CODE, notes=GOOD_NOTES)
        raise AssertionError("starter-code validation should be blocked")
    except ValueError:
        pass

    state = await inventory_simulation_service.interviewer_turn(
        state["session_id"],
        stage_key="planning",
        notes={"understanding": GOOD_NOTES["understanding"]},
    )
    state = await inventory_simulation_service.interviewer_turn(
        state["session_id"],
        stage_key="implementation",
        notes={**GOOD_NOTES, "validation": "", "reflection": ""},
    )
    failed = await inventory_simulation_service.run_tests(state["session_id"], code=BAD_PATCH, notes=GOOD_NOTES)
    assert failed["test_result"]["passed"] < failed["test_result"]["total"], failed["test_result"]

    state = await inventory_simulation_service.run_tests(state["session_id"], code=GOLDEN_SOLUTION, notes=GOOD_NOTES)
    assert state["test_result"]["passed"] == state["test_result"]["total"], state["test_result"]
    state = await inventory_simulation_service.interviewer_turn(
        state["session_id"],
        stage_key="reflection",
        code=GOLDEN_SOLUTION,
        notes=GOOD_NOTES,
    )
    state = await inventory_simulation_service.finalize(state["session_id"], code=GOLDEN_SOLUTION, notes=GOOD_NOTES)
    assert state["report"]["overall_score"] >= 85, state["report"]
    assert state["report"]["hiring_signal"] == "strong_hire", state["report"]
    assert state["report"]["artifact_quality"]["shallow"] is False, state["report"]
    assert state["report"]["evidence_ledger"]["coverage_score"] == 100, state["report"]["evidence_ledger"]
    assert state["report"]["evidence_ledger"]["summary"]["proved_count"] >= 10, state["report"]["evidence_ledger"]
    assert state["report"]["next_challenge"]["id"] in {
        "ghost_inventory_recovery",
        "production_locking_boundary",
        "flash_sale_scale_design",
    }, state["report"]["next_challenge"]
    listed = await inventory_simulation_service.list_sessions()
    assert any(item["session_id"] == state["session_id"] for item in listed), listed

    shallow = await inventory_simulation_service.start_session()
    shallow = await inventory_simulation_service.interviewer_turn(
        shallow["session_id"],
        stage_key="planning",
        notes={"understanding": KEYWORD_SALAD_NOTES["understanding"]},
    )
    shallow = await inventory_simulation_service.interviewer_turn(
        shallow["session_id"],
        stage_key="implementation",
        notes={**KEYWORD_SALAD_NOTES, "validation": "", "reflection": ""},
    )
    shallow = await inventory_simulation_service.run_tests(
        shallow["session_id"],
        code=GOLDEN_SOLUTION,
        notes=KEYWORD_SALAD_NOTES,
    )
    shallow = await inventory_simulation_service.interviewer_turn(
        shallow["session_id"],
        stage_key="reflection",
        code=GOLDEN_SOLUTION,
        notes=KEYWORD_SALAD_NOTES,
    )
    shallow = await inventory_simulation_service.finalize(
        shallow["session_id"],
        code=GOLDEN_SOLUTION,
        notes=KEYWORD_SALAD_NOTES,
    )
    assert shallow["report"]["test_result"]["passed"] == shallow["report"]["test_result"]["total"], shallow["report"]
    assert shallow["report"]["overall_score"] <= 68, shallow["report"]
    assert shallow["report"]["hiring_signal"] != "strong_hire", shallow["report"]
    assert shallow["report"]["overclaim_detected"] is True, shallow["report"]
    assert shallow["report"]["evidence_ledger"]["summary"]["contradiction_count"] >= 1, shallow["report"]["evidence_ledger"]
    assert shallow["report"]["next_challenge"]["id"] == "explain_green_code_authorship", shallow["report"]["next_challenge"]

    print("inventory_simulation_service tests passed")


if __name__ == "__main__":
    asyncio.run(main())
