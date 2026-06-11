import { expect, type Page, type Route, test } from "@playwright/test";

const BAD_PATCH = `export async function createPayment(input, store, gateway) {
  if (!input.idempotencyKey) {
    throw new Error("missing idempotency key");
  }

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
}`;

const GOOD_PATCH = `export async function createPayment(input, store, gateway) {
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
}`;

const GOOD_INVENTORY_PATCH = `export async function reserveInventory(productId, quantity, store) {
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
}`;

const UNDERSTANDING_NOTE =
  "The dangerous path is a client retry after a mobile timeout: the first request may already have created a gateway charge, but the local handler does not know how to connect the retry to the original operation. Because the code inserts a fresh payment row before calling the gateway, the same client operation can become two payment records and two money movements. I would inspect the idempotency key, payment row status, gateway charge id persistence, and whether pending or completed attempts are reused before any second charge call.";

const PLANNING_NOTE =
  "First I will require an idempotency key because requests without an operation identity cannot be safely retried. Before calling the gateway, I will check for an existing attempt and compare user, amount, and currency so the same key with different payload is rejected as a conflict. Then I will persist a pending record, reuse completed or pending attempts, pass the key to the gateway, and mark gateway timeouts as recoverable instead of pretending the payment completed.";

const IMPLEMENTATION_NOTE =
  "I changed the handler so existing idempotency records are resolved before any gateway call. The insert now creates a pending payment with the key, and if a unique-key race happens it reloads the raced record rather than charging again. The gateway receives the same idempotency key, completed records return the original charge id, and timeout failures are stored as recoverable failed attempts.";

const VALIDATION_NOTE =
  "The first bad patch failed because it required a key but still inserted a new row and charged again, so the failure pointed at the missing existing-attempt lookup and persistence order. The final runtime evidence proves duplicate completed retries, pending reuse, conflict rejection, timeout recovery, concurrent duplicate collapse, cross-user conflicts, and gateway idempotency propagation. The production twist means tests do not prove webhook reconciliation: if the original timed-out charge later succeeds, the system must reconcile that gateway event to the original attempt or refund/void the later duplicate.";

const REFLECTION_NOTE =
  "The patch trades a stricter payment state machine and uniqueness handling for safer money movement, because payment retries should be joined by operation identity rather than treated as independent creates. After deploy I would monitor duplicate key rates, conflict rejections, aged pending and failed records, gateway webhook mismatches, refund and reconciliation events, and crash or timeout gaps where a gateway charge exists without a completed local record. I would ask a teammate to review the transaction boundary and webhook reconciliation path because green request tests still do not prove every asynchronous gateway outcome.";

const INVENTORY_UNDERSTANDING_NOTE =
  "This is a concurrent read/write race where many requests can read the same available inventory before any decrement writes. Each request then believes stock exists, so confirmed reservations can exceed the inventory cap. I would inspect the product row, version, reservation records, decrement history, and the invariant that total confirmed reserved quantity must never exceed available stock.";

const INVENTORY_PLANNING_NOTE =
  "I will use optimistic locking through a versioned compare-and-decrement operation. First I read the product and check available quantity, then the decrement only succeeds if the version still matches. If another request wins, I retry or return contention without corrupting state, and I still need a recovery story for partial crashes between decrement and reservation creation.";

const INVENTORY_IMPLEMENTATION_NOTE =
  "I changed the handler to reject invalid quantities, read the product version, use compareAndDecrement as the atomic boundary, retry contention a bounded number of times, and create the reservation only after the decrement succeeds.";

const INVENTORY_VALIDATION_NOTE =
  "The runtime evidence proves normal reservations, exact depletion, insufficient inventory handling, zero quantity rejection, sequential updates, concurrent oversell protection, exact-boundary concurrency, and high-concurrency burst safety. The production twist still does not prove crash recovery when the decrement succeeds but createReservation never returns.";

const INVENTORY_REFLECTION_NOTE =
  "The tradeoff is optimistic locking gives better throughput than a broad pessimistic lock, but high contention can increase retries and latency. After deploy I would monitor contention rates, retry counts, negative or near-zero availability, ghost inventory, reservation/write mismatches, crash recovery events, and compensation jobs that reconcile decrements without reservations.";

const KEYWORD_SALAD_NOTES = {
  understanding:
    "retry timeout duplicate idempotency gateway charge payment status record inspect retry timeout duplicate idempotency gateway charge payment status record inspect retry timeout duplicate idempotency gateway charge payment row status inspect persisted record client operation money movement",
  planning:
    "idempotency key conflict amount currency pending completed reuse existing gateway timeout recoverable failure before after sequence reject persist pass idempotency key conflict pending completed gateway timeout recoverable same key different amount currency existing record pending completed failure recovery",
  implementation:
    "changed idempotency pending gateway recoverable unique insert store pass resolve idempotency pending gateway",
  validation:
    "test evidence proves duplicate conflict timeout concurrent hidden webhook reconcile original refund test evidence proves duplicate conflict timeout concurrent hidden webhook reconcile original refund",
  reflection:
    "monitor alert metric webhook reconcile refund crash timeout remaining risk tradeoff complexity monitor alert metric webhook reconcile refund crash timeout remaining risk tradeoff complexity deploy production dashboard log gateway mismatch pending failed age customer complaint review",
};

async function prepareSimulationPage(page: Page) {
  const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT;
  if (backendPort && backendPort !== "8000") {
    await page.route(/http:\/\/(127\.0\.0\.1|localhost):8000\/api\/.*/, async (route: Route) => {
      const url = route.request().url().replace(/http:\/\/(127\.0\.0\.1|localhost):8000/, `http://127.0.0.1:${backendPort}`);
      await route.continue({ url });
    });
  }

  await page.route("**/api/tts", async (route: Route) => {
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "stubbed unavailable tts provider" }),
    });
  });

  await page.goto("/simulation");
}

async function expectCoreSimulationOnly(page: Page) {
  await expect(page.getByRole("button", { name: /Hear Prompt/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Gemini Live Mic/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Record Note/i })).toHaveCount(0);
  await expect(page.getByText("Upload Audio", { exact: true })).toHaveCount(0);
}

async function fillEditor(page: Page, code: string, expectedText = "createPayment") {
  await page.evaluate((nextCode) => {
    window.dispatchEvent(new CustomEvent("antigravity:set-simulation-code", { detail: nextCode }));
  }, code);
  await expect(page.locator(".monaco-editor").first()).toContainText(expectedText);
}

async function reachImplementation(page: Page) {
  await expect(page.getByRole("button", { name: "Start Simulation" })).toBeVisible();
  await page.getByRole("button", { name: "Start Simulation" }).click();

  await expect(page.getByRole("heading", { name: "Payment Retry Safety" })).toBeVisible();
  await expectCoreSimulationOnly(page);
  await expect(page.getByText("Assessment Lead")).toBeVisible();
  await expect(page.getByLabel("Understand worklog")).toBeVisible();
  await expect(page.getByText(/runs\.\d+/).first()).toBeVisible();
  await expect(page.getByText(/Starter baseline: \d+\/10 checks/).first()).toBeVisible({ timeout: 15_000 });

  await page.getByLabel("Understand worklog").fill(UNDERSTANDING_NOTE);

  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Plan worklog")).toBeVisible();
  await page.getByLabel("Plan worklog").fill(PLANNING_NOTE);
  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Implement worklog")).toBeVisible();
  await page.getByLabel("Implement worklog").fill(IMPLEMENTATION_NOTE);
}

test("empty click-through is blocked and produces no score", async ({ page }) => {
  await prepareSimulationPage(page);
  await page.getByRole("button", { name: "Start Simulation" }).click();
  await expectCoreSimulationOnly(page);
  await expect(page.getByText(/Starter baseline: \d+\/10 checks/).first()).toBeVisible();
  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByText("Give me a concrete incident read before we move on")).toBeVisible();
  await expect(page.getByLabel("Understand worklog")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run Tests" })).toBeDisabled();
  await expect(page.getByText("final score")).toHaveCount(0);
});

test("starter code cannot be counted as candidate validation", async ({ page }) => {
  await prepareSimulationPage(page);
  await reachImplementation(page);
  await expect(page.getByRole("button", { name: "Run Tests" })).toBeDisabled();
  await fillEditor(page, BAD_PATCH);
  await expect(page.getByRole("button", { name: "Run Tests" })).toBeEnabled();
  await page.getByRole("button", { name: "Run Tests" }).click();
  await expect(page.getByText("duplicate completed request returns the original attempt without a second charge")).toBeVisible();
  await expect(page.getByText(/3\/10 checks/).first()).toBeVisible();
});

test("candidate can complete the payment retry safety simulation", async ({ page }, testInfo) => {
  await prepareSimulationPage(page);
  await reachImplementation(page);

  await fillEditor(page, GOOD_PATCH);
  await page.getByRole("button", { name: "Run Tests" }).click();
  await expect(page.getByText(/10\/10 checks passing/).first()).toBeVisible();
  await page.getByLabel("Validate worklog").fill(VALIDATION_NOTE);

  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Reflect worklog")).toBeVisible();
  await page.getByLabel("Reflect worklog").fill(REFLECTION_NOTE);

  await page.getByRole("button", { name: "Finalize" }).click();
  await expect(page.getByText("Assessment Report")).toBeVisible();
  await expect(page.getByText("Strong Hire", { exact: true })).toBeVisible();
  await expect(page.getByText("What Was Proved")).toBeVisible();
  await expect(page.getByText("What Remains Unproven")).toBeVisible();
  await expect(page.getByText("Reasoning Quality / Authorship Signal")).toBeVisible();
  await expect(page.getByText(/webhook reconciliation|production risk/i).first()).toBeVisible();

  await page.screenshot({ path: testInfo.outputPath("simulation-e2e-screenshot.png"), fullPage: true });
});

test("keyword-salad candidate with correct code is capped below strong hire", async ({ page }) => {
  await prepareSimulationPage(page);
  await page.getByRole("button", { name: "Start Simulation" }).click();
  await expect(page.getByRole("heading", { name: "Payment Retry Safety" })).toBeVisible();
  await expect(page.getByLabel("Understand worklog")).toBeVisible();

  await page.getByLabel("Understand worklog").fill(KEYWORD_SALAD_NOTES.understanding);
  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Plan worklog")).toBeVisible();
  await page.getByLabel("Plan worklog").fill(KEYWORD_SALAD_NOTES.planning);
  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Implement worklog")).toBeVisible();
  await page.getByLabel("Implement worklog").fill(KEYWORD_SALAD_NOTES.implementation);

  await fillEditor(page, GOOD_PATCH);
  await page.getByRole("button", { name: "Run Tests" }).click();
  await expect(page.getByText(/10\/10 checks passing/).first()).toBeVisible();
  await page.getByLabel("Validate worklog").fill(KEYWORD_SALAD_NOTES.validation);

  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Reflect worklog")).toBeVisible();
  await page.getByLabel("Reflect worklog").fill(KEYWORD_SALAD_NOTES.reflection);
  await page.getByRole("button", { name: "Finalize" }).click();

  await expect(page.getByText("Assessment Report")).toBeVisible();
  await expect(page.getByText("Strong Hire", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Mixed Signal|Weak Signal/).first()).toBeVisible();
  await expect(page.getByText("Reasoning Quality / Authorship Signal")).toBeVisible();
  await expect(page.getByText(/Weak reasoning|authorship uncertain|Deep reasoning quality remains weak|Authorship/i).first()).toBeVisible();
});

test("inventory simulation completes with persisted report", async ({ page }) => {
  await prepareSimulationPage(page);
  await page.goto("/simulation/inventory");
  await expect(page.getByRole("button", { name: "Start Simulation" })).toBeVisible();
  await page.getByRole("button", { name: "Start Simulation" }).click();

  // Baseline Node.js test run happens during start — allow up to 20s
  await expect(page.getByRole("heading", { name: "Flash Sale Inventory Race" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByLabel("Understand worklog")).toBeVisible();
  await page.getByLabel("Understand worklog").fill(INVENTORY_UNDERSTANDING_NOTE);
  await page.getByRole("button", { name: "Next Stage" }).click();

  await expect(page.getByLabel("Plan worklog")).toBeVisible();
  await page.getByLabel("Plan worklog").fill(INVENTORY_PLANNING_NOTE);
  await page.getByRole("button", { name: "Next Stage" }).click();

  await expect(page.getByLabel("Implement worklog")).toBeVisible();
  await page.getByLabel("Implement worklog").fill(INVENTORY_IMPLEMENTATION_NOTE);
  await fillEditor(page, GOOD_INVENTORY_PATCH, "reserveInventory");
  await page.getByRole("button", { name: "Run Tests" }).click();
  // Hidden concurrency tests (20-100 concurrent requests) — allow up to 20s
  await expect(page.getByText(/10\/10 checks/).first()).toBeVisible({ timeout: 20_000 });
  await page.getByLabel("Validate worklog").fill(INVENTORY_VALIDATION_NOTE);

  await page.getByRole("button", { name: "Next Stage" }).click();
  await expect(page.getByLabel("Reflect worklog")).toBeVisible();
  await page.getByLabel("Reflect worklog").fill(INVENTORY_REFLECTION_NOTE);
  await page.getByRole("button", { name: "Finalize" }).click();

  await expect(page.getByText("Strong Hire", { exact: true })).toBeVisible();
  const share = page.getByText("Share Report", { exact: false });
  await expect(share).toBeVisible();
  const href = await share.getAttribute("href");
  expect(href).toContain("/simulation/report/");
  await page.goto(href as string);
  await expect(page.getByText("Flash Sale Inventory Race", { exact: true })).toBeVisible();
  await expect(page.getByText("Assessment Report", { exact: true })).toBeVisible();
  await expect(page.getByText(/ghost inventory|crash-between/i).first()).toBeVisible();
});

test("simulation admin lists completed payment and inventory reports", async ({ page }) => {
  await prepareSimulationPage(page);
  await page.goto("/simulation/admin");
  await expect(page.getByText("Simulation Admin")).toBeVisible();
  await expect(page.getByText("Payment Retry Safety").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Flash Sale Inventory Race").first()).toBeVisible();
  await expect(page.getByText("Strong Hire").first()).toBeVisible();
  await expect(page.locator('a[href^="/simulation/report/"]').first()).toBeVisible();
});
