import { defineConfig, devices } from "@playwright/test";

const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT || "8000";
const frontendPort = process.env.PLAYWRIGHT_FRONTEND_PORT || "3000";
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const frontendCommand =
  process.env.PLAYWRIGHT_NEXT_START === "1"
    ? `NEXT_PUBLIC_API_URL=${backendUrl} npm run start -- -p ${frontendPort}`
    : `NEXT_PUBLIC_API_URL=${backendUrl} npm run dev -- -p ${frontendPort}`;

export default defineConfig({
  testDir: "tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: frontendUrl,
    channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: `python3 -u -m uvicorn backend.main:app --host 127.0.0.1 --port ${backendPort}`,
      url: `${backendUrl}/api/tts_health`,
      reuseExistingServer: true,
      timeout: 90_000,
    },
    {
      command: frontendCommand,
      url: `${frontendUrl}/simulation`,
      reuseExistingServer: true,
      timeout: 90_000,
    },
  ],
});
