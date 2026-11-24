// Capture README screenshots from real executions against a running backend.
// The backend decides the provider; run it with a live model for live screenshots.
//   BASE_URL=http://127.0.0.1:3000 API_URL=http://127.0.0.1:8000 PROVIDER=openai node tests/screenshots.cjs
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

const BASE = process.env.BASE_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://localhost:8000";
const TOKEN = process.env.AGENTOS_TOKEN || "local-demo-token";
const PROVIDER = process.env.PROVIDER || "demo";
const OUT = process.env.SCREENSHOT_DIR || "../docs/screenshots";
const TIMEOUT = Number(process.env.RUN_TIMEOUT_MS || 600000);
// Optional comma-separated subset: research,approval,analytics,experiments
const ONLY = (
  process.env.SHOTS || "research,approval,analytics,experiments"
).split(",");

async function api(path, body) {
  const r = await fetch(API + path, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
}

async function run(page, goal) {
  await page.getByRole("button", { name: "Workspace", exact: false }).click();
  await page.getByLabel("Provider").selectOption(PROVIDER);
  await page.getByLabel("What should your agents accomplish?").fill(goal);
  await page.getByRole("button", { name: /Run workflow/ }).click();
  // The previous result clears when the new run starts.
  await page
    .getByRole("heading", { name: "Workflow result" })
    .waitFor({ state: "detached" });
}

(async () => {
  await api("/demo/seed", {});
  for (const [source, content] of [
    [
      "inventory-policy",
      "East depot inventory policy. The East depot must keep at least twenty reserve pallets on site to cover supply interruptions. Reducing reserve stock requires the inventory owner's approval.",
    ],
    [
      "capacity-policy",
      "East depot capacity policy. The East depot may keep at most twelve reserve pallets on site to maintain fire-lane clearance. The capacity owner must review any proposed exception.",
    ],
  ])
    await api("/documents", { source, content });

  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 2,
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE);
  await page
    .getByRole("heading", { name: "From intent to verified output." })
    .waitFor();

  // 1. Research with conflicting policies.
  if (ONLY.includes("research")) {
    await run(
      page,
      "Compare the inventory and capacity policies for the East depot's reserve stock. Identify the conflicting thresholds, explain the operational risk, and give a cited recommendation with uncertainties.",
    );
    await page
      .getByRole("heading", { name: "Workflow result" })
      .waitFor({ timeout: TIMEOUT });
    await page
      .getByRole("heading", { name: "Workflow result" })
      .scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${OUT}/research.png`, fullPage: true });
  }

  // 2. Approval of an exact report proposal.
  if (ONLY.includes("approval")) {
    await run(
      page,
      "Analyze overdue invoices as of 2026-04-01. Prepare an internal follow-up report identifying overdue invoice numbers and amounts. Save that report after my approval.",
    );
    await page
      .getByText("Approval requested", { exact: true })
      .waitFor({ timeout: TIMEOUT });
    await page
      .getByText("Approval requested", { exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${OUT}/approval.png`, fullPage: true });
    await page.getByRole("button", { name: "Approve action" }).click();
    await page
      .getByRole("heading", { name: "Workflow result" })
      .waitFor({ timeout: TIMEOUT });
    await page.getByText("committed").first().waitFor({ timeout: TIMEOUT });
    await page.screenshot({ path: `${OUT}/receipt.png`, fullPage: true });
  }

  // 3. Analytics with recomputed metrics.
  if (ONLY.includes("analytics")) {
    await run(
      page,
      "Analyze February and March 2026 revenue, expenses, and profit. Calculate month-over-month changes for all three metrics, identify significant trends, and explain the findings.",
    );
    await page
      .getByRole("heading", { name: "Workflow result" })
      .waitFor({ timeout: TIMEOUT });
    await page.screenshot({ path: `${OUT}/analytics.png`, fullPage: true });
  }

  // 4. Experiments dashboard.
  await page.getByRole("button", { name: "Experiments", exact: false }).click();
  await page.getByRole("table").first().waitFor();
  await page.screenshot({ path: `${OUT}/experiments.png`, fullPage: true });

  assert.deepEqual(errors, []);
  console.log(
    `PASS: ${PROVIDER} research, approval, receipt, analytics and experiments captured`,
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
