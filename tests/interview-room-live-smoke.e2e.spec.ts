import { expect, test } from "@playwright/test";

const sessionId = process.env.LIVE_ROOM_SESSION_ID;

test.use({
  permissions: ["camera", "microphone"],
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
});

test.skip(!sessionId, "Set LIVE_ROOM_SESSION_ID to run the live room smoke test.");

test("live room can enter an active backend session", async ({ page }) => {
  test.setTimeout(90_000);
  const pageErrors: string[] = [];
  const consoleMessages: string[] = [];
  const badResponses: Array<{ status: number; url: string }> = [];
  let statePayload: Record<string, unknown> | null = null;
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleMessages.push(`${msg.type()}: ${msg.text()}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      badResponses.push({ status: response.status(), url: response.url() });
    }
  });

  const stateResponsePromise = page.waitForResponse(
    (response) => response.url().includes(`/api/state/${sessionId}`),
    { timeout: 15_000 },
  ).catch(() => null);
  await page.goto(`/interview-room/${sessionId}`);
  const stateResponse = await stateResponsePromise;
  if (stateResponse) {
    statePayload = await stateResponse.json().catch(() => null);
  }

  await expect(page.getByText("Antigravity Interview", { exact: true })).toBeVisible();
  await expect(page.getByText("Turn history", { exact: true })).toBeVisible();
  try {
    await expect(page.getByText("S. V. S. Apparao - Product Analyst")).toBeVisible({ timeout: 15_000 });
  } catch (err) {
    console.log("live-room-prestart-diagnostics", {
      url: page.url(),
      stateStatus: stateResponse?.status() ?? null,
      stateKeys: statePayload ? Object.keys(statePayload) : [],
      stateCandidate: (statePayload?.parsed_resume as Record<string, unknown> | undefined)?.name,
      stateRole: statePayload?.target_role,
      stateQuestion: statePayload?.last_question,
      pageErrors,
      consoleMessages,
      badResponses,
      text: await page.locator("main").innerText(),
    });
    throw err;
  }
  await expect(page.getByText("Interviewer's question")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run session" })).toBeEnabled();

  await page.getByRole("button", { name: "Run session" }).click();

  await expect(page.getByText("Mic ready", { exact: true })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Hey, thanks so much for coming in", { exact: false })).toBeVisible({
    timeout: 45_000,
  });
  console.log("live-room-diagnostics", {
    pageErrors,
    consoleMessages,
    startButtonCount: await page.getByRole("button", { name: "Starting..." }).count(),
    text: await page.locator("main").innerText(),
  });

  await expect(page.getByText("Interviewer's question")).toBeVisible();

  await expect(page.getByText("Internal Server Error", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Could not start interview", { exact: false })).toHaveCount(0);
});
