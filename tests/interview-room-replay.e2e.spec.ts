import { expect, test } from "@playwright/test";

const replayCase = {
  case_id: "best_product_replay",
  label: "Best Product Replay",
  source_type: "full_gate_artifact",
  source_path: "/tmp/antigravity_v1_lock_best_product_fix3_20260605_full_gate.json",
  target_role: "Product Analyst",
  years_experience: "3 years",
  candidate_name: "S. V. S. Apparao",
  turn_count: 15,
  map_available: true,
  report_available: true,
};

const replayState = {
  session_id: "replay_best_product_mock",
  question_count: 0,
  interview_complete: false,
  resume: "S. V. S. Apparao\nProduct analyst with ecommerce experimentation experience.",
  target_role: "Product Analyst",
  years_experience: "3 years",
  last_question:
    "Hey, thanks so much for coming in. Let's start with the retention experiment: what exact user action defined the trial start?",
  parsed_resume: {
    name: "S. V. S. Apparao",
  },
  interview_trajectory_map: {
    focus_areas: [{ title: "Retention and conversion optimization" }],
  },
  history: [],
  replay_metadata: {
    case_id: replayCase.case_id,
    label: replayCase.label,
    zero_llm: true,
  },
};

test("replay launcher starts a saved case and opens the locked room", async ({ page }) => {
  await page.route("**/api/replay/cases", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ cases: [replayCase], count: 1 }),
    });
  });
  await page.route("**/api/replay/start", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: replayState.session_id,
        opening_question: replayState.last_question,
        turn_count: 15,
        candidate_name: replayCase.candidate_name,
        target_role: replayCase.target_role,
        zero_llm: true,
      }),
    });
  });
  await page.route("**/api/state/replay_best_product_mock", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(replayState),
    });
  });
  await page.route("**/api/replay/qa_capture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });

  await page.goto("/interview-room/replay");
  await expect(page.getByRole("heading", { name: "Locked Room Runtime Replay" })).toBeVisible();
  await expect(page.getByText("Best Product Replay")).toBeVisible();
  await expect(page.getByText("map")).toBeVisible();
  await expect(page.getByText("report")).toBeVisible();

  await page.getByRole("button", { name: "Full replay" }).click();
  await expect(page).toHaveURL(/\/interview-room\/replay_best_product_mock/);
  await expect(page.getByText("S. V. S. Apparao - Product Analyst")).toBeVisible();
  await expect(page.getByText("Interviewer's question")).toBeVisible();
  await expect(page.getByText("retention experiment", { exact: false })).toBeVisible();
});

test("replay room emits passive layout QA captures", async ({ page }) => {
  let captureCount = 0;
  let lastPayload: Record<string, unknown> | null = null;
  await page.route("**/api/state/replay_best_product_mock", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(replayState),
    });
  });
  await page.route("**/api/replay/qa_capture", async (route) => {
    const requestPayload = JSON.parse(route.request().postData() || "{}");
    captureCount += 1;
    lastPayload = requestPayload.payload;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });

  await page.goto("/interview-room/replay_best_product_mock");
  await expect(page.getByText("Interviewer's question")).toBeVisible();
  await expect.poll(() => captureCount, { timeout: 4_000 }).toBeGreaterThan(0);
  expect(lastPayload?.phase).toBe("ready");
  expect((lastPayload?.boxes as Record<string, unknown>).question_card).toBeTruthy();
  expect((lastPayload?.overlaps as Record<string, unknown>).question_right_rail).toBe(false);
});
