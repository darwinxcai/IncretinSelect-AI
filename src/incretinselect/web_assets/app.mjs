import {
  EXAMPLE_SEQUENCE,
  EXPECTED_MODEL_SHA256,
  EVIDENCE_COPY,
  SOFTWARE_VERSION,
  TIER_COPY,
  formatNumber,
  normalizeSequence,
  predictFromModel,
  sha256Hex,
  validateModelArtifact,
} from "./model.mjs";
import {
  MAX_BROWSER_BYTES,
  buildBatchArtifacts,
  decodeUtf8Bytes,
  parseCandidateCsv,
  parseSingleFasta,
  renderSingleResultCsv,
  renderSingleResultJson,
  renderSingleResultMarkdown,
} from "./io.mjs";

// Retain these exports for the Node parity runner and downstream users.
export {
  EXAMPLE_SEQUENCE,
  EXPECTED_MODEL_SHA256,
  EVIDENCE_COPY,
  SOFTWARE_VERSION,
  TIER_COPY,
  alignedIdentity,
  formatNumber,
  normalizeSequence,
  predictFromModel,
  sha256Hex,
  validateModelArtifact,
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

function focusResult(id) {
  const section = element(id);
  const reduceMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  section.focus({ preventScroll: true });
  section.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
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
  return [...result.exploratoryRanking.exclusionReasons];
}

function renderResult(result, model, artifactSha256) {
  const predictions = result.predictions;
  const scope = result.applicability;
  const tier = EVIDENCE_COPY[scope.evidenceState] ?? TIER_COPY[scope.tier];
  const badge = element("applicability-badge");
  badge.textContent = tier.label;
  badge.className = `badge ${tier.className}`;
  setText("normalized-sequence", result.input.alignedSequence);
  setText("glp1r-value", `${formatNumber(predictions.glp1r.ec50Pm)} pM`);
  setText(
    "glp1r-detail",
    `${formatNumber(predictions.glp1r.ec50Pm / 1000)} nM · ` +
      `log10(EC50 / 1 pM) ${predictions.glp1r.log10Ec50Pm.toFixed(4)}`,
  );
  setText("gcgr-value", `${formatNumber(predictions.gcgr.ec50Pm)} pM`);
  setText(
    "gcgr-detail",
    `${formatNumber(predictions.gcgr.ec50Pm / 1000)} nM · ` +
      `log10(EC50 / 1 pM) ${predictions.gcgr.log10Ec50Pm.toFixed(4)}`,
  );
  setText("balance-value", `${formatNumber(predictions.selectivity.ec50FoldRatio)}-fold`);
  setText("balance-detail", predictions.selectivity.interpretation);
  setText("applicability-name", tier.label);
  setText("nearest-identity", `${(scope.nearestAlignedIdentity * 100).toFixed(1)}%`);
  setText("nearest-reference", scope.nearestReferenceIds.join(", "));
  setText("applicability-summary", scope.summary);

  const comparison = result.nearestReferenceComparison;
  const delta = comparison.queryMinusReference;
  setText("comparison-reference", comparison.referenceId);
  setText("comparison-change-count", comparison.changedPositionCount);
  setText("comparison-tie-count", comparison.nearestReferenceTieCount);
  setText("comparison-glp1r-delta", delta.glp1rDeltaLog10Ec50Pm.toFixed(4));
  setText("comparison-gcgr-delta", delta.gcgrDeltaLog10Ec50Pm.toFixed(4));
  setText(
    "comparison-glp1r-fold",
    `${formatNumber(delta.glp1rEc50FoldRatio)}x query/reference EC50`,
  );
  setText(
    "comparison-gcgr-fold",
    `${formatNumber(delta.gcgrEc50FoldRatio)}x query/reference EC50`,
  );
  const contributionRows = comparison.positionContributions;
  element("comparison-table-body").replaceChildren(...contributionRows.map((row) => {
    const tableRow = document.createElement("tr");
    const values = [
      row.alignmentPosition,
      row.referenceSymbol,
      row.querySymbol,
      row.glp1rDeltaLog10Ec50Pm.toFixed(4),
      row.gcgrDeltaLog10Ec50Pm.toFixed(4),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      tableRow.append(cell);
    }
    return tableRow;
  }));
  element("comparison-table-wrap").hidden = contributionRows.length === 0;
  const comparisonEmpty = element("comparison-empty");
  comparisonEmpty.hidden = contributionRows.length !== 0;
  comparisonEmpty.textContent = contributionRows.length
    ? ""
    : "The query is identical to the selected nearest reference.";

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
  setText(
    "batch-context-note",
    counts.ranked_rows
      ? `${counts.within_one_development_mae_of_first_rows} of ${counts.ranked_rows} ` +
        "ordered candidates differ from the top score by no more than one development " +
        "out-of-fold MAE. This is descriptive context, not an uncertainty interval for " +
        "any candidate."
      : "No candidates met the software gate for exploratory ordering.",
  );
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
      row.score_delta_from_first_log10 || "—",
      row.within_one_development_mae_of_first === "true"
        ? "Within 1 development MAE"
        : row.within_one_development_mae_of_first === "false"
        ? "More than 1 development MAE"
        : "—",
      row.glp1r_ec50_pm ? formatNumber(Number(row.glp1r_ec50_pm)) : "—",
      row.gcgr_ec50_pm ? formatNumber(Number(row.gcgr_ec50_pm)) : "—",
      row.applicability_tier ? row.applicability_tier.replaceAll("_", " ") : "—",
      row.nearest_aligned_identity
        ? `${(Number(row.nearest_aligned_identity) * 100).toFixed(1)}%`
        : "—",
      row.error_message || row.ranking_exclusion_reason || "—",
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
  if (observed !== manifest.artifact_sha256 || observed !== EXPECTED_MODEL_SHA256) {
    throw new Error("Frozen model checksum mismatch. Do not use this application copy.");
  }
  const model = validateModelArtifact(JSON.parse(new TextDecoder().decode(bytes)));
  if (manifest.software_version !== SOFTWARE_VERSION) {
    throw new Error("Browser application version does not match its release manifest.");
  }
  model.software_version = SOFTWARE_VERSION;
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
  const objectiveRadios = [...document.querySelectorAll('input[name="objective"]')];
  let singleDownloads = null;
  let batchText = null;
  let batchBytes = null;
  let batchFilename = null;
  let batchDownloads = null;
  let singleRevision = 0;
  let batchRevision = 0;
  let batchRunning = false;

  const invalidateSingleResult = () => {
    singleRevision += 1;
    singleDownloads = null;
    element("results").hidden = true;
    return singleRevision;
  };
  const invalidateBatchResult = () => {
    batchRevision += 1;
    batchRunning = false;
    batchDownloads = null;
    element("batch-results").hidden = true;
    screenButton.textContent = "Run batch screen";
    return batchRevision;
  };

  // Prevent file events from being lost while the model checksum is verified.
  fastaFile.disabled = true;
  batchFile.disabled = true;
  objectiveRadios.forEach((radio) => { radio.disabled = true; });

  sequence.value = EXAMPLE_SEQUENCE;
  updateSequenceCount(sequence);
  sequence.addEventListener("input", () => {
    updateSequenceCount(sequence);
    invalidateSingleResult();
    clearError();
  });
  element("single-mode-button").addEventListener("click", () => setMode("single"));
  element("batch-mode-button").addEventListener("click", () => setMode("batch"));
  element("example-button").addEventListener("click", () => {
    invalidateSingleResult();
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
    fastaFile.disabled = false;
    batchFile.disabled = false;
    objectiveRadios.forEach((radio) => { radio.disabled = false; });
  } catch (error) {
    modelState.textContent = "Model verification failed";
    modelState.className = "model-state failed";
    showError(error);
    return;
  }

  fastaFile.addEventListener("change", async () => {
    const file = fastaFile.files?.[0];
    const revision = invalidateSingleResult();
    if (!file) return;
    try {
      if (file.size > MAX_BROWSER_BYTES) {
        throw new Error(`File is ${file.size} bytes; the browser limit is ${MAX_BROWSER_BYTES}.`);
      }
      const bytes = await file.arrayBuffer();
      if (revision !== singleRevision || file !== fastaFile.files?.[0]) return;
      const text = decodeUtf8Bytes(bytes, file.name);
      const trimmed = text.trimStart();
      const parsed = trimmed.startsWith(">")
        ? parseSingleFasta(text, verified.model)
        : { header: file.name, alignedSequence: normalizeSequence(text, verified.model) };
      sequence.value = parsed.alignedSequence;
      updateSequenceCount(sequence);
      setText("fasta-status", `Loaded ${file.name} locally (${parsed.header}).`);
      clearError();
    } catch (error) {
      if (revision !== singleRevision || file !== fastaFile.files?.[0]) return;
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
        markdown: renderSingleResultMarkdown(
          result,
          verified.model,
          verified.artifactSha256,
        ),
      };
      clearError();
      renderResult(result, verified.model, verified.artifactSha256);
      focusResult("results");
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
  element("single-markdown-button").addEventListener("click", () => {
    if (singleDownloads) {
      downloadText(
        "incretinselect_prediction.md",
        singleDownloads.markdown,
        "text/markdown",
      );
    }
  });

  const selectedObjective = () => (
    document.querySelector('input[name="objective"]:checked')?.value ?? ""
  );
  const updateBatchButton = () => {
    screenButton.disabled = batchRunning || !(batchText && selectedObjective());
  };
  objectiveRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      invalidateBatchResult();
      updateBatchButton();
    });
  });
  batchFile.addEventListener("change", async () => {
    const file = batchFile.files?.[0];
    batchText = null;
    batchBytes = null;
    batchFilename = null;
    const revision = invalidateBatchResult();
    updateBatchButton();
    if (!file) return;
    try {
      if (file.size > MAX_BROWSER_BYTES) {
        throw new Error(`File is ${file.size} bytes; the browser limit is ${MAX_BROWSER_BYTES}.`);
      }
      const bytes = await file.arrayBuffer();
      if (revision !== batchRevision || file !== batchFile.files?.[0]) return;
      const text = decodeUtf8Bytes(bytes, file.name);
      const records = parseCandidateCsv(text);
      batchText = text;
      batchBytes = bytes;
      batchFilename = file.name;
      setText("batch-status", `Ready: ${file.name} contains ${records.length} candidate rows.`);
      clearError();
    } catch (error) {
      if (revision !== batchRevision || file !== batchFile.files?.[0]) return;
      setText("batch-status", `Could not load ${file.name}.`);
      showError(error);
    }
    updateBatchButton();
  });
  element("batch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submissionRevision = batchRevision;
    try {
      if (!batchText || !batchFilename) throw new Error("Select a candidate CSV first.");
      const objective = selectedObjective();
      if (!objective) throw new Error("Choose a screening objective.");
      const inputText = batchText;
      const inputBytes = batchBytes;
      const inputFilename = batchFilename;
      batchRunning = true;
      updateBatchButton();
      screenButton.textContent = "Screening…";
      const artifacts = await buildBatchArtifacts(inputText, objective, verified.model, {
        artifactSha256: verified.artifactSha256,
        inputBytes,
        inputFilename,
        outputFilename: "incretinselect_screened_candidates.csv",
      });
      if (submissionRevision !== batchRevision) return;
      batchDownloads = artifacts;
      clearError();
      renderBatch(batchDownloads);
      setText(
        "batch-status",
        `Completed locally: ${batchDownloads.counts.ranked_rows} of ` +
        `${batchDownloads.counts.total_rows} rows met the software gate for ordering.`,
      );
      focusResult("batch-results");
    } catch (error) {
      if (submissionRevision === batchRevision) {
        batchDownloads = null;
        element("batch-results").hidden = true;
        showError(error);
      }
    } finally {
      if (submissionRevision === batchRevision) {
        batchRunning = false;
        screenButton.textContent = "Run batch screen";
      }
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
