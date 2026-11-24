// Run after starting backend/frontend. npm install -D @playwright/test; npx playwright install chromium.
const { chromium } = require("playwright");
const OUT = process.env.SCREENSHOT_DIR || "../docs/screenshots/demo";
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(process.env.BASE_URL || "http://localhost:3000");
  await page
    .getByRole("heading", { name: "From intent to verified output." })
    .waitFor();
  await page.getByRole("button", { name: "Knowledge", exact: false }).click();
  page.on("dialog", (d) => d.accept());
  await page
    .getByRole("button", { name: "Load synthetic demo dataset" })
    .click();
  await page.getByRole("button", { name: "Workspace", exact: false }).click();
  await page.getByRole("button", { name: "Run workflow" }).click();
  await page
    .getByRole("heading", { name: "Workflow result" })
    .waitFor({ timeout: 20000 });
  await page.screenshot({
    path: `${OUT}/workspace.png`,
    fullPage: true,
  });
  await page.getByLabel("Workflow").selectOption("auto");
  await page
    .getByLabel("What should your agents accomplish?")
    .fill("Create an internal report explaining revenue with policy evidence");
  await page.getByRole("button", { name: "Run workflow" }).click();
  await page
    .getByText("Approval requested", { exact: true })
    .waitFor({ timeout: 20000 });
  await page.screenshot({
    path: `${OUT}/approval.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Approve action" }).click();
  await page
    .getByRole("heading", { name: "Workflow result" })
    .waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "Experiments", exact: false }).click();
  await page.getByRole("table").first().waitFor();
  await page.screenshot({
    path: `${OUT}/experiments.png`,
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "PASS: workspace execution, approval, experiment dashboard, no browser exceptions",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
