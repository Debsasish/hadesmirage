import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type {
  AIProviderCheck,
  BackendEvidence,
  CaseDetail,
  ImportedReport,
  ReportSummary,
  ScenarioResult,
} from "../src/types";

const root = resolve(process.cwd(), "..", "..");
const artifacts = resolve(root, ".local", "browser-artifacts", `${Date.now()}-${process.pid}`);
mkdirSync(artifacts, { recursive: true });

function launchCode() {
  const runId = process.env.MIRAGE_BROWSER_RUN_ID;
  if (!runId || !/^[A-Za-z0-9-]+$/.test(runId))
    throw new Error("The browser run has no isolated native data directory");
  const value: unknown = JSON.parse(
    readFileSync(resolve(root, ".local", "browser-qa", runId, "runtime-secrets.json"), "utf-8"),
  );
  if (
    typeof value !== "object" ||
    value === null ||
    !("access_code" in value) ||
    typeof value.access_code !== "string"
  )
    throw new Error("Native test launcher did not create its private local code");
  return value.access_code;
}

async function waitForSeed() {
  const runId = process.env.MIRAGE_BROWSER_RUN_ID ?? "";
  const marker = resolve(root, ".local", "browser-qa", runId, "demo-seed.json");
  const deadline = Date.now() + 90_000;
  while (!existsSync(marker)) {
    if (Date.now() > deadline) throw new Error("Native launcher did not finish seeding scenarios");
    await new Promise((done) => setTimeout(done, 250));
  }
}

async function login(page: Page, role = "admin", lens: "plain" | "technical" = "technical") {
  await waitForSeed();
  await page.addInitScript((value) => localStorage.setItem("mirage.lens", value), lens);
  await page.goto("/login");
  await page.getByLabel("Local identity", { exact: true }).selectOption(role);
  await page.getByLabel("Local access code", { exact: true }).fill(launchCode());
  await page.getByRole("button", { name: "Open analyst console" }).click();
  await expect(page.getByRole("heading", { name: "Risk overview", exact: true })).toBeVisible();
}

async function expectTopologyLabelsClear(page: Page) {
  const overlaps = await page
    .locator(".topology-zone > span, .native-path-label")
    .evaluateAll((labels) => {
      const nodes = [...document.querySelectorAll(".topology-node")];
      return labels.flatMap((label) => {
        const bounds = label.getBoundingClientRect();
        return nodes
          .filter((node) => {
            const box = node.getBoundingClientRect();
            return (
              Math.min(bounds.right, box.right) - Math.max(bounds.left, box.left) > 1 &&
              Math.min(bounds.bottom, box.bottom) - Math.max(bounds.top, box.top) > 1
            );
          })
          .map((node) => `${label.textContent} / ${node.textContent}`);
      });
    });
  expect(overlaps).toEqual([]);
}

async function authorized(page: Page, path: string, body: unknown, method = "POST") {
  return page.evaluate(
    async ({ path, body, method }) => {
      const identity = (await fetch("/auth/me").then((response) => response.json())) as {
        csrf: string;
      };
      const response = await fetch(path, {
        method,
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          "X-CSRF-Token": identity.csrf,
        },
        body: JSON.stringify(body),
      });
      return { status: response.status, body: (await response.json()) as Record<string, unknown> };
    },
    { path, body, method },
  );
}

async function scenario(page: Page, name = "external-probing") {
  await authorized(page, "/v1/settings", { engagements_enabled: true }, "PATCH");
  await page.goto("/overview");
  await page.getByRole("button", { name: "Run lab scenario", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Scenario", { exact: true }).selectOption(name);
  const response = page.waitForResponse(
    (request) =>
      request.url().endsWith("/v1/laboratory/run") && request.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Run scenario", exact: true }).click();
  const result = (await (await response).json()) as ScenarioResult;
  await expect(dialog.getByRole("heading", { name: "Execution recorded" })).toBeVisible();
  return result;
}

test("all nine screens show API-backed records without runtime errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  for (const [path, heading] of [
    ["/overview", "Risk overview"],
    ["/incidents", "Issues"],
    ["/agents", "AI agents"],
    ["/guardrails", "Access rules"],
    ["/deception", "Honeypot"],
    ["/architecture", "Attack map"],
    ["/integrations", "Integrations"],
    ["/audit", "Reports"],
    ["/settings", "Settings"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(page.getByText("Unable to load this view", { exact: true })).toHaveCount(0);
    if (path === "/architecture") await expectTopologyLabelsClear(page);
  }
  expect(errors).toEqual([]);
});

test("the real diversion workflow shows zero prohibited backend mutations and cited evidence", async ({
  page,
}) => {
  await login(page);
  const result = await scenario(page);
  expect(result.backend_effect_delta.production_reads).toBe(0);
  expect(result.backend_effect_delta.production_mutations).toBe(0);
  expect(result.session.history.map((entry) => entry.mode)).toEqual([
    "PRODUCTION",
    "RESTRICTED",
    "DECOY_PENDING",
    "DECOY",
  ]);
  await page.getByRole("button", { name: "Open incident workbench" }).click();
  await expect(page.getByRole("heading", { name: "Evidence timeline" })).toBeVisible();
  await page.getByRole("button", { name: "Investigate evidence", exact: true }).click();
  await expect(page.getByText("Deterministic fixture output", { exact: true })).toBeVisible();
  await page.locator(".evidence-refs button").first().click();
  await expect(page.getByRole("heading", { name: "Evidence detail", exact: true })).toBeVisible();
  await expect(page.getByText("Immutable body digest", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Evidence timeline" })).toBeVisible();
  await page.screenshot({ path: resolve(artifacts, "incident-dark.png"), fullPage: true });
});

test("dark and light themes pass serious/critical WCAG checks on overview and preserve theme", async ({
  page,
}) => {
  await login(page);
  for (const theme of ["dark", "light"]) {
    if (theme === "light")
      await page.getByRole("button", { name: "Switch to light theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.evaluate(async () => {
      await document.fonts.ready;
      await new Promise<void>((done) =>
        requestAnimationFrame(() => requestAnimationFrame(() => done())),
      );
    });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
    ).toEqual([]);
    await page.screenshot({ path: resolve(artifacts, `overview-${theme}.png`), fullPage: true });
  }
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("policy simulator is explicitly non-executing and respects workload scope", async ({
  page,
}) => {
  await login(page);
  await page.goto("/agents");
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as {
    production_mutations: number;
    production_reads: number;
  };
  await page.getByLabel("Acting agent", { exact: true }).selectOption("agent-audit");
  await page.getByRole("button", { name: "Evaluate policy" }).click();
  await expect(page.getByText("RESOURCE OUT OF SCOPE", { exact: true })).toBeVisible();
  await expect(page.getByText(/executed: false/)).toBeVisible();
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as {
    production_mutations: number;
    production_reads: number;
  };
  expect(after.production_mutations).toBe(before.production_mutations);
  expect(after.production_reads).toBe(before.production_reads);
});

test("independent approver reviews exact digest then admin executes only once", async ({
  page,
}) => {
  await login(page);
  const result = await scenario(page, "blocked-payment");
  expect(result.backend_effect_delta.production_mutations).toBe(0);
  const approval = result.approval;
  expect(approval).not.toBeNull();
  if (!approval) throw new Error("Bounded scenario did not create an approval");
  await page.getByRole("dialog").getByRole("button", { name: "Close dialog" }).click();
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as { production_mutations: number };
  await page.getByRole("button", { name: "Open account menu" }).click();
  await page.getByRole("button", { name: "Sign out / switch role" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "approver");
  await page.goto("/guardrails?tab=approvals");
  const card = page.locator("section.panel").filter({ hasText: approval.id });
  await expect(card.getByText(approval.digest, { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Approve one execution", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Approve exact action", exact: true })
    .click();
  await expect(card.getByText("approved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open account menu" }).click();
  await page.getByRole("button", { name: "Sign out / switch role" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "admin");
  await page.goto("/guardrails?tab=approvals");
  const adminCard = page.locator("section.panel").filter({ hasText: approval.id });
  await adminCard.getByRole("button", { name: "Execute reviewed lab action" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Execute synthetic change once" })
    .click();
  await expect(adminCard.getByText("consumed", { exact: true })).toBeVisible();
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as { production_mutations: number };
  expect(after.production_mutations - before.production_mutations).toBe(1);
  const retry = await authorized(page, "/v1/laboratory/run", {
    scenario: "approved-payment",
    approval_id: approval.id,
  });
  expect(retry.status).toBe(200);
  const final = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as { production_mutations: number };
  expect(final.production_mutations).toBe(after.production_mutations);
});

test("stored attacker HTML is inert and never creates external requests", async ({ page }) => {
  await login(page);
  const result = await scenario(page);
  await page.getByRole("button", { name: "Open incident workbench" }).click();
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    if (!request.url().startsWith("http://127.0.0.1:8797") && !request.url().startsWith("data:"))
      externalRequests.push(request.url());
  });
  const payload = '<img src="https://example.invalid/untrusted" onerror="window.__mirageXss=1">';
  await page.getByLabel("Analyst note", { exact: true }).fill(payload);
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await expect(page.getByText(payload, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => Reflect.get(window, "__mirageXss"))).toBeUndefined();
  expect(externalRequests).toEqual([]);
  const response = await page.request.get(`/v1/incidents/${result.incident_id}/export?format=html`);
  const html = await response.text();
  expect(html).toContain("&lt;img");
  expect(html).not.toContain('<img src="https://example.invalid');
});

test("keyboard search, topology selection and source filters remain usable", async ({ page }) => {
  await login(page);
  await page.keyboard.press("Control+k");
  await page.getByLabel("Search incidents and agents", { exact: true }).fill("procurement");
  await page.getByRole("link", { name: /Procurement assistant/ }).click();
  await expect(
    page.getByRole("heading", { name: "Agent authority & recent evidence" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/architecture");
  await page.getByRole("button", { name: /Wasm supplier decoy/ }).click();
  await expect(
    page.getByRole("heading", { name: "Wasm supplier decoy", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Inspect dispatcher to gateway/ }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "dispatcher to gateway", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("mTLS HTTP/2 CONNECT (proposed)", { exact: true }).last(),
  ).toBeVisible();
  await page.screenshot({ path: resolve(artifacts, "architecture-dark.png"), fullPage: true });
  await page.goto("/incidents");
  await page.getByLabel("Filter severity", { exact: true }).selectOption("high");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: /Boards/ })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: /^Issues/ })
    .click();
  await expect(page.getByLabel("Filter severity", { exact: true })).toHaveValue("high");
});

test("live attack map traces an attacker from the front door into the honeypot", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page, "admin", "plain");
  const result = await scenario(page);
  expect(result.session.route_mode).toBe("DECOY");
  await page.goto("/architecture");
  await expect(page.getByRole("heading", { name: "Attack map", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live attack traffic" })).toBeVisible();
  const summary = page.getByRole("list", { name: "Attack map summary" });
  await expect(summary.getByText("Requests checked", { exact: true })).toBeVisible();
  await expect(summary.getByText("Real data touched after catch", { exact: true })).toBeVisible();
  await expect(page.locator(".map-pill").filter({ hasText: "sent to honeypot" })).toBeVisible();

  const map = (await (await page.request.get("/v1/attack-map?hours=168")).json()) as {
    ledger: { available: boolean; after_containment: number };
    attackers: { session_id: string; route_mode: string; edges: string[] }[];
  };
  expect(map.ledger.available).toBe(true);
  expect(map.ledger.after_containment).toBe(0);
  const traced = map.attackers.find((item) => item.session_id === result.session.id);
  expect(traced?.edges).toContain("limited-honeypot");

  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(page.getByRole("button", { name: "Paused", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Blocked \d+ requests?$/ }).click();
  const inspector = page.getByRole("complementary", { name: "Attack map details" });
  await expect(inspector.getByRole("heading", { name: "Blocked", exact: true })).toBeVisible();
  await expect(inspector.getByText("Why requests were blocked")).toBeVisible();

  await page
    .getByRole("button", {
      name: `Show path for External laboratory client ${result.session.id.slice(0, 8)}`,
    })
    .click();
  await expect(
    inspector.getByRole("heading", { name: "External laboratory client", exact: true }),
  ).toBeVisible();
  const path = inspector.getByRole("list", { name: "Path through the map" });
  await expect(path).toContainText("Front door checks");
  await expect(path).toContainText("Access limited");
  await expect(path).toContainText("Honeypot");
  await expect(page.locator(".map-node.is-dim").first()).toBeVisible();
  await page.screenshot({ path: resolve(artifacts, "attack-map-trace.png"), fullPage: true });

  await inspector.getByRole("button", { name: "Open issue", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Issue details" });
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);

  await page.getByRole("button", { name: "Technical view", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Live L7 traffic flow" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^deny \d+ requests?$/ })).toBeVisible();
  for (const theme of ["dark", "light"]) {
    if (theme === "light")
      await page.getByRole("button", { name: "Switch to light theme" }).click();
    const results = await new AxeBuilder({ page })
      .include(".live-map")
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
    ).toEqual([]);
  }
  expect(errors).toEqual([]);
});

test("mobile navigation and containment of wide evidence/topology layouts", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("dialog").getByRole("link", { name: "Attack map" }).click();
  await expect(page.getByRole("heading", { name: "Attack map", exact: true })).toBeVisible();
  await expectTopologyLabelsClear(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: resolve(artifacts, "architecture-mobile.png"), fullPage: true });
  await page.goto("/overview");
  await expect(page.getByRole("heading", { name: "Risk overview", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: resolve(artifacts, "overview-mobile.png"), fullPage: true });
});

test("loading, empty, error and permission-denied states are explicit", async ({ page }) => {
  await login(page);
  await page.route("**/v1/incidents?**", async (route) => {
    await new Promise((done) => setTimeout(done, 700));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    });
  });
  await page.goto("/incidents");
  await expect(
    page.getByRole("status").filter({ hasText: "Loading recorded evidence" }),
  ).toBeVisible();
  await expect(page.getByText("No incidents in this view", { exact: true })).toBeVisible();
  await page.unroute("**/v1/incidents?**");
  await page.route("**/v1/incidents?**", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ code: "ROLE_REQUIRED", message: "Denied by test fixture" }),
    }),
  );
  await page.reload();
  await expect(
    page.getByText("Permission denied. Your verified role cannot access this operation.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({ path: resolve(artifacts, "permission-denied.png"), fullPage: true });
  await page.unroute("**/v1/incidents?**");
  await page.route("**/v1/incidents?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: "STATE_UNAVAILABLE",
        message: "Authoritative store unavailable (test fixture)",
      }),
    }),
  );
  await page.reload();
  await expect(
    page.getByText("Authoritative store unavailable (test fixture)", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});

test("kill switch is confirmed and never restores production access", async ({ page }) => {
  await login(page);
  const result = await scenario(page);
  await page.getByRole("dialog").getByRole("button", { name: "Close dialog" }).click();
  await page.goto("/deception");
  await page.getByRole("button", { name: "Kill switch", exact: true }).click();
  await expect(page.getByText(/No session returns to production/)).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Terminate all decoy sessions", exact: true })
    .click();
  await expect(page.getByText("New engagements disabled", { exact: true })).toBeVisible();
  const response = await page.request.get(`/v1/sessions/${result.session.id}`);
  expect(((await response.json()) as { route_mode: string }).route_mode).toBe("TERMINATED");
  await page.screenshot({ path: resolve(artifacts, "deception-stopped.png"), fullPage: true });
});

test("policy editor requires fixture tests and separate review before activation and rollback", async ({
  page,
}) => {
  await login(page);
  await page.goto("/guardrails");
  await page.getByRole("button", { name: "Create new draft", exact: true }).click();
  const version = `policy-ui-${Date.now()}`;
  const editor = page.getByRole("dialog");
  await editor.getByLabel("New immutable version", { exact: true }).fill(version);
  await editor.getByRole("button", { name: "Compare with active policy" }).click();
  await expect(editor.getByText("Current active version", { exact: true })).toBeVisible();
  await editor.getByRole("button", { name: "Save draft", exact: true }).click();
  await page.locator(".policy-list button").filter({ hasText: version }).click();
  await page.getByRole("button", { name: "Test fixtures", exact: true }).click();
  await expect(page.getByText("Fixtures passed", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review exact version", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Open account menu" }).click();
  await page.getByRole("button", { name: "Sign out / switch role" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "approver");
  await page.goto("/guardrails");
  await page.locator(".policy-list button").filter({ hasText: version }).click();
  await page.getByRole("button", { name: "Review exact version", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Record separate review", exact: true })
    .click();
  await expect(
    page.locator(".policy-grid > section").last().getByText("reviewed", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open account menu" }).click();
  await page.getByRole("button", { name: "Sign out / switch role" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "admin");
  await page.goto("/guardrails");
  await page.locator(".policy-list button").filter({ hasText: version }).click();
  await page.getByRole("button", { name: "Activate reviewed version", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Activate reviewed version", exact: true })
    .click();
  await expect(
    page.locator(".policy-grid > section").last().getByText("active", { exact: true }),
  ).toBeVisible();
  await page.locator(".policy-list button").filter({ hasText: "policy-demo-v1" }).click();
  await page.getByRole("button", { name: "Rollback to this version", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Activate reviewed version", exact: true })
    .click();
  await expect(
    page.locator(".policy-grid > section").last().getByText("active", { exact: true }),
  ).toBeVisible();
});

test("overview case preview is keyboard-operable and does not dispatch backend operations", async ({
  page,
}) => {
  await login(page);
  const run = await scenario(page);
  await page.getByRole("dialog").getByRole("button", { name: "Close dialog" }).click();
  await page.goto("/overview");
  await expect(page.locator(".case-peek h3")).toBeVisible();
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as {
    production_reads: number;
    production_mutations: number;
  };
  const first = page.locator(".queue-case").first();
  await first.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator(".queue-case").nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".case-peek h3")).toBeVisible();
  await page.locator(".case-peek").getByRole("button", { name: "Route", exact: true }).click();
  await expect(page.getByRole("list", { name: "Session route history" })).toBeVisible();
  expect(page.url()).toContain("/overview");
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as {
    production_reads: number;
    production_mutations: number;
  };
  expect(after.production_reads).toBe(before.production_reads);
  expect(after.production_mutations).toBe(before.production_mutations);
  expect(run.backend_effect_delta.production_mutations).toBe(0);
});

test("compact navigation persists without losing access to the nine views", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Collapse navigation", exact: true }).click();
  await expect(page.locator(".app-shell")).toHaveClass(/sidebar-compact/);
  expect(
    await page
      .locator("aside.sidebar")
      .evaluate((element) => element.getBoundingClientRect().width),
  ).toBeLessThan(100);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "AI agents", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "AI agents", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.locator(".app-shell")).toHaveClass(/sidebar-compact/);
  await page.getByRole("button", { name: "Expand navigation", exact: true }).click();
  await expect(page.locator(".app-shell")).not.toHaveClass(/sidebar-compact/);
});

test("overview refresh controls and metric links have explicit, working scope", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "Pause auto refresh", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume auto refresh", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  const refreshed = page.waitForResponse(
    (response) => response.url().includes("/v1/overview?") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Refresh workspace records", exact: true }).click();
  await refreshed;
  await page.evaluate(() =>
    localStorage.setItem(
      "mirage.filters.audit",
      JSON.stringify({ q: "", outcome: "allow", source: "" }),
    ),
  );
  await page.locator(".summary-figure").filter({ hasText: "Denied operations" }).click();
  await expect(page.getByLabel("Filter event outcome", { exact: true })).toHaveValue("deny");
});

test("sign-in role guidance and optional code visibility do not bypass authentication", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Local identity", { exact: true }).selectOption("analyst");
  await expect(
    page.getByText("Work the case without widening authority.", { exact: true }),
  ).toBeVisible();
  const code = page.getByLabel("Local access code", { exact: true });
  await code.fill("not-a-real-launch-code");
  await page.getByRole("button", { name: "Show local access code", exact: true }).click();
  await expect(code).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Hide local access code", exact: true }).click();
  await expect(code).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Open analyst console", exact: true }).click();
  await expect(page.getByText("Incorrect local access code", { exact: true })).toBeVisible();
  expect((await page.request.get("/v1/incidents")).status()).toBe(401);
});

test("route lens inspects real historical evidence without changing the current route or backend", async ({
  page,
}) => {
  await login(page);
  const run = await scenario(page);
  if (!run.incident_id) throw new Error("The laboratory sequence did not produce a case");
  await page.getByRole("dialog").getByRole("button", { name: "Close dialog" }).click();
  const detail = (await page.request
    .get(`/v1/incidents/${run.incident_id}`)
    .then((response) => response.json())) as CaseDetail;
  await page.goto("/overview");
  await page.locator(".queue-case").filter({ hasText: detail.incident.number }).click();
  await page.locator(".case-peek").getByRole("button", { name: "Route", exact: true }).click();
  const lens = page.locator(".case-peek .route-lens");
  await expect(lens).toHaveAttribute("data-route", "DECOY");
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as {
    production_reads: number;
    production_mutations: number;
  };
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") writes.push(request.url());
  });
  await lens.getByLabel("Inspect route history", { exact: true }).focus();
  await page.keyboard.press("Home");
  await expect(lens).toHaveAttribute("data-route", "PRODUCTION");
  await expect(lens.getByText("Historical state", { exact: true })).toBeVisible();
  await expect(lens.locator(".lens-current-route")).toContainText("DECOY");
  const productionEvents = detail.events.filter(
    (event) => event.body.route_mode === "PRODUCTION",
  ).length;
  await expect(lens.locator(".lens-observation-counts")).toContainText(
    `${productionEvents} linked in this route`,
  );
  await page.getByRole("button", { name: "Focus route lens", exact: true }).click();
  const focused = page.getByRole("dialog");
  await expect(
    focused.getByRole("heading", { name: `Route lens / ${detail.incident.number}`, exact: true }),
  ).toBeVisible();
  await expect(focused.locator(".route-lens")).toHaveAttribute("data-route", "PRODUCTION");
  await focused.getByRole("button", { name: /Restricted.*v2/ }).click();
  await expect(focused.locator(".route-lens")).toHaveAttribute("data-route", "RESTRICTED");
  await expect(focused.getByText(/Already committed work was not undone/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(lens).toHaveAttribute("data-route", "RESTRICTED");
  await lens.getByRole("button", { name: "Latest", exact: true }).click();
  await expect(lens).toHaveAttribute("data-route", "DECOY");
  const current = (await page.request
    .get(`/v1/sessions/${run.session.id}`)
    .then((response) => response.json())) as { route_mode: string; route_version: number };
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as {
    production_reads: number;
    production_mutations: number;
  };
  expect(current).toMatchObject({
    route_mode: run.session.route_mode,
    route_version: run.session.route_version,
  });
  expect(after.production_reads).toBe(before.production_reads);
  expect(after.production_mutations).toBe(before.production_mutations);
  expect(writes).toEqual([]);
  await page.screenshot({ path: resolve(artifacts, "soc-route-lens.png"), fullPage: true });
});

test("reduced transparency is a persistent appearance preference, not an enforcement setting", async ({
  page,
}) => {
  await login(page);
  await page.goto("/settings");
  const control = page.getByRole("switch", { name: "Translucent surfaces", exact: true });
  await expect(control).toHaveAttribute("aria-checked", "true");
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") writes.push(request.url());
  });
  await control.click();
  await expect(page.locator("html")).toHaveAttribute("data-transparency", "solid");
  await page.reload();
  await expect(control).toHaveAttribute("aria-checked", "false");
  await page.goto("/overview");
  await expect(page.getByRole("heading", { name: "Risk overview", exact: true })).toBeVisible();
  const style = await page.locator(".topbar").evaluate((element) => {
    const value = getComputedStyle(element);
    return { filter: value.backdropFilter, background: value.backgroundColor };
  });
  expect(style.filter).toBe("none");
  expect(style.background).toMatch(/^rgb\(/);
  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    accessibility.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
  ).toEqual([]);
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  const lightAccessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    lightAccessibility.violations.filter((item) =>
      ["serious", "critical"].includes(item.impact ?? ""),
    ),
  ).toEqual([]);
  expect(writes).toEqual([]);
});

test("SOC workbench remains usable on mobile and with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await login(page);
  await page.getByRole("button", { name: "Pause auto refresh", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume auto refresh", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".case-peek h3")).toBeVisible();
  await page.locator(".case-peek").getByRole("button", { name: "Route", exact: true }).click();
  await page.getByRole("button", { name: "Focus route lens", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("slider", { name: "Inspect route history", exact: true }),
  ).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  if (bounds) expect(bounds.x + bounds.width).toBeLessThanOrEqual(391);
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const moving = await page.evaluate(
    () => document.getAnimations().filter((animation) => animation.playState === "running").length,
  );
  expect(moving).toBe(0);
  await page.screenshot({ path: resolve(artifacts, "soc-mobile.png"), fullPage: true });
});

test("SOC record search and severity distribution open the actual scoped filters", async ({
  page,
}) => {
  await login(page);
  await page.evaluate(() => {
    localStorage.setItem(
      "mirage.filters.incidents",
      JSON.stringify({
        q: "stale",
        severity: "low",
        status: "resolved",
        confidence: "low",
        source: "gateway",
        response: "DECOY",
        sort: "oldest",
      }),
    );
    localStorage.setItem(
      "mirage.filters.audit",
      JSON.stringify({ q: "stale", outcome: "deny", source: "gateway" }),
    );
  });
  await page.getByLabel("Search security records", { exact: true }).fill("procurement");
  await page
    .locator(".soc-record-search")
    .getByRole("button", { name: "Search", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Issues", exact: true })).toBeVisible();
  await expect(page.getByLabel("Search incidents", { exact: true })).toHaveValue("procurement");
  await expect(page.getByLabel("Filter severity", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Filter status", { exact: true })).toHaveValue("");
  await page.goto("/overview");
  await page.getByLabel("Security search scope", { exact: true }).selectOption("events");
  await page.getByLabel("Search security records", { exact: true }).fill("authorization.decided");
  await page
    .locator(".soc-record-search")
    .getByRole("button", { name: "Search", exact: true })
    .click();
  await expect(page.getByLabel("Search events", { exact: true })).toHaveValue(
    "authorization.decided",
  );
  await expect(page.getByLabel("Filter event outcome", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Filter event producer", { exact: true })).toHaveValue("");
  await page.goto("/overview");
  await page.locator(".distribution-legend").getByRole("link", { name: /high/i }).click();
  await expect(page.getByLabel("Filter severity", { exact: true })).toHaveValue("high");
  await expect(page.getByLabel("Search incidents", { exact: true })).toHaveValue("");
  await page.getByLabel("Filter status", { exact: true }).selectOption("investigating");
  await page.reload();
  await expect(page.getByLabel("Filter severity", { exact: true })).toHaveValue("high");
  await expect(page.getByLabel("Filter status", { exact: true })).toHaveValue("investigating");
});

test("SOC analyst queue search and progressive evidence inspection are read-only", async ({
  page,
}) => {
  await login(page);
  await expect(page.locator(".case-peek h3")).toBeVisible();
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") writes.push(request.url());
  });
  const firstReference = await page.locator(".queue-case > span").first().innerText();
  await page.getByLabel("Search analyst queue", { exact: true }).fill(firstReference);
  await expect(page.locator(".queue-case")).toHaveCount(1);
  await page.locator(".case-peek").getByRole("button", { name: "Evidence", exact: true }).click();
  await expect(
    page.getByText("Authenticated metadata. Untrusted text. Select any record to inspect it.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.locator(".inspector-events button").first().click();
  await expect(page.getByRole("heading", { name: "Evidence detail", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  expect(page.url()).toContain("/overview");
  expect(writes).toEqual([]);
});

test("AI provider checks are fixture-labelled, budgeted and administrator-only", async ({
  page,
}) => {
  await login(page);
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as BackendEvidence;
  await page.goto("/settings");
  const panel = page.locator(".ai-provider");
  await expect(panel).toContainText("not live AI");
  const checked = page.waitForResponse(
    (response) => response.url().endsWith("/v1/ai/check") && response.request().method() === "POST",
  );
  await panel.getByRole("button", { name: "Run fixture check", exact: true }).click();
  const result = (await (await checked).json()) as AIProviderCheck;
  expect(result.live).toBe(false);
  expect(result.provider).toBe("fixture-investigator-v1");
  await expect(
    panel.getByText(
      "Fixture check passed. This does not verify Gemini, credentials or live inference.",
      { exact: true },
    ),
  ).toBeVisible();
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as BackendEvidence;
  expect(after.production_reads).toBe(before.production_reads);
  expect(after.production_mutations).toBe(before.production_mutations);
  await page.screenshot({ path: resolve(artifacts, "ai-provider-fixture.png"), fullPage: true });
  await authorized(page, "/auth/logout", {});
  await login(page, "analyst");
  await page.goto("/settings");
  await expect(page.getByRole("button", { name: "Run fixture check", exact: true })).toBeDisabled();
  expect((await authorized(page, "/v1/ai/check", { allow_live: false })).status).toBe(403);
});

test("AI case questions persist with citations and never dispatch backend operations", async ({
  page,
}) => {
  await login(page);
  const run = await scenario(page);
  if (!run.incident_id) throw new Error("The bounded scenario did not create a case");
  await page.getByRole("button", { name: "Open incident workbench", exact: true }).click();
  const assistant = page.locator(".ai-assistant");
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as BackendEvidence;
  const answered = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/v1/incidents/${run.incident_id}/assistant`) &&
      response.request().method() === "POST",
  );
  await assistant
    .getByLabel("Question about this case", { exact: true })
    .fill("What do these denials establish?");
  await assistant.getByRole("button", { name: "Generate fixture answer", exact: true }).click();
  expect((await answered).status()).toBe(200);
  await expect(assistant.locator(".ai-record")).toHaveCount(1);
  await expect(assistant.locator(".ai-answer")).toContainText("deterministic fixture answer");
  await expect(assistant).toContainText("Fixture output / not live AI");
  await assistant.locator(".evidence-refs button").first().click();
  await expect(page.getByRole("heading", { name: "Evidence detail", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.reload();
  await expect(page.locator(".ai-assistant .ai-record")).toHaveCount(1);
  const detail = (await page.request
    .get(`/v1/incidents/${run.incident_id}`)
    .then((response) => response.json())) as CaseDetail;
  expect(detail.assistant[0].output?.case_id).toBe(run.incident_id);
  expect(detail.model_budget.used).toBe(1);
  const current = (await page.request
    .get(`/v1/sessions/${run.session.id}`)
    .then((response) => response.json())) as { route_mode: string; route_version: number };
  expect(current.route_mode).toBe(run.session.route_mode);
  expect(current.route_version).toBe(run.session.route_version);
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as BackendEvidence;
  expect(after.production_reads).toBe(before.production_reads);
  expect(after.production_mutations).toBe(before.production_mutations);
  await page.screenshot({ path: resolve(artifacts, "ai-case-question.png"), fullPage: true });
});

test("AI imported-report summaries stay metadata-only and focus local observations", async ({
  page,
}) => {
  await login(page);
  await page.goto("/integrations");
  await page.getByRole("button", { name: "Import Hades report", exact: true }).click();
  const modal = page.getByRole("dialog");
  await modal.getByLabel("Report JSON", { exact: true }).fill(
    JSON.stringify({
      source_version: "c".repeat(40),
      tool_count: 1,
      tools: [
        {
          name: "synthetic.review",
          risk_tier: "T3",
          issues: ["<b>Local scanner note, synthetic only.</b>"],
        },
      ],
    }),
  );
  const imported = page.waitForResponse(
    (response) =>
      response.url().endsWith("/v1/integrations/hades/import") &&
      response.request().method() === "POST",
  );
  await modal.getByRole("button", { name: "Validate & import report", exact: true }).click();
  const report = (await (await imported).json()) as ImportedReport;
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .locator("tr")
    .filter({ hasText: "cccccccccccc" })
    .getByRole("button", { name: "Inspect", exact: true })
    .click();
  const inspecting = page.getByRole("dialog");
  const summarized = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/v1/integrations/hades/${report.id}/summary`) &&
      response.request().method() === "POST",
  );
  await inspecting.getByRole("button", { name: "Generate fixture summary", exact: true }).click();
  const summary = (await (await summarized).json()) as ReportSummary;
  expect(summary.coverage.raw_text_sent).toBe(false);
  expect(summary.coverage.tool_names_sent).toBe(false);
  await expect(inspecting.locator(".ai-answer")).toContainText("Deterministic fixture summary");
  await inspecting
    .locator(".evidence-refs")
    .getByRole("button", { name: "obs-1", exact: true })
    .click();
  await expect(inspecting.locator(".import-observation")).toBeFocused();
  await expect(
    inspecting.getByText("<b>Local scanner note, synthetic only.</b>", { exact: true }),
  ).toBeVisible();
  expect(await inspecting.locator(".import-observation b").count()).toBe(0);
  await page.screenshot({ path: resolve(artifacts, "ai-report-summary.png") });
});

test("AI answer text is inert and provider errors never become success-shaped answers", async ({
  page,
}) => {
  await login(page);
  const run = await scenario(page);
  if (!run.incident_id) throw new Error("The bounded scenario did not create a case");
  await page.getByRole("button", { name: "Open incident workbench", exact: true }).click();
  await page
    .locator(".ai-assistant")
    .getByLabel("Question about this case", { exact: true })
    .fill("What evidence is missing?");
  await page.getByRole("button", { name: "Generate fixture answer", exact: true }).click();
  await expect(page.locator(".ai-assistant .ai-record")).toHaveCount(1);
  const inert = '<b data-model-probe="synthetic">Untrusted model text</b>';
  await page.route(`**/v1/incidents/${run.incident_id}`, async (route) => {
    const response = await route.fetch();
    const detail = (await response.json()) as CaseDetail;
    const output = detail.assistant[0]?.output;
    if (!output) throw new Error("The real fixture answer was not recorded");
    output.answer = inert;
    await route.fulfill({ response, json: detail });
  });
  await page.reload();
  await expect(page.getByText(inert, { exact: true })).toBeVisible();
  expect(await page.locator("[data-model-probe]").count()).toBe(0);
  await page.route(`**/v1/incidents/${run.incident_id}/assistant`, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: "MODEL_UNAVAILABLE",
        message: "Synthetic provider outage for UI test",
      }),
    }),
  );
  const field = page
    .locator(".ai-assistant")
    .getByLabel("Question about this case", { exact: true });
  await field.fill("Explain the remaining evidence gaps.");
  await page.getByRole("button", { name: "Generate fixture answer", exact: true }).click();
  await expect(page.locator(".ai-assistant .error-text")).toHaveText(
    "Synthetic provider outage for UI test",
  );
  await expect(field).toHaveValue("Explain the remaining evidence gaps.");
  await expect(page.locator(".ai-assistant .ai-record")).toHaveCount(1);
});

test("Wiz-style board opens an issue drawer with a plain and technical attack graph", async ({
  page,
}) => {
  await login(page, "admin", "plain");
  const run = await scenario(page);
  if (!run.incident_id) throw new Error("The bounded scenario did not create a case");
  await page.getByRole("dialog").getByRole("button", { name: "Close dialog" }).click();
  await expect(page.getByRole("heading", { name: "Open issues", exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Attackers contained", exact: true }),
  ).toBeVisible();
  const before = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as BackendEvidence;
  await page.goto(`/incidents?issue=${run.incident_id}`);
  const drawer = page.locator(".issue-drawer");
  await expect(drawer.locator(".issue-description")).toContainText("honeypot");
  await expect(drawer.locator(".issue-banner")).toContainText("No real data touched");
  await expect(drawer.locator(".attack-chain")).toContainText("Internet");
  await expect(drawer.locator(".attack-chain")).toContainText("Honeypot");
  const graph = drawer.locator(".graph-card svg[role='img']");
  await expect(graph).toBeVisible();
  await drawer.locator(".attack-node", { hasText: "Honeypot" }).first().click();
  await expect(drawer.locator(".attack-node-detail")).toContainText("fake");
  await drawer.getByRole("button", { name: "What happened", exact: true }).click();
  await expect(drawer.locator(".attack-story")).toContainText("blocked");
  await drawer.getByRole("button", { name: "Technical view", exact: true }).first().click();
  await expect(drawer.locator(".attack-story")).toContainText("authorization.decided");
  await drawer.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(drawer.locator(".issue-description")).toContainText("D-002");
  await page.screenshot({ path: resolve(artifacts, "wiz-issue-drawer.png") });
  await page.keyboard.press("Escape");
  await expect(page.locator(".issue-drawer")).toHaveCount(0);
  const after = (await page.request
    .get("/v1/backend/evidence")
    .then((response) => response.json())) as BackendEvidence;
  expect(after.production_reads).toBe(before.production_reads);
  expect(after.production_mutations).toBe(before.production_mutations);
});

test("floating AI assistant answers workspace questions with issue references", async ({
  page,
}) => {
  await login(page, "analyst", "plain");
  await page.getByRole("button", { name: "Ask Mirage AI", exact: true }).click();
  const panel = page.getByRole("complementary", { name: "Ask Mirage AI" });
  await expect(panel).toBeVisible();
  const answered = page.waitForResponse(
    (response) =>
      response.url().endsWith("/v1/assistant") && response.request().method() === "POST",
  );
  await panel.getByRole("button", { name: "What attacks happened today?", exact: true }).click();
  expect((await answered).status()).toBe(200);
  await expect(panel.locator(".ai-chat-answer")).toContainText("Demo answer");
  await expect(panel.locator(".ai-chat-answer")).toContainText(
    "Demo AI (fixture, not live Gemini)",
  );
  await panel
    .getByLabel("Ask Mirage AI", { exact: true })
    .fill("Which agents are in the honeypot?");
  await panel.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(panel.locator(".ai-chat-turn")).toHaveCount(2);
  await page.screenshot({ path: resolve(artifacts, "wiz-ai-chat.png") });
  await panel.getByRole("button", { name: "Close AI chat", exact: true }).click();
  await expect(page.getByRole("button", { name: "Ask Mirage AI", exact: true })).toBeVisible();
});

test("administrator selects the Gemini model in the portal without exposing credentials", async ({
  page,
}) => {
  await login(page, "admin", "plain");
  await page.goto("/settings");
  const form = page.locator(".ai-config-form");
  await form.getByLabel("AI provider", { exact: true }).selectOption("gemini");
  await form.getByLabel("Google Cloud project ID", { exact: true }).fill("mirage-demo-project");
  await form.getByLabel("Region", { exact: true }).selectOption("us-central1");
  await form.getByLabel("Gemini model", { exact: true }).fill("gemini-3.8-flash");
  const saved = page.waitForResponse(
    (response) => response.url().endsWith("/v1/ai/config") && response.request().method() === "PUT",
  );
  await form.getByRole("button", { name: "Save AI settings", exact: true }).click();
  expect((await saved).status()).toBe(200);
  const status = (await page.request.get("/v1/ai").then((response) => response.json())) as {
    mode: string;
    model: string;
    state: string;
    can_generate: boolean;
  };
  expect(status).toMatchObject({
    mode: "gemini",
    model: "gemini-3.8-flash",
    state: "egress-disabled",
  });
  expect(status.can_generate).toBe(false);
  await page.screenshot({ path: resolve(artifacts, "wiz-ai-settings.png"), fullPage: true });
  const reset = page.locator(".ai-config-form");
  await reset.getByLabel("AI provider", { exact: true }).selectOption("fixture");
  const restored = page.waitForResponse(
    (response) => response.url().endsWith("/v1/ai/config") && response.request().method() === "PUT",
  );
  await reset.getByRole("button", { name: "Save AI settings", exact: true }).click();
  expect((await restored).status()).toBe(200);
  await expect
    .poll(
      async () =>
        ((await page.request.get("/v1/ai").then((response) => response.json())) as { mode: string })
          .mode,
    )
    .toBe("fixture");
});

test("Telegram access requests are approved with a role and can be revoked by an administrator", async ({
  page,
}) => {
  await login(page, "admin", "plain");
  const update = {
    update_id: 4100 + Math.floor(Math.random() * 1000),
    message: {
      message_id: 1,
      date: Math.floor(Date.now() / 1000),
      text: "/start",
      from: { id: 700000001, is_bot: false, first_name: "Priya", username: "priya_sec" },
      chat: { id: 700000001, type: "private" },
    },
  };
  const forged = await page.request.post("/telegram/webhook", {
    data: update,
    headers: { "X-Telegram-Bot-Api-Secret-Token": "wrong-secret-wrong-secret-000000" },
  });
  expect(forged.status()).toBe(401);
  const delivered = await page.request.post("/telegram/webhook", {
    data: update,
    headers: { "X-Telegram-Bot-Api-Secret-Token": "qa-webhook-secret-0123456789abcdef" },
  });
  expect(delivered.status()).toBe(200);
  await page.goto("/integrations");
  const row = page.locator(".telegram-user", { hasText: "priya_sec" });
  await expect(row).toBeVisible();
  await row.getByLabel(/Telegram role for/).selectOption("approver");
  await row.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator(".telegram-user", { hasText: "priya_sec" })).toContainText("approved");
  const users = (await page.request
    .get("/v1/telegram/users")
    .then((response) => response.json())) as {
    items: { username: string | null; status: string; role: string | null }[];
  };
  expect(users.items.find((item) => item.username === "priya_sec")).toMatchObject({
    status: "approved",
    role: "approver",
  });
  const status = await page.request.get("/v1/telegram").then((response) => response.text());
  expect(status).not.toContain("qa-fake-token");
  await page.screenshot({ path: resolve(artifacts, "wiz-telegram.png"), fullPage: true });
  await page
    .locator(".telegram-user", { hasText: "priya_sec" })
    .getByRole("button", { name: "Revoke", exact: true })
    .click();
  await expect(page.locator(".telegram-user", { hasText: "priya_sec" })).toContainText("revoked");
});
