import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const ELEMENT_IDS = [
  "applicability-badge",
  "applicability-name",
  "applicability-panel",
  "applicability-summary",
  "alignment-summary",
  "balance-detail",
  "balance-error",
  "balance-value",
  "batch-context-note",
  "batch-csv-button",
  "batch-excluded",
  "batch-file",
  "batch-form",
  "batch-json-button",
  "batch-mode-button",
  "batch-preview-note",
  "batch-ranked",
  "batch-result-status",
  "batch-results",
  "batch-status",
  "batch-table-body",
  "batch-total",
  "comparison-change-count",
  "comparison-empty",
  "comparison-gcgr-delta",
  "comparison-gcgr-fold",
  "comparison-glp1r-delta",
  "comparison-glp1r-fold",
  "comparison-reference",
  "comparison-panel",
  "comparison-table-body",
  "comparison-table-wrap",
  "comparison-tie-count",
  "example-button",
  "expert-aligned-mode",
  "fasta-file",
  "fasta-status",
  "gcgr-detail",
  "gcgr-error",
  "gcgr-value",
  "glp1r-detail",
  "glp1r-error",
  "glp1r-value",
  "input-error",
  "model-id",
  "model-sha",
  "model-state",
  "nearest-identity",
  "nearest-reference",
  "normalized-sequence",
  "overview-applicability",
  "overview-evidence",
  "overview-profile",
  "overview-ranking",
  "predict-button",
  "prediction-form",
  "ranking-block",
  "ranking-block-reason",
  "results",
  "screen-button",
  "sequence",
  "sequence-count",
  "sequence-help",
  "single-csv-button",
  "single-json-button",
  "single-markdown-button",
  "single-mode-button",
  "template-button",
  "warnings",
];

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name);
    else this.values.delete(name);
    return enabled;
  }
}

class FakeElement {
  constructor(id = "", tagName = "div", ownerDocument = null) {
    this.id = id;
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.attributes = new Map();
    this.children = [];
    this.classList = new FakeClassList();
    this.className = "";
    this.checked = false;
    this.disabled = false;
    this.files = [];
    this.hidden = false;
    this.listeners = new Map();
    this.textContent = "";
    this.value = "";
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  async fire(type) {
    const event = { preventDefault() {} };
    const pending = (this.listeners.get(type) ?? []).map((listener) => listener(event));
    await Promise.all(pending);
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  focus() {}

  scrollIntoView() {}

  remove() {}

  click() {
    if (this.tagName === "A") {
      this.ownerDocument.downloads.push({
        blob: this.ownerDocument.blobs.get(this.href),
        filename: this.download,
      });
    }
  }
}

class FakeDocument {
  constructor() {
    this.blobs = new Map();
    this.downloads = [];
    this.elements = new Map(
      ELEMENT_IDS.map((id) => [id, new FakeElement(id, "div", this)]),
    );
    for (const id of ["results", "batch-results", "input-error", "batch-form"]) {
      this.elements.get(id).hidden = true;
    }
    this.objectives = ["glp1r", "gcgr", "dual"].map((value) => {
      const radio = new FakeElement("", "input", this);
      radio.value = value;
      return radio;
    });
    this.body = new FakeElement("", "body", this);
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }

  querySelectorAll(selector) {
    if (selector === 'input[name="objective"]') return this.objectives;
    return [];
  }

  querySelector(selector) {
    if (selector === 'input[name="objective"]:checked') {
      return this.objectives.find((radio) => radio.checked) ?? null;
    }
    return null;
  }

  createElement(tagName) {
    return new FakeElement("", tagName, this);
  }
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function arrayBufferCopy(bytes) {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function delayedFile(name, text) {
  const bytes = new TextEncoder().encode(text);
  const gate = deferred();
  return {
    file: {
      name,
      size: bytes.byteLength,
      arrayBuffer: () => gate.promise.then(() => arrayBufferCopy(bytes)),
    },
    resolve: gate.resolve,
  };
}

function immediateFile(name, text) {
  const bytes = new TextEncoder().encode(text);
  return {
    name,
    size: bytes.byteLength,
    arrayBuffer: async () => arrayBufferCopy(bytes),
  };
}

async function waitFor(predicate, label) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  assert.fail(`Timed out waiting for ${label}.`);
}

const document = new FakeDocument();
globalThis.document = document;
globalThis.matchMedia = () => ({ matches: true });

const manifest = JSON.parse(
  await readFile(new URL("../docs/demo_manifest.json", import.meta.url), "utf8"),
);
const modelBytes = await readFile(
  new URL("../docs/assets/incretin_ridge_v1.json", import.meta.url),
);
const adapterBytes = await readFile(
  new URL("../docs/assets/raw_alignment_adapter.json", import.meta.url),
);
globalThis.fetch = async (path) => {
  if (path === "demo_manifest.json") {
    return { ok: true, json: async () => structuredClone(manifest) };
  }
  if (path === "assets/incretin_ridge_v1.json") {
    return { ok: true, arrayBuffer: async () => arrayBufferCopy(modelBytes) };
  }
  if (path === "assets/raw_alignment_adapter.json") {
    return { ok: true, arrayBuffer: async () => arrayBufferCopy(adapterBytes) };
  }
  return { ok: false };
};

let blobCounter = 0;
URL.createObjectURL = (blob) => {
  const url = `blob:state-test-${blobCounter += 1}`;
  document.blobs.set(url, blob);
  return url;
};
URL.revokeObjectURL = (url) => document.blobs.delete(url);

await import("../docs/app.mjs?app-state-unit-test");
await waitFor(
  () => document.getElementById("model-state").textContent === "Verified model ready",
  "verified model initialization",
);

const ref93 = "HSQGTFTSDYSKYLDSRAASEFVQWLISE-";
const ref11 = "HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG";
const sequence = document.getElementById("sequence");
const results = document.getElementById("results");
const predictionForm = document.getElementById("prediction-form");
const expertMode = document.getElementById("expert-aligned-mode");
const sequenceCount = document.getElementById("sequence-count");

// Input feedback must describe the selected contract, not infer mode from text.
sequence.value = ref93;
await sequence.fire("input");
assert.match(sequenceCount.textContent, /gaps require expert mode/);
assert.equal(sequenceCount.classList.values.has("bad"), true);
expertMode.checked = true;
await expertMode.fire("change");
assert.match(sequenceCount.textContent, /30 \/ 30 model columns/);
assert.equal(sequenceCount.classList.values.has("bad"), false);
sequence.value = ref93.replaceAll("-", "");
await sequence.fire("input");
assert.match(sequenceCount.textContent, /29 \/ 30 model columns/);
assert.equal(sequenceCount.classList.values.has("bad"), true);
expertMode.checked = false;
await expertMode.fire("change");
assert.equal(sequenceCount.textContent, "29 residues");
assert.equal(sequenceCount.classList.values.has("bad"), false);

// Editing the sequence must invalidate both the visible result and its downloads.
await predictionForm.fire("submit");
assert.equal(results.hidden, false);
const downloadCount = document.downloads.length;
sequence.value = ref93;
await sequence.fire("input");
assert.equal(results.hidden, true);
await document.getElementById("single-json-button").fire("click");
assert.equal(document.downloads.length, downloadCount);

// A slow earlier FASTA read must not replace a newer selection.
const fastaFile = document.getElementById("fasta-file");
const olderFasta = delayedFile("older.fasta", `>older\n${ref93.replaceAll("-", "")}\n`);
const newerFasta = delayedFile("newer.fasta", `>newer\n${ref11.replaceAll("-", "")}\n`);
fastaFile.files = [olderFasta.file];
const olderFastaRead = fastaFile.fire("change");
fastaFile.files = [newerFasta.file];
const newerFastaRead = fastaFile.fire("change");
newerFasta.resolve();
await newerFastaRead;
assert.equal(sequence.value, ref11.replaceAll("-", ""));
assert.match(document.getElementById("fasta-status").textContent, /newer\.fasta/);
olderFasta.resolve();
await olderFastaRead;
assert.equal(sequence.value, ref11.replaceAll("-", ""));
assert.match(document.getElementById("fasta-status").textContent, /newer\.fasta/);

const batchFile = document.getElementById("batch-file");
const batchForm = document.getElementById("batch-form");
const batchResults = document.getElementById("batch-results");
const csvOlder = `candidate_id,aligned_sequence\nolder,${ref93}\n`;
const csvNewer = `candidate_id,aligned_sequence\nnewer,${ref11}\n`;

function chooseObjective(value) {
  for (const radio of document.objectives) radio.checked = radio.value === value;
  return document.objectives.find((radio) => radio.value === value);
}

// A slow earlier CSV read must not replace the newer selected file.
const olderCsv = delayedFile("older.csv", csvOlder);
const newerCsv = delayedFile("newer.csv", csvNewer);
batchFile.files = [olderCsv.file];
const olderCsvRead = batchFile.fire("change");
batchFile.files = [newerCsv.file];
const newerCsvRead = batchFile.fire("change");
newerCsv.resolve();
await newerCsvRead;
assert.match(document.getElementById("batch-status").textContent, /newer\.csv/);
olderCsv.resolve();
await olderCsvRead;
assert.match(document.getElementById("batch-status").textContent, /newer\.csv/);

// Objective changes and file changes must immediately invalidate old batch output.
const dualRadio = chooseObjective("dual");
await dualRadio.fire("change");
await batchForm.fire("submit");
assert.equal(batchResults.hidden, false);
const beforeObjectiveInvalidation = document.downloads.length;
const glp1rRadio = chooseObjective("glp1r");
await glp1rRadio.fire("change");
assert.equal(batchResults.hidden, true);
await document.getElementById("batch-json-button").fire("click");
assert.equal(document.downloads.length, beforeObjectiveInvalidation);

await batchForm.fire("submit");
assert.equal(batchResults.hidden, false);
const replacementCsv = delayedFile("replacement.csv", csvOlder);
batchFile.files = [replacementCsv.file];
const replacementRead = batchFile.fire("change");
assert.equal(batchResults.hidden, true);
replacementCsv.resolve();
await replacementRead;

// A slower earlier screening run must not render over a newer objective/run.
const readyFile = immediateFile("race.csv", csvNewer);
batchFile.files = [readyFile];
await batchFile.fire("change");
await chooseObjective("dual").fire("change");

const originalDigest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle);
const firstDigestGate = deferred();
const firstDigestStarted = deferred();
let delayFirstDigest = true;
globalThis.crypto.subtle.digest = (algorithm, data) => {
  if (delayFirstDigest) {
    delayFirstDigest = false;
    firstDigestStarted.resolve();
    return firstDigestGate.promise.then(() => originalDigest(algorithm, data));
  }
  return originalDigest(algorithm, data);
};

const olderScreen = batchForm.fire("submit");
await firstDigestStarted.promise;
await chooseObjective("gcgr").fire("change");
await batchForm.fire("submit");
assert.equal(batchResults.hidden, false);

async function downloadLatestReceipt() {
  await document.getElementById("batch-json-button").fire("click");
  const download = document.downloads.at(-1);
  assert.equal(download.filename, "incretinselect_screening_receipt.json");
  return JSON.parse(await download.blob.text());
}

assert.equal((await downloadLatestReceipt()).objective.name, "gcgr");
firstDigestGate.resolve();
await olderScreen;
assert.equal(batchResults.hidden, false);
assert.equal((await downloadLatestReceipt()).objective.name, "gcgr");
globalThis.crypto.subtle.digest = originalDigest;

process.stdout.write("static demo stale-result and race checks passed\n");
