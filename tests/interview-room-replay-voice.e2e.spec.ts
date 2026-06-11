import { expect, test } from "@playwright/test";

const apiBase = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "").endsWith("/api")
  ? (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "")
  : `${(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "")}/api`;

const fakeAudioFile = process.env.REPLAY_FAKE_AUDIO_FILE || "";

test.use({
  permissions: ["camera", "microphone"],
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      ...(fakeAudioFile ? [`--use-file-for-fake-audio-capture=${fakeAudioFile}`] : []),
    ],
  },
});

test.skip(process.env.REPLAY_VOICE_QA !== "1", "Set REPLAY_VOICE_QA=1 to spend Deepgram/TTS on replay voice QA.");
test.skip(!fakeAudioFile, "Set REPLAY_FAKE_AUDIO_FILE to a local WAV fixture for automated voice replay.");

test("replay voice QA exercises Deepgram, TTS, layout capture, and zero-LLM guard", async ({ page, request }) => {
  test.setTimeout(140_000);
  const casesRes = await request.get(`${apiBase}/replay/cases`);
  expect(casesRes.ok()).toBeTruthy();
  const casesPayload = await casesRes.json();
  const selected = casesPayload.cases?.find((item: { turn_count?: number }) => (item.turn_count || 0) >= 3)
    || casesPayload.cases?.[0];
  expect(selected?.case_id).toBeTruthy();

  const startRes = await request.post(`${apiBase}/replay/start`, {
    data: { case_id: selected.case_id, max_turns: 3 },
  });
  expect(startRes.ok()).toBeTruthy();
  const started = await startRes.json();
  const sessionId = started.session_id as string;

  await page.goto(`/interview-room/${sessionId}`);
  await expect(page.getByText("Interviewer's question")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Run session" }).click();

  await expect(page.getByText("Mic ready", { exact: true })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Candidate answer live transcription", { exact: false })).toBeVisible({
    timeout: 90_000,
  });

  await expect.poll(async () => {
    const telemetry = await request.get(`${apiBase}/telemetry/${sessionId}?limit=500`);
    const payload = await telemetry.json();
    return Number(payload.events?.["replay.process_turn"] || payload.events?.["api.process_turn"] || 0);
  }, { timeout: 90_000 }).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Need a moment" }).click();
  await page.getByRole("button", { name: "Hide stream" }).click();
  await page.getByRole("button", { name: "Collapse" }).click();

  const reportRes = await request.get(`${apiBase}/replay/qa_report/${sessionId}`);
  expect(reportRes.ok()).toBeTruthy();
  const report = await reportRes.json();
  expect(report.checks.zero_llm_guard.passed).toBeTruthy();
  expect(report.checks.tts_recorded.passed).toBeTruthy();
  expect(report.checks.partials_recorded.passed).toBeTruthy();
  expect(report.checks.layout_captures_recorded.passed).toBeTruthy();
});
