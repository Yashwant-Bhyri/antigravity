import { expect, test } from "@playwright/test";

const roomState = {
  session_id: "room-fixture",
  question_count: 0,
  interview_complete: false,
  resume: "S. V. S. Apparao\nProduct analyst with ecommerce experimentation experience.",
  target_role: "Product Analyst",
  years_experience: "3 years experience",
  last_question:
    "Now make it candidate-facing: how would you explain that uncertainty to a product manager without sounding vague?",
  parsed_resume: {
    name: "S. V. S. Apparao",
  },
  interview_trajectory_map: {
    focus_areas: [{ title: "Product analytics reasoning" }],
  },
  history: [
    {
      question: "What is the first probe you would run if one cohort improves but total retention gets worse?",
      answer:
        "I would check acquisition mix and cohort sizes, then compare weighted retention before and after the change.",
    },
    {
      question:
        "If the dashboard shows a conversion drop, how would you separate a real product issue from bad event instrumentation?",
      answer:
        "I would compare raw event volume, schema changes, funnel step counts, and a holdout metric before calling it a product regression.",
    },
    {
      question:
        "You said holdout metric. Which one would you trust if the checkout event itself might be corrupted?",
      answer:
        "I would trust an upstream intent signal like payment-page reach plus backend order creation, then reconcile it against client-side checkout events.",
    },
  ],
};

test("live interview room renders backend state without simulator leakage", async ({ page }) => {
  await page.route("**/api/state/room-fixture", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(roomState),
    });
  });

  await page.goto("/interview-room/room-fixture");

  await expect(page.getByText("S. V. S. Apparao - Product Analyst")).toBeVisible();
  await expect(page.getByText("3 years experience")).toBeVisible();
  await expect(page.getByText("Interviewer's question")).toBeVisible();
  await expect(page.getByText(roomState.last_question)).toBeVisible();
  await expect(page.getByText("Antigravity Interview Room")).toHaveCount(0);
  await expect(page.getByText("This room uses the live interview backend")).toHaveCount(0);
  await expect(page.getByText("Latest turn")).toBeVisible();
  await expect(page.getByText("Prior turn")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Run session" })).toBeVisible();

  await expect(page.getByText("prototype mode", { exact: false })).toHaveCount(0);
  await expect(page.getByText("monotonic fencing token", { exact: false })).toHaveCount(0);

  await page.getByRole("button", { name: "Show full transcript" }).click();
  await expect(page.getByRole("button", { name: "Hide full transcript" })).toBeVisible();

  await page.getByRole("button", { name: "Collapse" }).click();
  await expect(page.getByRole("button", { name: "Turn history" })).toBeVisible();
  await expect(page.getByText(roomState.last_question)).toBeVisible();
});

test("completed live interview room hydrates into closing state", async ({ page }) => {
  await page.route("**/api/state/room-complete", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...roomState,
        session_id: "room-complete",
        question_count: 15,
        interview_complete: true,
        last_question: "",
      }),
    });
  });

  await page.goto("/interview-room/room-complete");

  await expect(page.getByRole("heading", { name: "Report is being prepared" })).toBeVisible();
  await expect(page.getByText("AI interviewer is closing the interview")).toBeVisible();
  await expect(page.getByText("Interview room is ready")).toHaveCount(0);
});
