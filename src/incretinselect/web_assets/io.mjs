import {
  SOFTWARE_VERSION,
  normalizeSequence,
  predictFromModel,
  predictRawFromModel,
  prepareRawSequence,
  validateAlignmentAdapter,
} from "./model.mjs";

export const MAX_BROWSER_ROWS = 500;
export const MAX_BROWSER_RAW_ROWS = 200;
export const MAX_BROWSER_BYTES = 2_000_000;
export const MIN_RANKING_RESIDUES = 26;
export const RANKING_TIE_TOLERANCE = 1e-12;
export const RAW_INPUT_COLUMNS = Object.freeze(["candidate_id", "sequence"]);
export const ALIGNED_INPUT_COLUMNS = Object.freeze(["candidate_id", "aligned_sequence"]);
export const INPUT_COLUMNS = RAW_INPUT_COLUMNS;

export const OBJECTIVES = Object.freeze({
  glp1r: Object.freeze({
    definition: "minimize predicted GLP-1R log10(EC50 / 1 pM)",
    scoreColumn: "glp1r_log10_ec50_pm",
  }),
  gcgr: Object.freeze({
    definition: "minimize predicted GCGR log10(EC50 / 1 pM)",
    scoreColumn: "gcgr_log10_ec50_pm",
  }),
  dual: Object.freeze({
    definition: (
      "minimize the larger of predicted GLP-1R and GCGR log10(EC50 / 1 pM) values"
    ),
    scoreColumn: "max_receptor_log10_ec50_pm",
  }),
});

export const SCREENING_OUTPUT_COLUMNS = Object.freeze([
  "input_row",
  "candidate_id",
  "input_sequence",
  "input_mode",
  "aligned_sequence",
  "alignment_method",
  "alignment_status",
  "alignment_reference_ids",
  "alignment_adapter_id",
  "alignment_adapter_version",
  "alignment_adapter_sha256",
  "status",
  "error_code",
  "error_message",
  "ranking_objective",
  "ranking_objective_definition",
  "ranking_eligible",
  "ranking_exclusion_reason",
  "rank",
  "ranking_score",
  "score_delta_from_first_log10",
  "score_fold_ratio_from_first",
  "development_mae_context_log10",
  "within_one_development_mae_of_first",
  "ranking_context",
  "glp1r_log10_ec50_pm",
  "glp1r_ec50_pm",
  "gcgr_log10_ec50_pm",
  "gcgr_ec50_pm",
  "selectivity_log10_gcgr_over_glp1r",
  "applicability_tier",
  "applicability_evidence_state",
  "exact_reference_match",
  "nearest_aligned_identity",
  "nearest_reference_ids",
  "standard_residue_count",
  "duplicate_sequence_count",
  "software_version",
  "artifact_id",
  "artifact_version",
  "artifact_sha256",
  "endpoint_warning",
  "validation_warning",
  "ranking_warning",
]);

const SINGLE_OUTPUT_COLUMNS = Object.freeze([
  "original_sequence",
  "aligned_sequence",
  "alignment_method",
  "alignment_status",
  "alignment_reference_ids",
  "alignment_adapter_id",
  "alignment_adapter_version",
  "alignment_adapter_sha256",
  "glp1r_log10_ec50_pm",
  "glp1r_ec50_pm",
  "glp1r_ec50_nm",
  "gcgr_log10_ec50_pm",
  "gcgr_ec50_pm",
  "gcgr_ec50_nm",
  "selectivity_log10_gcgr_over_glp1r",
  "selectivity_ec50_fold_ratio",
  "selectivity_interpretation",
  "applicability_tier",
  "nearest_aligned_identity",
  "nearest_reference_ids",
  "standard_residue_count",
  "exploratory_ranking_enabled",
  "exploratory_ranking_exclusion_reason",
  "comparison_reference_id",
  "changed_position_count",
  "glp1r_delta_log10_ec50_pm_vs_reference",
  "gcgr_delta_log10_ec50_pm_vs_reference",
  "glp1r_ec50_fold_ratio_vs_reference",
  "gcgr_ec50_fold_ratio_vs_reference",
  "software_version",
  "artifact_id",
  "artifact_version",
  "artifact_sha256",
  "endpoint_warning",
  "validation_warning",
]);

const ENDPOINT_WARNING = (
  "Cell-based cAMP EC50 functional-potency estimate; not binding affinity, " +
  "maximal assay response, safety, or drug validation."
);
const RANKING_WARNING = (
  "Exploratory model ordering for experiment planning; not an experimental recommendation."
);
const CANDIDATE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const textEncoder = new TextEncoder();

function assertTextWithinLimit(value, label) {
  if (typeof value !== "string") throw new Error(`${label} must be text.`);
  const size = textEncoder.encode(value).byteLength;
  if (size > MAX_BROWSER_BYTES) {
    throw new Error(
      `${label} is ${size} bytes; the browser limit is ${MAX_BROWSER_BYTES} bytes.`,
    );
  }
  return value.startsWith("\uFEFF") ? value.slice(1) : value;
}

/** Decode uploaded bytes strictly so receipts can bind the original file. */
export function decodeUtf8Bytes(value, label = "Input file") {
  let bytes;
  if (value instanceof ArrayBuffer) bytes = new Uint8Array(value);
  else if (ArrayBuffer.isView(value)) {
    bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  } else {
    throw new Error(`${label} must be supplied as bytes.`);
  }
  if (bytes.byteLength > MAX_BROWSER_BYTES) {
    throw new Error(
      `${label} is ${bytes.byteLength} bytes; the browser limit is ${MAX_BROWSER_BYTES} bytes.`,
    );
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error) {
    throw new Error(`${label} must be valid UTF-8.`);
  }
}

function assertArtifactSha256(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error("A verified lowercase SHA-256 model checksum is required.");
  }
}

/** Parse exactly one FASTA record under an explicit raw or expert input mode. */
export function parseSingleFasta(value, model, inputMode = "raw_sequence") {
  const text = assertTextWithinLimit(value, "FASTA input");
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  while (lines.length && !lines[0].trim()) lines.shift();
  while (lines.length && !lines.at(-1).trim()) lines.pop();
  if (!lines.length || !lines[0].startsWith(">")) {
    throw new Error("FASTA input must begin with one '>' header line.");
  }
  const header = lines[0].slice(1).trim();
  if (!header) throw new Error("FASTA header is empty.");
  if (lines.slice(1).some((line) => line.startsWith(">"))) {
    throw new Error("Single-sequence mode accepts exactly one FASTA record.");
  }
  const sequenceText = lines.slice(1).join("");
  if (!sequenceText.trim()) throw new Error("FASTA record has no sequence.");
  if (!new Set(["raw_sequence", "provided_alignment"]).has(inputMode)) {
    throw new Error("FASTA input mode must be raw_sequence or provided_alignment.");
  }
  const prepared = inputMode === "provided_alignment"
    ? {
      originalSequence: normalizeSequence(sequenceText, model),
      alignedSequence: normalizeSequence(sequenceText, model),
      alignmentStatus: "provided",
    }
    : prepareRawSequence(sequenceText, model);
  return {
    header,
    inputSequence: prepared.originalSequence,
    alignedSequence: prepared.alignedSequence,
    alignmentStatus: prepared.alignmentStatus,
    inputMode,
  };
}

function parseCsvRows(text, maximumRows = Number.POSITIVE_INFINITY) {
  const rows = [];
  let row = [];
  let field = "";
  let index = 0;
  let quoted = false;
  let quoteClosed = false;
  let fieldStarted = false;

  const finishField = () => {
    row.push(field);
    field = "";
    fieldStarted = false;
    quoteClosed = false;
  };
  const finishRow = () => {
    finishField();
    const blank = row.length === 1 && row[0] === "";
    if (!blank || rows.length === 0) {
      rows.push(row);
      if (rows.length > maximumRows) {
        throw new Error(
          `CSV input exceeds the browser limit of ${maximumRows - 1} candidate rows.`,
        );
      }
    }
    row = [];
  };

  while (index < text.length) {
    const character = text[index];
    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 2;
          continue;
        }
        quoted = false;
        quoteClosed = true;
        index += 1;
        continue;
      }
      field += character;
      index += 1;
      continue;
    }

    if (quoteClosed && character !== "," && character !== "\r" && character !== "\n") {
      throw new Error(
        `Malformed CSV: unexpected character after a closing quote at byte ${index}.`,
      );
    }
    if (character === '"') {
      if (fieldStarted || field) {
        throw new Error(`Malformed CSV: quote inside an unquoted field at byte ${index}.`);
      }
      quoted = true;
      fieldStarted = true;
      index += 1;
      continue;
    }
    if (character === ",") {
      finishField();
      index += 1;
      continue;
    }
    if (character === "\r" || character === "\n") {
      finishRow();
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      index += 1;
      continue;
    }
    field += character;
    fieldStarted = true;
    index += 1;
  }
  if (quoted) throw new Error("Malformed CSV: unterminated quoted field.");
  if (fieldStarted || quoteClosed || field || row.length) finishRow();
  return rows;
}

/** Parse the bounded browser batch schema without silently dropping rows. */
export function parseCandidateCsv(value) {
  const text = assertTextWithinLimit(value, "CSV input");
  const rows = parseCsvRows(text, MAX_BROWSER_ROWS + 1);
  if (!rows.length) throw new Error("CSV input is empty.");
  const header = rows[0].map((name) => name.trim());
  const isRaw = (
    header.length === RAW_INPUT_COLUMNS.length &&
    new Set(header).size === RAW_INPUT_COLUMNS.length &&
    header.every((name) => RAW_INPUT_COLUMNS.includes(name))
  );
  const isAligned = (
    header.length === ALIGNED_INPUT_COLUMNS.length &&
    new Set(header).size === ALIGNED_INPUT_COLUMNS.length &&
    header.every((name) => ALIGNED_INPUT_COLUMNS.includes(name))
  );
  if (!isRaw && !isAligned) {
    throw new Error(
      "CSV must contain exactly candidate_id,sequence (raw adapter) or " +
      "candidate_id,aligned_sequence (expert 30-column mode).",
    );
  }
  const dataRows = rows.slice(1).filter(
    (cells) => !(cells.length === 1 && cells[0] === ""),
  );
  if (!dataRows.length) throw new Error("CSV input contains no candidate rows.");
  if (dataRows.length > MAX_BROWSER_ROWS) {
    throw new Error(
      `CSV input has ${dataRows.length} rows; the browser limit is ${MAX_BROWSER_ROWS}.`,
    );
  }
  if (isRaw && dataRows.length > MAX_BROWSER_RAW_ROWS) {
    throw new Error(
      `Raw-sequence CSV input has ${dataRows.length} rows; the browser adapter limit ` +
      `is ${MAX_BROWSER_RAW_ROWS}. Use a smaller shortlist or reviewed 30-column input.`,
    );
  }
  const idIndex = header.indexOf("candidate_id");
  const sequenceIndex = header.indexOf(isRaw ? "sequence" : "aligned_sequence");
  const records = dataRows.map((originalCells, index) => {
    if (originalCells.length > INPUT_COLUMNS.length) {
      throw new Error(
        `CSV candidate row ${index + 1} has ${originalCells.length} fields; expected 2.`,
      );
    }
    const cells = [...originalCells];
    while (cells.length < INPUT_COLUMNS.length) cells.push("");
    return {
      candidateId: cells[idIndex].trim(),
      inputSequence: cells[sequenceIndex],
      inputMode: isRaw ? "raw_sequence" : "provided_alignment",
      alignedSequence: isAligned ? cells[sequenceIndex] : "",
    };
  });
  const seen = new Set();
  const duplicates = new Set();
  for (const record of records) {
    if (!record.candidateId) continue;
    if (seen.has(record.candidateId)) duplicates.add(record.candidateId);
    seen.add(record.candidateId);
  }
  if (duplicates.size) {
    const preview = [...duplicates].sort().slice(0, 5).join(", ");
    const suffix = duplicates.size > 5 ? ` (+${duplicates.size - 5} more)` : "";
    throw new Error(`Candidate IDs must be unique; duplicates: ${preview}${suffix}.`);
  }
  return records;
}

function rankingScore(result, objective) {
  const glp1r = Number(result.predictions.glp1r.log10Ec50Pm);
  const gcgr = Number(result.predictions.gcgr.log10Ec50Pm);
  if (objective === "glp1r") return glp1r;
  if (objective === "gcgr") return gcgr;
  return Math.max(glp1r, gcgr);
}

function developmentMaeContext(model, objective) {
  const metrics = model.benchmark_context?.metrics ?? {};
  if (objective === "glp1r" || objective === "gcgr") {
    return {
      value: Number(metrics[objective]?.development_oof_mae_log10),
      source: `${objective}_development_oof_mae_log10`,
      interpretation: (
        "Population-level development out-of-fold MAE for this receptor; " +
        "not an individual confidence interval or significance threshold."
      ),
    };
  }
  return {
    value: Math.max(
      Number(metrics.glp1r?.development_oof_mae_log10),
      Number(metrics.gcgr?.development_oof_mae_log10),
    ),
    source: "larger_receptor_development_oof_mae_log10",
    interpretation: (
      "Conservative descriptive reference for the dual max-receptor score; the dual " +
      "objective was not benchmarked as a separate endpoint. This is not an individual " +
      "confidence interval or significance threshold."
    ),
  };
}

function numberString(value) {
  if (!Number.isFinite(value)) throw new Error("Prediction contains a non-finite number.");
  return Number(value.toPrecision(15)).toString();
}

function blankScreeningRow(inputRow, record, objective, model, artifactSha256) {
  return {
    input_row: String(inputRow),
    candidate_id: record.candidateId,
    input_sequence: record.inputSequence.trim(),
    input_mode: record.inputMode,
    aligned_sequence: record.inputMode === "provided_alignment" ? record.inputSequence.trim() : "",
    alignment_method: "",
    alignment_status: "",
    alignment_reference_ids: "",
    alignment_adapter_id: "",
    alignment_adapter_version: "",
    alignment_adapter_sha256: "",
    status: "",
    error_code: "",
    error_message: "",
    ranking_objective: objective,
    ranking_objective_definition: OBJECTIVES[objective].definition,
    ranking_eligible: "false",
    ranking_exclusion_reason: "",
    rank: "",
    ranking_score: "",
    score_delta_from_first_log10: "",
    score_fold_ratio_from_first: "",
    development_mae_context_log10: "",
    within_one_development_mae_of_first: "",
    ranking_context: "",
    glp1r_log10_ec50_pm: "",
    glp1r_ec50_pm: "",
    gcgr_log10_ec50_pm: "",
    gcgr_ec50_pm: "",
    selectivity_log10_gcgr_over_glp1r: "",
    applicability_tier: "",
    applicability_evidence_state: "",
    exact_reference_match: "",
    nearest_aligned_identity: "",
    nearest_reference_ids: "",
    standard_residue_count: "",
    duplicate_sequence_count: "",
    software_version: String(model.software_version ?? SOFTWARE_VERSION),
    artifact_id: String(model.artifact_id ?? ""),
    artifact_version: String(model.artifact_version ?? ""),
    artifact_sha256: artifactSha256,
    endpoint_warning: ENDPOINT_WARNING,
    validation_warning: String(model.benchmark_context?.external_evaluation ?? ""),
    ranking_warning: RANKING_WARNING,
  };
}

/** Apply the same conservative ranking policy as the Python batch interface. */
export function screenCandidates(records, objective, model, artifactSha256) {
  if (!Object.hasOwn(OBJECTIVES, objective)) {
    throw new Error("Choose one ranking objective: glp1r, gcgr, or dual.");
  }
  if (!Array.isArray(records) || !records.length) {
    throw new Error("At least one candidate row is required.");
  }
  if (records.length > MAX_BROWSER_ROWS) {
    throw new Error(`The browser screening limit is ${MAX_BROWSER_ROWS} candidates.`);
  }
  assertArtifactSha256(artifactSha256);
  const normalizedRecords = records.map((record) => ({
    candidateId: String(record?.candidateId ?? "").trim(),
    inputSequence: String(record?.inputSequence ?? record?.alignedSequence ?? ""),
    inputMode: record?.inputMode === "raw_sequence"
      ? "raw_sequence"
      : "provided_alignment",
  }));
  if (
    normalizedRecords.some((record) => record.inputMode === "raw_sequence") &&
    normalizedRecords.length > MAX_BROWSER_RAW_ROWS
  ) {
    throw new Error(
      `Raw-sequence screening has ${normalizedRecords.length} rows; the browser ` +
      `adapter limit is ${MAX_BROWSER_RAW_ROWS}.`,
    );
  }
  const seenIds = new Set();
  const duplicateIds = new Set();
  for (const record of normalizedRecords) {
    if (!record.candidateId) continue;
    if (seenIds.has(record.candidateId)) duplicateIds.add(record.candidateId);
    seenIds.add(record.candidateId);
  }
  if (duplicateIds.size) {
    const preview = [...duplicateIds].sort().slice(0, 5).join(", ");
    const suffix = duplicateIds.size > 5 ? ` (+${duplicateIds.size - 5} more)` : "";
    throw new Error(`Candidate IDs must be unique; duplicates: ${preview}${suffix}.`);
  }
  const rows = [];
  const scores = new Map();
  const sequenceCounts = new Map();
  const predictionCache = new Map();

  normalizedRecords.forEach((record, index) => {
    const inputRow = index + 1;
    const row = blankScreeningRow(inputRow, record, objective, model, artifactSha256);
    if (!CANDIDATE_ID_PATTERN.test(record.candidateId)) {
      row.status = "input_error";
      row.error_code = "invalid_candidate_id";
      row.error_message = (
        "Candidate ID must start with a letter or number and contain at most 128 " +
        "letters, numbers, '.', '_', ':', or '-'."
      );
      rows.push(row);
      return;
    }

    // Keep pre-validation characters distinct. Unicode uppercasing can expand a
    // glyph, so an uppercased key could otherwise alias an invalid and valid row.
    const cacheKey = `${record.inputMode}\0${record.inputSequence.replace(/\s/g, "")}`;
    let cached = predictionCache.get(cacheKey);
    if (!cached) {
      try {
        cached = {
          result: record.inputMode === "raw_sequence"
            ? predictRawFromModel(record.inputSequence, model)
            : predictFromModel(record.inputSequence, model),
        };
      } catch (error) {
        cached = { error: error instanceof Error ? error.message : String(error) };
      }
      predictionCache.set(cacheKey, cached);
    }
    if (cached.error) {
      row.status = "input_error";
      row.error_code = record.inputMode === "raw_sequence"
        ? "invalid_raw_sequence"
        : "invalid_aligned_sequence";
      row.error_message = cached.error;
      rows.push(row);
      return;
    }
    const result = cached.result;

    const normalized = result.input.alignedSequence;
    const residueCount = Number(result.input.standardResidueCount);
    const scope = result.applicability;
    const exclusions = [];
    if (scope.tier !== "close_analogue") {
      exclusions.push(`applicability_tier=${scope.tier}`);
    }
    if (residueCount < MIN_RANKING_RESIDUES) {
      exclusions.push(
        `standard_residue_count=${residueCount} is below ${MIN_RANKING_RESIDUES}`,
      );
    }
    const eligible = exclusions.length === 0;
    const score = rankingScore(result, objective);
    sequenceCounts.set(normalized, (sequenceCounts.get(normalized) ?? 0) + 1);
    if (eligible) scores.set(inputRow, score);
    row.aligned_sequence = normalized;
    row.alignment_method = result.input.alignmentMethod;
    row.alignment_status = result.input.alignmentStatus;
    row.alignment_reference_ids = result.input.alignmentReferenceIds.join(";");
    row.alignment_adapter_id = result.input.alignmentAdapterId ?? "";
    row.alignment_adapter_version = result.input.alignmentAdapterVersion ?? "";
    row.alignment_adapter_sha256 = result.input.alignmentAdapterSha256 ?? "";
    row.status = eligible ? "pending_rank" : "not_ranked_out_of_scope";
    row.ranking_eligible = eligible ? "true" : "false";
    row.ranking_exclusion_reason = exclusions.join("; ");
    row.ranking_score = eligible ? numberString(score) : "";
    row.glp1r_log10_ec50_pm = numberString(result.predictions.glp1r.log10Ec50Pm);
    row.glp1r_ec50_pm = numberString(result.predictions.glp1r.ec50Pm);
    row.gcgr_log10_ec50_pm = numberString(result.predictions.gcgr.log10Ec50Pm);
    row.gcgr_ec50_pm = numberString(result.predictions.gcgr.ec50Pm);
    row.selectivity_log10_gcgr_over_glp1r = numberString(
      result.predictions.selectivity.log10Ec50Ratio,
    );
    row.applicability_tier = scope.tier;
    row.applicability_evidence_state = scope.evidenceState;
    row.exact_reference_match = scope.exactReferenceMatch ? "true" : "false";
    row.nearest_aligned_identity = numberString(scope.nearestAlignedIdentity);
    row.nearest_reference_ids = scope.nearestReferenceIds.join(";");
    row.standard_residue_count = String(residueCount);
    rows.push(row);
  });

  for (const row of rows) {
    if (row.status !== "input_error") {
      row.duplicate_sequence_count = String(sequenceCounts.get(row.aligned_sequence));
    }
  }
  const eligibleRows = rows
    .filter((row) => row.status === "pending_rank")
    .sort((left, right) => {
      const delta = scores.get(Number(left.input_row)) - scores.get(Number(right.input_row));
      return delta || Number(left.input_row) - Number(right.input_row);
    });
  const maeContext = developmentMaeContext(model, objective);
  if (!Number.isFinite(maeContext.value) || maeContext.value < 0) {
    throw new Error("Model benchmark context is missing a valid development MAE.");
  }
  const bestScore = eligibleRows.length
    ? scores.get(Number(eligibleRows[0].input_row))
    : null;
  let rank = 0;
  let previousScore = null;
  for (const row of eligibleRows) {
    const score = scores.get(Number(row.input_row));
    if (previousScore === null || Math.abs(score - previousScore) > RANKING_TIE_TOLERANCE) {
      rank += 1;
      previousScore = score;
    }
    row.rank = String(rank);
    row.status = "ranked";
    const delta = bestScore === null ? 0 : score - bestScore;
    const withinContext = delta <= maeContext.value + RANKING_TIE_TOLERANCE;
    row.score_delta_from_first_log10 = numberString(delta);
    row.score_fold_ratio_from_first = numberString(10 ** delta);
    row.development_mae_context_log10 = numberString(maeContext.value);
    row.within_one_development_mae_of_first = withinContext ? "true" : "false";
    row.ranking_context = withinContext
      ? "within_one_development_mae_of_first"
      : "more_than_one_development_mae_from_first";
  }
  const remainder = rows
    .filter((row) => row.status !== "ranked")
    .sort((left, right) => Number(left.input_row) - Number(right.input_row));
  const ordered = [...eligibleRows, ...remainder];
  const counts = {
    total_rows: rows.length,
    valid_prediction_rows: rows.filter((row) => row.status !== "input_error").length,
    input_error_rows: rows.filter((row) => row.status === "input_error").length,
    ranking_eligible_rows: eligibleRows.length,
    ranked_rows: eligibleRows.length,
    out_of_scope_rows: rows.filter(
      (row) => row.status === "not_ranked_out_of_scope",
    ).length,
    within_one_development_mae_of_first_rows: rows.filter(
      (row) => row.within_one_development_mae_of_first === "true",
    ).length,
  };
  let status = "completed";
  let exitCode = 0;
  if (!counts.ranking_eligible_rows) {
    status = "no_rankable_rows";
    exitCode = 3;
  } else if (counts.input_error_rows) {
    status = "completed_with_row_errors";
    exitCode = 1;
  }
  return { rows: ordered, counts, status, exitCode };
}

/** Prefix spreadsheet-formula leaders without changing the in-memory result. */
export function spreadsheetSafeText(value) {
  const controlCharacters = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;
  const text = String(value ?? "").replace(controlCharacters, (character) => (
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`
  ));
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

function csvCell(value, formulaSafe = false) {
  const text = String(value ?? "");
  const safe = formulaSafe ? spreadsheetSafeText(text) : text;
  return /[",\r\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

function renderRows(columns, rows, formulaSafeColumns = new Set()) {
  const lines = [columns.map((column) => csvCell(column)).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => (
      csvCell(row[column], formulaSafeColumns.has(column))
    )).join(","));
  }
  return `${lines.join("\n")}\n`;
}

export function renderScreeningCsv(rows) {
  return renderRows(
    SCREENING_OUTPUT_COLUMNS,
    rows,
    new Set(["candidate_id", "input_sequence", "aligned_sequence"]),
  );
}

function thresholdNote() {
  return (
    "The 0.85 threshold defines sequence-identity components in the benchmark; " +
    "0.70 is an interface heuristic. Neither is calibrated to prediction error."
  );
}

/** Convert the browser result to an auditable, Python-compatible document. */
export function buildSingleResultDocument(result, model, artifactSha256) {
  assertArtifactSha256(artifactSha256);
  return {
    schema_version: 1,
    model: {
      software_version: String(model.software_version ?? SOFTWARE_VERSION),
      artifact_id: String(model.artifact_id ?? ""),
      artifact_version: String(model.artifact_version ?? ""),
      artifact_sha256: artifactSha256,
      selected_alpha: Number(model.model?.selected_alpha),
      training_records: Number(model.applicability_reference?.sequences?.length),
    },
    input: {
      original_sequence: result.input.originalSequence,
      aligned_sequence: result.input.alignedSequence,
      aligned_length: result.input.alignedSequence.length,
      standard_residue_count: result.input.standardResidueCount,
      alignment_gaps: [...result.input.alignedSequence].filter((symbol) => symbol === "-").length,
      input_residue_count: result.input.inputResidueCount,
      alignment_method: result.input.alignmentMethod,
      alignment_status: result.input.alignmentStatus,
      alignment_reference_ids: [...result.input.alignmentReferenceIds],
      alignment_score: result.input.alignmentScore,
      alignment_note: result.input.alignmentNote,
      alignment_adapter_id: result.input.alignmentAdapterId,
      alignment_adapter_version: result.input.alignmentAdapterVersion,
      alignment_adapter_sha256: result.input.alignmentAdapterSha256,
    },
    predictions: {
      gcgr: {
        endpoint: "cAMP accumulation EC50",
        log10_ec50_pm: result.predictions.gcgr.log10Ec50Pm,
        ec50_pm: result.predictions.gcgr.ec50Pm,
        ec50_nm: result.predictions.gcgr.ec50Pm / 1000,
      },
      glp1r: {
        endpoint: "cAMP accumulation EC50",
        log10_ec50_pm: result.predictions.glp1r.log10Ec50Pm,
        ec50_pm: result.predictions.glp1r.ec50Pm,
        ec50_nm: result.predictions.glp1r.ec50Pm / 1000,
      },
      selectivity: {
        definition: "GCGR EC50 / GLP-1R EC50",
        log10_ec50_ratio: result.predictions.selectivity.log10Ec50Ratio,
        ec50_fold_ratio: result.predictions.selectivity.ec50FoldRatio,
        interpretation: result.predictions.selectivity.interpretation,
        interpretation_boundary: (
          "The three-fold wording is descriptive, not a validated decision cutoff."
        ),
      },
    },
    applicability: {
      tier: result.applicability.tier,
      evidence_state: result.applicability.evidenceState,
      exact_reference_match: result.applicability.exactReferenceMatch,
      nearest_aligned_identity: result.applicability.nearestAlignedIdentity,
      nearest_reference_ids: [...result.applicability.nearestReferenceIds],
      nearest_component_ids: [...result.applicability.nearestComponentIds],
      threshold_note: thresholdNote(),
      summary: result.applicability.summary,
    },
    exploratory_ranking: {
      enabled: result.exploratoryRanking.enabled,
      identity_gate: result.exploratoryRanking.identityGate,
      minimum_standard_residue_count:
        result.exploratoryRanking.minimumStandardResidueCount,
      exclusion_reasons: [...result.exploratoryRanking.exclusionReasons],
      boundary: result.exploratoryRanking.boundary,
    },
    nearest_reference_comparison: {
      reference_id: result.nearestReferenceComparison.referenceId,
      reference_component_id: result.nearestReferenceComparison.referenceComponentId,
      reference_aligned_sequence: result.nearestReferenceComparison.referenceAlignedSequence,
      nearest_reference_tie_count:
        result.nearestReferenceComparison.nearestReferenceTieCount,
      changed_position_count: result.nearestReferenceComparison.changedPositionCount,
      reference_prediction: {
        gcgr_log10_ec50_pm:
          result.nearestReferenceComparison.referencePrediction.gcgrLog10Ec50Pm,
        glp1r_log10_ec50_pm:
          result.nearestReferenceComparison.referencePrediction.glp1rLog10Ec50Pm,
      },
      query_minus_reference: {
        gcgr_delta_log10_ec50_pm:
          result.nearestReferenceComparison.queryMinusReference.gcgrDeltaLog10Ec50Pm,
        glp1r_delta_log10_ec50_pm:
          result.nearestReferenceComparison.queryMinusReference.glp1rDeltaLog10Ec50Pm,
        selectivity_delta_log10_ratio:
          result.nearestReferenceComparison.queryMinusReference.selectivityDeltaLog10Ratio,
        gcgr_ec50_fold_ratio:
          result.nearestReferenceComparison.queryMinusReference.gcgrEc50FoldRatio,
        glp1r_ec50_fold_ratio:
          result.nearestReferenceComparison.queryMinusReference.glp1rEc50FoldRatio,
      },
      position_contributions: result.nearestReferenceComparison.positionContributions.map(
        (row) => ({
          alignment_position: row.alignmentPosition,
          reference_symbol: row.referenceSymbol,
          query_symbol: row.querySymbol,
          gcgr_delta_log10_ec50_pm: row.gcgrDeltaLog10Ec50Pm,
          glp1r_delta_log10_ec50_pm: row.glp1rDeltaLog10Ec50Pm,
          selectivity_delta_log10_ratio: row.selectivityDeltaLog10Ratio,
        }),
      ),
      decomposition_max_abs_residual_log10:
        result.nearestReferenceComparison.decompositionMaxAbsResidualLog10,
      interpretation: result.nearestReferenceComparison.interpretation,
      scientific_boundary: result.nearestReferenceComparison.scientificBoundary,
    },
    benchmark_context: model.benchmark_context,
    warnings: [...result.warnings],
  };
}

export function renderSingleResultJson(result, model, artifactSha256) {
  return `${JSON.stringify(buildSingleResultDocument(result, model, artifactSha256), null, 2)}\n`;
}

export function renderSingleResultCsv(result, model, artifactSha256) {
  const document = buildSingleResultDocument(result, model, artifactSha256);
  const predictions = document.predictions;
  const applicability = document.applicability;
  const comparison = document.nearest_reference_comparison;
  const delta = comparison.query_minus_reference;
  const ranking = document.exploratory_ranking;
  const row = {
    original_sequence: document.input.original_sequence,
    aligned_sequence: document.input.aligned_sequence,
    alignment_method: document.input.alignment_method,
    alignment_status: document.input.alignment_status,
    alignment_reference_ids: document.input.alignment_reference_ids.join(";"),
    alignment_adapter_id: document.input.alignment_adapter_id ?? "",
    alignment_adapter_version: document.input.alignment_adapter_version ?? "",
    alignment_adapter_sha256: document.input.alignment_adapter_sha256 ?? "",
    glp1r_log10_ec50_pm: predictions.glp1r.log10_ec50_pm,
    glp1r_ec50_pm: predictions.glp1r.ec50_pm,
    glp1r_ec50_nm: predictions.glp1r.ec50_nm,
    gcgr_log10_ec50_pm: predictions.gcgr.log10_ec50_pm,
    gcgr_ec50_pm: predictions.gcgr.ec50_pm,
    gcgr_ec50_nm: predictions.gcgr.ec50_nm,
    selectivity_log10_gcgr_over_glp1r: predictions.selectivity.log10_ec50_ratio,
    selectivity_ec50_fold_ratio: predictions.selectivity.ec50_fold_ratio,
    selectivity_interpretation: predictions.selectivity.interpretation,
    applicability_tier: applicability.tier,
    nearest_aligned_identity: applicability.nearest_aligned_identity,
    nearest_reference_ids: applicability.nearest_reference_ids.join(";"),
    standard_residue_count: document.input.standard_residue_count,
    exploratory_ranking_enabled: ranking.enabled ? "true" : "false",
    exploratory_ranking_exclusion_reason: ranking.exclusion_reasons.join(" "),
    comparison_reference_id: comparison.reference_id,
    changed_position_count: comparison.changed_position_count,
    glp1r_delta_log10_ec50_pm_vs_reference: delta.glp1r_delta_log10_ec50_pm,
    gcgr_delta_log10_ec50_pm_vs_reference: delta.gcgr_delta_log10_ec50_pm,
    glp1r_ec50_fold_ratio_vs_reference: delta.glp1r_ec50_fold_ratio,
    gcgr_ec50_fold_ratio_vs_reference: delta.gcgr_ec50_fold_ratio,
    software_version: document.model.software_version,
    artifact_id: document.model.artifact_id,
    artifact_version: document.model.artifact_version,
    artifact_sha256: document.model.artifact_sha256,
    endpoint_warning: ENDPOINT_WARNING,
    validation_warning: String(model.benchmark_context?.external_evaluation ?? ""),
  };
  return renderRows(
    SINGLE_OUTPUT_COLUMNS,
    [row],
    new Set(["original_sequence", "aligned_sequence"]),
  );
}

function markdownNumber(value) {
  if (value === 0) return "0";
  if (Math.abs(value) >= 10000 || Math.abs(value) < 0.001) return value.toExponential(4);
  return value.toFixed(4).replace(/\.?0+$/, "");
}

function comparisonStatus(evidenceState, rankingEnabled) {
  if (evidenceState === "training_reference_match") {
    return "In-sample reference · not an independent prediction";
  }
  return rankingEnabled
    ? "Eligible for exploratory comparison"
    : "Do not use for candidate ranking";
}

function validationEvidence(evidenceState) {
  if (evidenceState === "training_reference_match") return "In-sample evidence only";
  if (evidenceState === "local_analogue_mixed_evidence") {
    return "Mixed retrospective transfer";
  }
  return "No supported transfer evidence";
}

function foldComparison(foldRatio, receptor) {
  if (Math.abs(foldRatio - 1) <= 1e-12) {
    return `${receptor} EC50 is unchanged from the closest development sequence.`;
  }
  if (foldRatio > 1) {
    return `Query ${receptor} EC50 is predicted ${markdownNumber(foldRatio)}× higher than ` +
      "the closest development sequence.";
  }
  return `Query ${receptor} EC50 is predicted ${markdownNumber(1 / foldRatio)}× lower than ` +
    "the closest development sequence.";
}

/** Render a concise human-readable result for lab notes or review. */
export function renderSingleResultMarkdown(result, model, artifactSha256) {
  const document = buildSingleResultDocument(result, model, artifactSha256);
  const predictions = document.predictions;
  const applicability = document.applicability;
  const comparison = document.nearest_reference_comparison;
  const delta = comparison.query_minus_reference;
  const ranking = document.exploratory_ranking;
  const applicabilityLabels = {
    training_reference_match: "Training-set match · in-sample",
    local_analogue_mixed_evidence: "Within local-analog scope · exploratory use",
    outside_ranking_scope: "Outside supported comparison scope",
    far_outside_ranking_scope: "Distant extrapolation · do not rank",
  };
  const applicabilityLabel = applicabilityLabels[applicability.evidence_state]
    ?? "Applicability unavailable";
  const comparisonState = comparisonStatus(applicability.evidence_state, ranking.enabled);
  const evidence = validationEvidence(applicability.evidence_state);
  const ratio = predictions.selectivity.ec50_fold_ratio;
  const ratioSentence = ratio >= 3
    ? `GCGR EC50 is predicted to be ${markdownNumber(ratio)}× higher than GLP-1R EC50.`
    : ratio <= 1 / 3
    ? `GLP-1R EC50 is predicted to be ${markdownNumber(1 / ratio)}× higher than GCGR EC50.`
    : `The two predicted EC50 values are within ` +
      `${markdownNumber(Math.max(ratio, 1 / ratio))}×.`;
  const lines = [
    "# IncretinSelect-AI result",
    "",
    "## Result overview",
    "",
    "| Question | Assessment |",
    "|:--|:--|",
    `| Model applicability | ${applicabilityLabel} |`,
    `| Comparison status | ${comparisonState} |`,
    `| Predicted receptor profile | ${predictions.selectivity.interpretation} |`,
    `| Validation evidence | ${evidence} |`,
    "",
    `**Input sequence:** \`${document.input.original_sequence}\`  `,
    `**Model alignment:** \`${document.input.aligned_sequence}\`  `,
    `**Input mapping:** ${document.input.alignment_note}`,
    "",
    "## Predicted functional potency",
    "",
    "Cell-based cAMP EC50 in the source assay; lower predicted EC50 means greater " +
      "functional potency in that assay.",
    "",
    "| Receptor | pM | nM | Model scale: log10(EC50 / 1 pM) |",
    "|:--|--:|--:|--:|",
    `| GLP-1R | ${markdownNumber(predictions.glp1r.ec50_pm)} | ` +
      `${markdownNumber(predictions.glp1r.ec50_nm)} | ` +
      `${predictions.glp1r.log10_ec50_pm.toFixed(4)} |`,
    `| GCGR | ${markdownNumber(predictions.gcgr.ec50_pm)} | ` +
      `${markdownNumber(predictions.gcgr.ec50_nm)} | ` +
      `${predictions.gcgr.log10_ec50_pm.toFixed(4)} |`,
    "",
    `**Predicted receptor profile: ${predictions.selectivity.interpretation}.** ` +
      ratioSentence,
    "This describes functional-potency balance, not binding selectivity or evidence " +
      "of dual agonism.",
    "",
    "## Model applicability",
    "",
    `- Assessment: ${applicabilityLabel}`,
    `- Nearest aligned identity: ${(applicability.nearest_aligned_identity * 100).toFixed(1)}%`,
    `- Nearest reference: \`${comparison.reference_id}\``,
    `- Changed alignment positions: ${comparison.changed_position_count}`,
    `- Meaning: ${applicability.summary}`,
    `- Candidate comparison: ${comparisonState}`,
    "",
    "## Comparison with the closest development sequence",
    "",
    "| Endpoint | Plain-language comparison | Δ log10 EC50 |",
    "|:--|:--|--:|",
    `| GLP-1R | ${foldComparison(delta.glp1r_ec50_fold_ratio, "GLP-1R")} | ` +
      `${delta.glp1r_delta_log10_ec50_pm.toFixed(4)} |`,
    `| GCGR | ${foldComparison(delta.gcgr_ec50_fold_ratio, "GCGR")} | ` +
      `${delta.gcgr_delta_log10_ec50_pm.toFixed(4)} |`,
    "",
  ];
  if (comparison.position_contributions.length) {
    lines.push(
      "| Position | Reference | Query | GLP-1R contribution | GCGR contribution |",
      "|--:|:--:|:--:|--:|--:|",
    );
    for (const row of comparison.position_contributions) {
      lines.push(
        `| ${row.alignment_position} | \`${row.reference_symbol}\` | ` +
          `\`${row.query_symbol}\` | ${row.glp1r_delta_log10_ec50_pm.toFixed(4)} | ` +
          `${row.gcgr_delta_log10_ec50_pm.toFixed(4)} |`,
      );
    }
    lines.push("");
  } else {
    lines.push("The query is identical to the selected nearest reference.", "");
  }
  if (ranking.exclusion_reasons.length) {
    lines.push(
      "> **Do not use this output to rank experiments.** " +
        ranking.exclusion_reasons.join(" "),
      "",
    );
  }
  if (comparison.nearest_reference_tie_count > 1) {
    lines.push(
      `> ${comparison.nearest_reference_tie_count} references tied for nearest identity; ` +
        `\`${comparison.reference_id}\` was selected deterministically for the comparison.`,
      "",
    );
  }
  lines.push(
    `> ${comparison.scientific_boundary}`,
    "> Reference values in this report are model predictions, not observed assay values.",
    "",
    "## Benchmark performance",
    "",
    `- GLP-1R development MAE: ` +
      `${model.benchmark_context.metrics.glp1r.development_oof_mae_log10.toFixed(2)} ` +
      `log10 units (~${model.benchmark_context.metrics.glp1r.development_oof_geometric_fold_error.toFixed(1)}-fold)`,
    `- GCGR development MAE: ` +
      `${model.benchmark_context.metrics.gcgr.development_oof_mae_log10.toFixed(2)} ` +
      `log10 units (~${model.benchmark_context.metrics.gcgr.development_oof_geometric_fold_error.toFixed(1)}-fold)`,
    `- Receptor-balance development MAE: ` +
      `${model.benchmark_context.metrics.selectivity.development_oof_mae_log10.toFixed(2)} ` +
      `log10 units (~${model.benchmark_context.metrics.selectivity.development_oof_geometric_fold_error.toFixed(1)}-fold)`,
    "",
    "These are population-level cross-validated errors, not uncertainty intervals for " +
      "this peptide. Evaluation on 15 published designs showed mixed transfer and no " +
      "overall superiority over nearest-neighbor prediction.",
    "",
    "## Interpretation limits",
    "",
    "- Endpoint: cell-based cAMP EC50—not binding affinity, maximal response, safety, " +
      "stability, pharmacokinetics, or in vivo efficacy.",
    "- Chemistry: Aib, lipidation, amidation, cyclization, stapling, D-amino acids, and " +
      "other noncanonical modifications are not represented.",
    "- Applicability: estimates outside the local-analog gate are extrapolations and " +
      "should not be used for ranking.",
    "",
    `Model: \`${document.model.artifact_id}\` v${document.model.artifact_version}`,
    "",
    `Artifact SHA-256: \`${document.model.artifact_sha256}\``,
    "",
  );
  return lines.join("\n");
}

async function sha256Hex(value) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", textEncoder.encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256Bytes(value) {
  const bytes = value instanceof ArrayBuffer
    ? new Uint8Array(value)
    : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/** Build downloadable batch CSV plus a checksum-bound machine-readable receipt. */
export async function buildBatchArtifacts(value, objective, model, options = {}) {
  const artifactSha256 = options.artifactSha256;
  assertArtifactSha256(artifactSha256);
  const records = parseCandidateCsv(value);
  const alignmentAdapter = validateAlignmentAdapter(model.raw_alignment_adapter);
  const alignmentAdapterSha256 = String(model.raw_alignment_adapter_sha256 ?? "");
  if (!/^[0-9a-f]{64}$/.test(alignmentAdapterSha256)) {
    throw new Error("Raw-alignment adapter checksum is missing or invalid.");
  }
  const screening = screenCandidates(records, objective, model, artifactSha256);
  const csv = renderScreeningCsv(screening.rows);
  const inputFilename = options.inputFilename ?? "candidates.csv";
  const outputFilename = options.outputFilename ?? "screened_candidates.csv";
  const maeContext = developmentMaeContext(model, objective);
  let inputSha256;
  if (options.inputBytes !== undefined) {
    const decoded = decodeUtf8Bytes(options.inputBytes, "Candidate CSV");
    if (decoded !== value) {
      throw new Error("Candidate CSV bytes do not match the parsed text.");
    }
    inputSha256 = await sha256Bytes(options.inputBytes);
  } else {
    inputSha256 = await sha256Hex(value);
  }
  const receipt = {
    schema_version: 1,
    tool: "incretinselect-browser-screen",
    status: screening.status,
    exit_code: screening.exitCode,
    input: {
      filename: inputFilename,
      sha256: inputSha256,
      accepted_column_schemas: [
        [...RAW_INPUT_COLUMNS],
        [...ALIGNED_INPUT_COLUMNS],
      ],
      input_mode: records[0].inputMode,
      maximum_rows: records[0].inputMode === "raw_sequence"
        ? MAX_BROWSER_RAW_ROWS
        : MAX_BROWSER_ROWS,
      raw_sequence_maximum_rows: MAX_BROWSER_RAW_ROWS,
      expert_alignment_maximum_rows: MAX_BROWSER_ROWS,
      maximum_bytes: MAX_BROWSER_BYTES,
    },
    output: {
      filename: outputFilename,
      sha256: await sha256Hex(csv),
      columns: [...SCREENING_OUTPUT_COLUMNS],
    },
    objective: {
      name: objective,
      definition: OBJECTIVES[objective].definition,
      direction: "lower score ranks first",
    },
    ranking_gate: {
      required_applicability_tier: "close_analogue",
      minimum_standard_residue_count: MIN_RANKING_RESIDUES,
      scientific_boundary: (
        "This software gate enables exploratory ordering; it is not a calibrated " +
        "accuracy or validation threshold."
      ),
      tie_policy: (
        "dense rank when scores are equal within absolute tolerance 1e-12; " +
        "input order breaks display ties"
      ),
    },
    ranking_context: {
      development_mae_log10: maeContext.value,
      source: maeContext.source,
      interpretation: maeContext.interpretation,
      row_field: "score_delta_from_first_log10",
    },
    counts: screening.counts,
    model: {
      software_version: String(model.software_version ?? SOFTWARE_VERSION),
      artifact_id: String(model.artifact_id ?? ""),
      artifact_version: String(model.artifact_version ?? ""),
      artifact_sha256: artifactSha256,
      benchmark_context: model.benchmark_context,
    },
    alignment_adapter: {
      used_for_input: records[0].inputMode === "raw_sequence",
      adapter_id: alignmentAdapter.adapter_id,
      adapter_version: alignmentAdapter.adapter_version,
      sha256: alignmentAdapterSha256,
      acceptance_policy: alignmentAdapter.acceptance_policy,
      labels_accessed: alignmentAdapter.labels_accessed,
      model_coefficients_changed: alignmentAdapter.model_coefficients_changed,
    },
    scientific_boundaries: {
      endpoint: "cell-based cAMP EC50 functional potency, not binding affinity",
      experimental_recommendation_claim: false,
      holdout_labels_accessed: false,
      p1_p15_outcomes_accessed: false,
      structure_inference_run: false,
      missing_values_converted_to_negative_labels: false,
    },
  };
  return {
    ...screening,
    csv,
    receipt,
    receiptJson: `${JSON.stringify(receipt, null, 2)}\n`,
  };
}
