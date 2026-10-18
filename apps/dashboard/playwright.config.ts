import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)), "..", "..");
const runId = process.env.MIRAGE_BROWSER_RUN_ID ?? randomUUID();
if (!/^[A-Za-z0-9-]+$/.test(runId)) throw new Error("Invalid isolated browser run ID");
process.env.MIRAGE_BROWSER_RUN_ID = runId;
const data = resolve(root, ".local", "browser-qa", runId);
const python = resolve(root, ".venv", "Scripts", "python.exe");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: resolve(root, ".local", "browser-results"),
  use: {
    baseURL: "http://127.0.0.1:8797",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    headless: true,
    reducedMotion: "reduce",
  },
  webServer: {
    command: `"${python}" -m mirage run`,
    cwd: root,
    url: "http://127.0.0.1:8797/health",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      MIRAGE_DATA_DIR: data,
      MIRAGE_PROFILE: "P1-native",
      MIRAGE_LOCAL_LOGIN: "true",
      MIRAGE_DATABASE_URL: "",
      MIRAGE_BACKEND_URL: "http://127.0.0.1:8798",
      MIRAGE_ACCESS_CODE: "",
      MIRAGE_BACKEND_SECRET: "",
      MIRAGE_API_PORT: "8797",
      MIRAGE_BACKEND_PORT: "8798",
      MIRAGE_MODEL_PROVIDER: "fixture",
      MIRAGE_MODEL_EGRESS_APPROVED: "false",
      MIRAGE_DECOY_MODEL_WORDING: "false",
      MIRAGE_MODEL_CALL_BUDGET: "100",
      MIRAGE_MODEL_CASE_CALL_BUDGET: "3",
      MIRAGE_MODEL_MAX_PENDING: "4",
      MIRAGE_MODEL_INPUT_BYTES: "65536",
      MIRAGE_MODEL_TIMEOUT_SECONDS: "12",
      MIRAGE_GEMINI_PROJECT: "",
      MIRAGE_GEMINI_API_KEY: "",
      MIRAGE_GEMINI_ENDPOINT: "auto",
      MIRAGE_GEMINI_LOCATION: "global",
      MIRAGE_GEMINI_MODEL: "",
      MIRAGE_SESSION_TTL_SECONDS: "900",
      MIRAGE_DECOY_REQUEST_BUDGET: "100",
      MIRAGE_MAX_ENGAGEMENTS: "10",
      MIRAGE_TELEGRAM_MODE: "webhook",
      MIRAGE_TELEGRAM_BOT_TOKEN: "123456:qa-fake-token-not-a-real-bot-0000",
      MIRAGE_TELEGRAM_WEBHOOK_SECRET: "qa-webhook-secret-0123456789abcdef",
      MIRAGE_TELEGRAM_API_BASE: "http://127.0.0.1:9",
      MIRAGE_PUBLIC_URL: "http://127.0.0.1:8797",
      MIRAGE_ALLOWED_ORIGINS: JSON.stringify(["http://127.0.0.1:8797"]),
    },
    stdout: "ignore",
    stderr: "pipe",
  },
});
