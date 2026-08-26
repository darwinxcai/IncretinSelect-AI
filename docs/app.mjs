import {
  EXAMPLE_SEQUENCE,
  TIER_COPY,
  formatNumber,
  normalizeSequence,
  predictFromModel,
  sha256Hex,
} from "./model.mjs";
import {
  MAX_BROWSER_BYTES,
  buildBatchArtifacts,
  parseCandidateCsv,
  parseSingleFasta,
  renderSingleResultCsv,
  renderSingleResultJson,
} from "./io.mjs";

// Retain these exports for the Node parity runner and downstream users.
export {
  EXAMPLE_SEQUENCE,
  TIER_COPY,
  alignedIdentity,
  formatNumber,
  normalizeSequence,
  predictFromModel,
  sha256Hex,
} from "./model.mjs";

const BATCH_TEMPLATE = (
  "candidate_id,aligned_sequence\n" +
  `candidate_01,${EXAMPLE_SEQUENCE}\n` +
  "candidate_02,HSQGTFTSDYSKYLDSRAAAEFVQWLLAGG\n"
);

function element(id) {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Browser application is missing required element #${id}.`);
  return value;
}

function setText(id, value) {
  element(id).textContent = String(value);
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function showError(error) {
  const box = element("input-error");
  box.textContent = errorMessage(error);
  box.hidden = false;
}

function clearError() {
  element("input-error").hidden = true;
}

function downloadText(filename, text, mimeType) {
  const blob = new Blob([text], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function updateSequenceCount(sequenceInput) {
  const normalizedLength = sequenceInput.value.replace(/\s/g, "").length;
  const count = element("sequence-count");
  count.textContent = `${normalizedLength} / 30`;
  count.classList.toggle("bad", normalizedLength !== 30);
}

export function rankingExclusion(result) {
  const reasons = [];
  if (result.applicability.tier !== "close_analogue") {
    reasons.push(result.applicability.summary);
  }
  if (result.input.standardResidueCount < 26) {
    reasons.push(
      `The input contains ${result.input.standardResidueCount} standard residues; ` +
      "candidate ranking requires at least 26.",
    );
  }
  return reasons;
}

function renderResult(result, model, artifactSha256) {
  const predictions = result.predictions;
  const scope = result.applicability;
  const tier = TIER_COPY[scope.tier];
  const badge = element("applicability-badge");
  badge.textContent = tier.label;
  badge.className = `badge ${tier.className}`;
  setText("normalized-sequence", result.input.alignedSequence);
  setText("glp1r-value", `${formatNumber(predictions.glp1r.ec50Pm)} pM`);
  setText(
    "glp1r-detail",
    `${formatNumber(predictions.glp1r.ec50Pm / 1000)} nM · ` +
      `log10(pM) ${predictions.glp1r.log10Ec50Pm.toFixed(4)}`,
  );
  setText("gcgr-value", `${formatNumber(predictions.gcgr.ec50Pm)} pM`);
  setText(
    "gcgr-detail",
    `${formatNumber(predictions.gcgr.ec50Pm / 1000)} nM · ` +
      `log10(pM) ${predictions.gcgr.log10Ec50Pm.toFixed(4)}`,
  );
  setText("balance-value", `${formatNumber(predictions.selectivity.ec50FoldRatio)}-fold`);
  setText("balance-detail", predictions.selectivity.interpretation);
  setText("applicability-name", tier.label);
  setText("nearest-identity", `${(scope.nearestAlignedIdentity * 100).toFixed(1)}%`);
  setText("nearest-reference", scope.nearestReferenceIds.join(", "));
  setText("applicability-summary", scope.summary);

  const exclusions = rankingExclusion(result);
  const rankingBlock = element("ranking-block");
  rankingBlock.hidden = exclusions.length === 0;
  setText("ranking-block-reason", exclusions.join(" "));

  const metrics = model.benchmark_context.metrics;
  setText("gcgr-error", `${metrics.gcgr.development_oof_geometric_fold_error.toFixed(1)}×`);
  setText("glp1r-error", `${metrics.glp1r.development_oof_geometric_fold_error.toFixed(1)}×`);
  setText(
    "balance-error",
    `${metrics.selectivity.development_oof_geometric_fold_error.toFixed(1)}×`,
  );
  const warnings = element("warnings");
  warnings.replaceChildren(...result.warnings.map((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
  setText("model-id", `${model.artifact_id} v${model.artifact_version}`);
  setText("model-sha", artifactSha256);
  element("results").hidden = false;
}

function renderBatch(artifacts) {
  const counts = artifacts.counts;
  setText("batch-total", counts.total_rows);
  setText("batch-ranked", counts.ranked_rows);
  setText("batch-excluded", counts.total_rows - counts.ranked_rows);
  const badge = element("batch-result-status");
  const labels = {
    completed: "Completed",
    completed_with_row_errors: "Completed with row errors",
    no_rankable_rows: "No rankable rows",
  };
  badge.textContent = labels[artifacts.status] ?? artifacts.status;
  badge.className = `badge ${artifacts.status === "completed" ? "close" : "distant"}`;

  const visibleRows = artifacts.rows.slice(0, 50);
  const body = element("batch-table-body");
  body.replaceChildren(...visibleRows.map((row) => {
    const tableRow = document.createElement("tr");
    const values = [
      row.rank || "—",
      row.candidate_id,
      row.status.replaceAll("_", " "),
      row.glp1r_ec50_pm ? formatNumber(Number(row.glp1r_ec50_pm)) : "—",
      row.gcgr_ec50_pm ? formatNumber(Number(row.gcgr_ec50_pm)) : "—",
      row.applicability_tier ? row.applicability_tier.replaceAll("_", " ") : "—",
      row.nearest_aligned_identity
        ? `${(Number(row.nearest_aligned_identity) * 100).toFixed(1)}%`
        : "—",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      tableRow.append(cell);
    }
    return tableRow;
  }));
  setText(
    "batch-preview-note",
    artifacts.rows.length > visibleRows.length
      ? `Showing the first ${visibleRows.length} of ${artifacts.rows.length} rows. ` +
        "The download contains every row."
      : `Showing all ${artifacts.rows.length} rows.`,
  );
  element("batch-results").hidden = false;
}

async function loadVerifiedModel() {
  const [manifestResponse, modelResponse] = await Promise.all([
    fetch("demo_manifest.json", { cache: "no-store" }),
    fetch("assets/incretin_ridge_v1.json", { cache: "no-store" }),
  ]);
  if (!manifestResponse.ok || !modelResponse.ok) {
    throw new Error("Application assets could not be loaded. Serve the docs directory over HTTP.");
  }
  const manifest = await manifestResponse.json();
  const bytes = await modelResponse.arrayBuffer();
  const observed = await sha256Hex(bytes);
  if (observed !== manifest.artifact_sha256) {
    throw new Error("Frozen model checksum mismatch. Do not use this application copy.");
  }
  const model = JSON.parse(new TextDecoder().decode(bytes));
  if (
    model.schema_version !== 1 ||
    model.artifact_id !== "incretinselect_aligned_ridge_v1" ||
    model.input_contract?.aligned_length !== 30 ||
    model.model?.coefficients?.length !== 630 ||
    model.applicability_reference?.labels_included !== false
  ) {
    throw new Error("Frozen model contract is invalid.");
  }
  return { model, artifactSha256: observed };
}

function setMode(mode) {
  const single = mode === "single";
  element("prediction-form").hidden = !single;
  element("batch-form").hidden = single;
  element("single-mode-button").classList.toggle("active", single);
  element("single-mode-button").setAttribute("aria-pressed", String(single));
  element("batch-mode-button").classList.toggle("active", !single);
  element("batch-mode-button").setAttribute("aria-pressed", String(!single));
  element("results").hidden = true;
  element("batch-results").hidden = true;
  clearError();
}

async function initialize() {
  const sequence = element("sequence");
  const predictButton = element("predict-button");
  const screenButton = element("screen-button");
  const modelState = element("model-state");
  const fastaFile = element("fasta-file");
  const batchFile = element("batch-file");
  sequence.value = EXAMPLE_SEQUENCE;
  updateSequenceCount(sequence);
  sequence.addEventListener("input", () => updateSequenceCount(sequence));
  element("single-mode-button").addEventListener("click", () => setMode("single"));
  element("batch-mode-button").addEventListener("click", () => setMode("batch"));
  element("example-button").addEventListener("click", () => {
    sequence.value = EXAMPLE_SEQUENCE;
    fastaFile.value = "";
    setText("fasta-status", "Example restored; no file is loaded.");
    updateSequenceCount(sequence);
    clearError();
    sequence.focus();
  });
  element("template-button").addEventListener("click", () => {
    downloadText("incretinselect_candidates_template.csv", BATCH_TEMPLATE, "text/csv");
  });

  let verified;
  try {
    verified = await loadVerifiedModel();
    modelState.textContent = "Verified model ready";
    modelState.className = "model-state ready";
    predictButton.disabled = false;
  } catch (error) {
    modelState.textContent = "Model verification failed";
    modelState.className = "model-state failed";
    showError(error);
    return;
  }

  let singleDownloads = null;
  let batchText = null;
  let batchFilename = null;
  let batchDownloads = null;

  fastaFile.addEventListener("change", async () => {
    const file = fastaFile.files?.[0];
    if (!file) return;
    try {
      if (file.size > MAX_BROWSER_BYTES) {
        throw new Error(`File is ${file.size} bytes; the browser limit is ${MAX_BROWSER_BYTES}.`);
      }
      const text = await file.text();
      const trimmed = text.trimStart();
      const parsed = trimmed.startsWith(">")
        ? parseSingleFasta(text, verified.model)
        : { header: file.name, alignedSequence: normalizeSequence(text, verified.model) };
      sequence.value = parsed.alignedSequence;
      updateSequenceCount(sequence);
      setText("fasta-status", `Loaded ${file.name} locally (${parsed.header}).`);
      clearError();
    } catch (error) {
      setText("fasta-status", `Could not load ${file.name}.`);
      showError(error);
    }
  });

  element("prediction-form").addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const result = predictFromModel(sequence.value, verified.model);
      sequence.value = result.input.alignedSequence;
      updateSequenceCount(sequence);
      singleDownloads = {
        json: renderSingleResultJson(result, verified.model, verified.artifactSha256),
        csv: renderSingleResultCsv(result, verified.model, verified.artifactSha256),
      };
      clearError();
      renderResult(result, verified.model, verified.artifactSha256);
      element("results").scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      singleDownloads = null;
      element("results").hidden = true;
      showError(error);
    }
  });
  element("single-json-button").addEventListener("click", () => {
    if (singleDownloads) {
      downloadText("incretinselect_prediction.json", singleDownloads.json, "application/json");
    }
  });
  element("single-csv-button").addEventListener("click", () => {
    if (singleDownloads) {
      downloadText("incretinselect_prediction.csv", singleDownloads.csv, "text/csv");
    }
  });

  const selectedObjective = () => (
    document.querySelector('input[name="objective"]:checked')?.value ?? ""
  );
  const updateBatchButton = () => {
    screenButton.disabled = !(batchText && selectedObjective());
  };
  document.querySelectorAll('input[name="objective"]').forEach((radio) => {
    radio.addEventListener("change", updateBatchButton);
  });
  batchFile.addEventListener("change", async () => {
    const file = batchFile.files?.[0];
    batchText = null;
    batchFilename = null;
    updateBatchButton();
    if (!file) return;
    try {
      if (file.size > MAX_BROWSER_BYTES) {
        throw new Error(`File is ${file.size} bytes; the browser limit is ${MAX_BROWSER_BYTES}.`);
      }
      const text = await file.text();
      const records = parseCandidateCsv(text);
      batchText = text;
      batchFilename = file.name;
      setText("batch-status", `Ready: ${file.name} contains ${records.length} candidate rows.`);
      clearError();
    } catch (error) {
      setText("batch-status", `Could not load ${file.name}.`);
      showError(error);
    }
    updateBatchButton();
  });
  element("batch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      if (!batchText || !batchFilename) throw new Error("Select a candidate CSV first.");
      const objective = selectedObjective();
      if (!objective) throw new Error("Choose a screening objective.");
      screenButton.disabled = true;
      screenButton.textContent = "Screening…";
      batchDownloads = await buildBatchArtifacts(batchText, objective, verified.model, {
        artifactSha256: verified.artifactSha256,
        inputFilename: batchFilename,
        outputFilename: "incretinselect_screened_candidates.csv",
      });
      clearError();
      renderBatch(batchDownloads);
      setText(
        "batch-status",
        `Completed locally: ${batchDownloads.counts.ranked_rows} of ` +
        `${batchDownloads.counts.total_rows} rows were eligible for ranking.`,
      );
      element("batch-results").scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      batchDownloads = null;
      element("batch-results").hidden = true;
      showError(error);
    } finally {
      screenButton.textContent = "Run batch screen";
      updateBatchButton();
    }
  });
  element("batch-csv-button").addEventListener("click", () => {
    if (batchDownloads) {
      downloadText(
        "incretinselect_screened_candidates.csv",
        batchDownloads.csv,
        "text/csv",
      );
    }
  });
  element("batch-json-button").addEventListener("click", () => {
    if (batchDownloads) {
      downloadText(
        "incretinselect_screening_receipt.json",
        batchDownloads.receiptJson,
        "application/json",
      );
    }
  });
}

if (typeof document !== "undefined") initialize();
