import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const EXAMPLE_BATCH = [
  "candidate_id,sequence",
  "reference_like,HSQGTFTSDYSKYLDSRAASEFVQWLISH",
  "second_local_analog,HSQGTFTSDYSKYLDSRAAAEFVQWLLAGG",
  "invalid_too_short,HSQGTFTS",
  "",
].join("\n");

async function openVerifiedApplication(page) {
  await page.goto("/");
  await expect(page.locator("#model-state")).toHaveText("Verified model ready");
  await expect(page.locator("#predict-button")).toBeEnabled();
}

async function readDownloadJson(download) {
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function violationSummary(violations) {
  return violations
    .map((violation) => {
      const targets = violation.nodes.map((node) => node.target.join(" ")).join(", ");
      return `${violation.id}: ${violation.help} (${targets})`;
    })
    .join("\n");
}

async function expectNoAccessibilityViolations(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations, violationSummary(results.violations)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await openVerifiedApplication(page);
});

test("a first-time user can run and download the preloaded example", async ({ page }) => {
  const externalRequests = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && url.hostname !== "127.0.0.1") {
      externalRequests.push(request.url());
    }
  });
  await openVerifiedApplication(page);
  await expect(page.locator("#sequence")).not.toHaveValue("");
  await page.locator("#predict-button").click();

  await expect(page.locator("#results")).toBeVisible();
  await expect(page.locator("#results")).toBeFocused();
  await expect(page.locator("#overview-applicability")).not.toHaveText("");
  await expect(page.locator("#glp1r-value")).toContainText(/pM|nM/);
  await expect(page.locator("#gcgr-value")).toContainText(/pM|nM/);
  await expect(page.locator("#model-sha")).toHaveText(/^[a-f0-9]{64}$/);

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#single-json-button").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("incretinselect_prediction.json");
  const document = await readDownloadJson(download);
  expect(document.schema_version).toBe(1);
  expect(document.input.original_sequence).toBeTruthy();
  expect(document.input.aligned_sequence).toHaveLength(30);
  expect(Number.isFinite(document.predictions.glp1r.ec50_pm)).toBe(true);
  expect(Number.isFinite(document.predictions.gcgr.ec50_pm)).toBe(true);
  expect(document.model.artifact_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(externalRequests).toEqual([]);

  await expectNoAccessibilityViolations(page);
});

test("FASTA import and invalid-input recovery work in a real browser", async ({ page }) => {
  await page.locator("#fasta-file").setInputFiles({
    name: "candidate.fasta",
    mimeType: "text/plain",
    buffer: Buffer.from(">candidate\nHSQGTFTSDYSKYLDSRAASEFVQWLISH\n"),
  });
  await expect(page.locator("#fasta-status")).toContainText("Loaded candidate.fasta locally");
  await page.locator("#predict-button").click();
  await expect(page.locator("#results")).toBeVisible();
  await expect(page.locator("#results")).toBeFocused();

  await page.locator("#sequence").fill("ACDEFGHIK");
  await page.locator("#predict-button").click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator("#results")).toBeHidden();
  await expectNoAccessibilityViolations(page);
});

test("batch screening retains invalid rows and exposes audit downloads", async ({ page }) => {
  await page.locator("#batch-mode-button").click();
  await page.locator("#batch-file").setInputFiles({
    name: "candidate_batch.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(EXAMPLE_BATCH),
  });
  await page.locator('input[name="objective"][value="dual"]').check();
  await expect(page.locator("#screen-button")).toBeEnabled();
  await page.locator("#screen-button").click();

  await expect(page.locator("#batch-results")).toBeVisible();
  await expect(page.locator("#batch-results")).toBeFocused();
  await expect(page.locator("#batch-total")).toHaveText("3");
  await expect(page.locator("#batch-excluded")).toHaveText("1");
  await expect(page.locator("#batch-table-body tr")).toHaveCount(3);

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#batch-json-button").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("incretinselect_screening_receipt.json");
  const receipt = await readDownloadJson(download);
  expect(receipt.schema_version).toBe(1);
  expect(receipt.objective.name).toBe("dual");
  expect(receipt.counts.total_rows).toBe(3);
  expect(receipt.counts.input_error_rows).toBe(1);
  expect(receipt.model.artifact_sha256).toMatch(/^[a-f0-9]{64}$/);

  await expectNoAccessibilityViolations(page);
});

test("the initial workflow has no WCAG accessibility violations", async ({ page }) => {
  await expectNoAccessibilityViolations(page);
});
