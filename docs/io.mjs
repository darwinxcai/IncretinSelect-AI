import { normalizeSequence, predictFromModel } from "./model.mjs";

export const MAX_BROWSER_ROWS = 500;
export const MAX_BROWSER_BYTES = 2_000_000;
export const MIN_RANKING_RESIDUES = 26;
export const RANKING_TIE_TOLERANCE = 1e-12;
export const INPUT_COLUMNS = Object.freeze(["candidate_id", "aligned_sequence"]);

export const OBJECTIVES = Object.freeze({
  glp1r: Object.freeze({
    definition: "minimize predicted GLP-1R log10 EC50 (pM)",
    scoreColumn: "glp1r_log10_ec50_pm",
  }),
  gcgr: Object.freeze({
    definition: "minimize predicted GCGR log10 EC50 (pM)",
    scoreColumn: "gcgr_log10_ec50_pm",
  }),
  dual: Object.freeze({
    definition: (
      "minimize the worse (larger) of predicted GLP-1R and GCGR log10 EC50 (pM)"
    ),
    scoreColumn: "max_receptor_log10_ec50_pm",
  }),
});

export const SCREENING_OUTPUT_COLUMNS = Object.freeze([
  "input_row",
  "candidate_id",
  "aligned_sequence",
  "status",
  "error_code",
  "error_message",
  "ranking_objective",
  "ranking_objective_definition",
  "ranking_eligible",
  "ranking_exclusion_reason",
  "rank",
  "ranking_score",
  "glp1r_log10_ec50_pm",
  "glp1r_ec50_pm",
  "gcgr_log10_ec50_pm",
  "gcgr_ec50_pm",
  "selectivity_log10_gcgr_over_glp1r",
  "applicability_tier",
  "nearest_aligned_identity",
  "nearest_reference_ids",
  "standard_residue_count",
  "duplicate_sequence_count",
  "artifact_id",
  "artifact_version",
  "artifact_sha256",
  "endpoint_warning",
  "ranking_warning",
]);

const SINGLE_OUTPUT_COLUMNS = Object.freeze([
  "aligned_sequence",
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
  "artifact_id",
  "artifact_version",
  "artifact_sha256",
  "endpoint_warning",
]);

const ENDPOINT_WARNING = (
  "Cell-based cAMP EC50 functional-potency estimate; not binding affinity, " +
  "efficacy, safety, or drug validation."
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

function assertArtifactSha256(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error("A verified lowercase SHA-256 model checksum is required.");
  }
}

/** Parse exactly one FASTA record and enforce the model's aligned-sequence contract. */
export function parseSingleFasta(value, model) {
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
  return {
    header,
    alignedSequence: normalizeSequence(sequenceText, model),
  };
}

function parseCsvRows(text) {
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
    rows.push(row);
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
  const rows = parseCsvRows(text);
  if (!rows.length) throw new Error("CSV input is empty.");
  const header = rows[0];
  if (
    header.length !== INPUT_COLUMNS.length ||
    header.some((name, index) => name !== INPUT_COLUMNS[index])
  ) {
    throw new Error(
      "CSV header must be exactly: candidate_id,aligned_sequence",
    );
  }
  const dataRows = rows.slice(1);
  if (!dataRows.length) throw new Error("CSV input contains no candidate rows.");
  if (dataRows.length > MAX_BROWSER_ROWS) {
    throw new Error(
      `CSV input has ${dataRows.length} rows; the browser limit is ${MAX_BROWSER_ROWS}.`,
    );
  }
  const records = dataRows.map((cells, index) => {
    if (cells.length !== INPUT_COLUMNS.length) {
      throw new Error(
        `CSV candidate row ${index + 1} has ${cells.length} fields; expected 2.`,
      );
    }
    return {
      candidateId: cells[0].trim(),
      alignedSequence: cells[1],
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

function numberString(value) {
  if (!Number.isFinite(value)) throw new Error("Prediction contains a non-finite number.");
  return Number(value.toPrecision(15)).toString();
}

function blankScreeningRow(inputRow, record, objective, model, artifactSha256) {
  return {
    input_row: String(inputRow),
    candidate_id: record.candidateId,
    aligned_sequence: record.alignedSequence.trim(),
    status: "",
    error_code: "",
    error_message: "",
    ranking_objective: objective,
    ranking_objective_definition: OBJECTIVES[objective].definition,
    ranking_eligible: "false",
    ranking_exclusion_reason: "",
    rank: "",
    ranking_score: "",
    glp1r_log10_ec50_pm: "",
    glp1r_ec50_pm: "",
    gcgr_log10_ec50_pm: "",
    gcgr_ec50_pm: "",
    selectivity_log10_gcgr_over_glp1r: "",
    applicability_tier: "",
    nearest_aligned_identity: "",
    nearest_reference_ids: "",
    standard_residue_count: "",
    duplicate_sequence_count: "",
    artifact_id: String(model.artifact_id ?? ""),
    artifact_version: String(model.artifact_version ?? ""),
    artifact_sha256: artifactSha256,
    endpoint_warning: ENDPOINT_WARNING,
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
    alignedSequence: String(record?.alignedSequence ?? ""),
  }));
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

    let result;
    try {
      result = predictFromModel(record.alignedSequence, model);
    } catch (error) {
      row.status = "input_error";
      row.error_code = "invalid_aligned_sequence";
      row.error_message = error instanceof Error ? error.message : String(error);
      rows.push(row);
      return;
    }

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
    new Set(["candidate_id", "aligned_sequence"]),
  );
}

function thresholdNote() {
  return (
    "The 0.85 boundary was the benchmark's sequence-family threshold. The 0.70 " +
    "lower display boundary is a conservative interface heuristic. Neither is a " +
    "calibrated probability-of-correctness cutoff."
  );
}

/** Convert the browser result to an auditable, Python-compatible document. */
export function buildSingleResultDocument(result, model, artifactSha256) {
  assertArtifactSha256(artifactSha256);
  return {
    schema_version: 1,
    model: {
      artifact_id: String(model.artifact_id ?? ""),
      artifact_version: String(model.artifact_version ?? ""),
      artifact_sha256: artifactSha256,
      selected_alpha: Number(model.model?.selected_alpha),
      training_records: Number(model.applicability_reference?.sequences?.length),
    },
    input: {
      aligned_sequence: result.input.alignedSequence,
      aligned_length: result.input.alignedSequence.length,
      standard_residue_count: result.input.standardResidueCount,
      alignment_gaps: [...result.input.alignedSequence].filter((symbol) => symbol === "-").length,
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
      nearest_aligned_identity: result.applicability.nearestAlignedIdentity,
      nearest_reference_ids: [...result.applicability.nearestReferenceIds],
      nearest_component_ids: [...result.applicability.nearestComponentIds],
      threshold_note: thresholdNote(),
      summary: result.applicability.summary,
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
  const row = {
    aligned_sequence: document.input.aligned_sequence,
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
    artifact_id: document.model.artifact_id,
    artifact_version: document.model.artifact_version,
    artifact_sha256: document.model.artifact_sha256,
    endpoint_warning: ENDPOINT_WARNING,
  };
  return renderRows(SINGLE_OUTPUT_COLUMNS, [row], new Set(["aligned_sequence"]));
}

async function sha256Hex(value) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", textEncoder.encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/** Build downloadable batch CSV plus a checksum-bound machine-readable receipt. */
export async function buildBatchArtifacts(value, objective, model, options = {}) {
  const artifactSha256 = options.artifactSha256;
  assertArtifactSha256(artifactSha256);
  const records = parseCandidateCsv(value);
  const screening = screenCandidates(records, objective, model, artifactSha256);
  const csv = renderScreeningCsv(screening.rows);
  const inputFilename = options.inputFilename ?? "candidates.csv";
  const outputFilename = options.outputFilename ?? "screened_candidates.csv";
  const receipt = {
    schema_version: 1,
    tool: "incretinselect-browser-screen",
    status: screening.status,
    exit_code: screening.exitCode,
    input: {
      filename: inputFilename,
      sha256: await sha256Hex(value),
      required_columns: [...INPUT_COLUMNS],
      maximum_rows: MAX_BROWSER_ROWS,
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
      tie_policy: (
        "dense rank when scores are equal within absolute tolerance 1e-12; " +
        "input order breaks display ties"
      ),
    },
    counts: screening.counts,
    model: {
      artifact_id: String(model.artifact_id ?? ""),
      artifact_version: String(model.artifact_version ?? ""),
      artifact_sha256: artifactSha256,
      benchmark_context: model.benchmark_context,
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
