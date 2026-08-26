export const EXAMPLE_SEQUENCE = "HSQGTFTSDYSKYLDSRAASEFVQWLISH-";

const TIER_COPY = {
  close_analogue: {
    label: "Close analogue",
    className: "close",
    summary: (
      "The input has a close aligned-sequence analogue in the 125-peptide reference " +
      "set. This supports interpolation, but does not validate the estimate."
    ),
  },
  distant_analogue: {
    label: "Distant analogue",
    className: "distant",
    summary: (
      "The input is not a close analogue of the reference peptides. Treat both " +
      "receptor estimates as high-risk extrapolations."
    ),
  },
  outside_reference_neighborhood: {
    label: "Outside reference neighborhood",
    className: "outside",
    summary: (
      "The input is far from every reference peptide. The numeric output is an " +
      "extrapolation and should not be used to rank experiments."
    ),
  },
};

export function normalizeSequence(value, model) {
  if (typeof value !== "string") throw new Error("Sequence input must be text.");
  if (value.includes(">")) {
    throw new Error("FASTA headers are not accepted. Paste one aligned sequence only.");
  }
  const sequence = value.replace(/\s/g, "").toUpperCase();
  if (!sequence) throw new Error("Sequence input is empty.");
  const length = model.input_contract.aligned_length;
  if (sequence.length !== length) {
    throw new Error(
      `This model requires exactly ${length} aligned characters; received ` +
      `${sequence.length}. The demo will not guess an alignment or trim residues.`,
    );
  }
  const alphabet = new Set(model.input_contract.alphabet);
  const invalid = [...new Set([...sequence].filter((symbol) => !alphabet.has(symbol)))].sort();
  if (invalid.length) {
    throw new Error(
      `Unsupported sequence symbols: ${invalid.join("")}. Use only standard ` +
      "amino-acid letters and '-' alignment gaps.",
    );
  }
  if ([...sequence].every((symbol) => symbol === "-")) {
    throw new Error("An all-gap sequence cannot be predicted.");
  }
  return sequence;
}

export function alignedIdentity(first, second) {
  if (first.length !== second.length) throw new Error("Aligned sequences have different lengths.");
  let comparable = 0;
  let identical = 0;
  for (let position = 0; position < first.length; position += 1) {
    const left = first[position];
    const right = second[position];
    if (left === "-" && right === "-") continue;
    comparable += 1;
    if (left === right) identical += 1;
  }
  if (!comparable) throw new Error("Aligned identity is undefined for all-gap sequences.");
  return identical / comparable;
}

function direction(selectivityLog10) {
  const foldRatio = 10 ** selectivityLog10;
  if (foldRatio >= 3) return "GLP-1R-favoured predicted functional potency";
  if (foldRatio <= 1 / 3) return "GCGR-favoured predicted functional potency";
  return "roughly balanced predicted functional potency (within three-fold)";
}

function applicability(sequence, model) {
  const references = model.applicability_reference.sequences;
  const scored = references.map((reference) => ({
    score: alignedIdentity(sequence, reference.aligned_sequence),
    peptideId: reference.peptide_id,
    componentId: reference.component_id,
  }));
  const maximum = Math.max(...scored.map((row) => row.score));
  const nearest = scored
    .filter((row) => Math.abs(row.score - maximum) <= 1e-12)
    .sort((left, right) => left.peptideId.localeCompare(right.peptideId));
  let tier = "outside_reference_neighborhood";
  if (maximum >= 0.85) tier = "close_analogue";
  else if (maximum >= 0.70) tier = "distant_analogue";
  return {
    tier,
    nearestAlignedIdentity: maximum,
    nearestReferenceIds: nearest.map((row) => row.peptideId),
    nearestComponentIds: [...new Set(nearest.map((row) => row.componentId))].sort(),
    summary: TIER_COPY[tier].summary,
  };
}

export function predictFromModel(value, model) {
  const sequence = normalizeSequence(value, model);
  const alphabet = model.input_contract.alphabet;
  const featureMean = model.model.feature_mean;
  const coefficients = model.model.coefficients;
  const values = [...model.model.target_mean];
  let featureIndex = 0;
  for (const symbol of sequence) {
    const active = alphabet.indexOf(symbol);
    for (let alphabetIndex = 0; alphabetIndex < alphabet.length; alphabetIndex += 1) {
      const centered = (alphabetIndex === active ? 1 : 0) - featureMean[featureIndex];
      values[0] += centered * coefficients[featureIndex][0];
      values[1] += centered * coefficients[featureIndex][1];
      featureIndex += 1;
    }
  }
  const [gcgrLog10, glp1rLog10] = values;
  const selectivityLog10 = gcgrLog10 - glp1rLog10;
  const scope = applicability(sequence, model);
  const residueCount = [...sequence].filter((symbol) => symbol !== "-").length;
  const warnings = [
    (
      "Research use only: these are sequence-model point estimates of cell-based cAMP " +
      "EC50 functional potency, not binding affinity, efficacy, safety, or activity in " +
      "animals or people."
    ),
    (
      "The separate 15-peptide evaluation was mixed: GCGR point error was lower but its " +
      "dependence-aware interval crossed zero, while pooled GLP-1R error was worse versus " +
      "the nearest-neighbour comparator."
    ),
    (
      "The model cannot represent Aib, lipidation, amidation, cyclization, stapling, or " +
      "other noncanonical chemistry. '-' means an alignment gap only."
    ),
  ];
  if (scope.tier !== "close_analogue") warnings.push(scope.summary);
  if (residueCount < 26) {
    warnings.push(
      "The input has fewer residues than any modeled core and should not be used for " +
      "candidate ranking.",
    );
  }
  return {
    input: { alignedSequence: sequence, standardResidueCount: residueCount },
    predictions: {
      gcgr: { log10Ec50Pm: gcgrLog10, ec50Pm: 10 ** gcgrLog10 },
      glp1r: { log10Ec50Pm: glp1rLog10, ec50Pm: 10 ** glp1rLog10 },
      selectivity: {
        log10Ec50Ratio: selectivityLog10,
        ec50FoldRatio: 10 ** selectivityLog10,
        interpretation: direction(selectivityLog10),
      },
    },
    applicability: scope,
    warnings,
  };
}

export async function sha256Hex(bytes) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function number(value) {
  if (value >= 10000 || value < 0.001) return value.toExponential(3);
  return value.toFixed(3).replace(/\.?0+$/, "");
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function renderResult(result, model, artifactSha256) {
  const predictions = result.predictions;
  const scope = result.applicability;
  const tier = TIER_COPY[scope.tier];
  const badge = document.getElementById("applicability-badge");
  badge.textContent = tier.label;
  badge.className = `badge ${tier.className}`;
  setText("normalized-sequence", result.input.alignedSequence);
  setText("glp1r-value", `${number(predictions.glp1r.ec50Pm)} pM`);
  setText(
    "glp1r-detail",
    `${number(predictions.glp1r.ec50Pm / 1000)} nM · ` +
      `log10(pM) ${predictions.glp1r.log10Ec50Pm.toFixed(4)}`,
  );
  setText("gcgr-value", `${number(predictions.gcgr.ec50Pm)} pM`);
  setText(
    "gcgr-detail",
    `${number(predictions.gcgr.ec50Pm / 1000)} nM · ` +
      `log10(pM) ${predictions.gcgr.log10Ec50Pm.toFixed(4)}`,
  );
  setText("balance-value", `${number(predictions.selectivity.ec50FoldRatio)}-fold`);
  setText("balance-detail", predictions.selectivity.interpretation);
  setText("applicability-name", tier.label);
  setText("nearest-identity", `${(scope.nearestAlignedIdentity * 100).toFixed(1)}%`);
  setText("nearest-reference", scope.nearestReferenceIds.join(", "));
  setText("applicability-summary", scope.summary);
  document.getElementById("ranking-block").hidden = scope.tier === "close_analogue";
  const metrics = model.benchmark_context.metrics;
  setText("gcgr-error", `${metrics.gcgr.development_oof_geometric_fold_error.toFixed(1)}×`);
  setText("glp1r-error", `${metrics.glp1r.development_oof_geometric_fold_error.toFixed(1)}×`);
  setText(
    "balance-error",
    `${metrics.selectivity.development_oof_geometric_fold_error.toFixed(1)}×`,
  );
  const list = document.getElementById("warnings");
  list.replaceChildren(...result.warnings.map((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
  setText("model-id", `${model.artifact_id} v${model.artifact_version}`);
  setText("model-sha", artifactSha256);
  document.getElementById("results").hidden = false;
}

async function loadVerifiedModel() {
  const [manifestResponse, modelResponse] = await Promise.all([
    fetch("demo_manifest.json", { cache: "no-store" }),
    fetch("assets/incretin_ridge_v1.json", { cache: "no-store" }),
  ]);
  if (!manifestResponse.ok || !modelResponse.ok) {
    throw new Error("Demo assets could not be loaded. Serve the docs directory over HTTP.");
  }
  const manifest = await manifestResponse.json();
  const bytes = await modelResponse.arrayBuffer();
  const observed = await sha256Hex(bytes);
  if (observed !== manifest.artifact_sha256) {
    throw new Error("Frozen model checksum mismatch. Do not use this copy of the demo.");
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

async function initialize() {
  const form = document.getElementById("prediction-form");
  const sequence = document.getElementById("sequence");
  const count = document.getElementById("sequence-count");
  const error = document.getElementById("input-error");
  const button = document.getElementById("predict-button");
  const state = document.getElementById("model-state");
  sequence.value = EXAMPLE_SEQUENCE;
  const updateCount = () => {
    const normalizedLength = sequence.value.replace(/\s/g, "").length;
    count.textContent = `${normalizedLength} / 30`;
    count.classList.toggle("bad", normalizedLength !== 30);
  };
  updateCount();
  sequence.addEventListener("input", updateCount);
  document.getElementById("example-button").addEventListener("click", () => {
    sequence.value = EXAMPLE_SEQUENCE;
    updateCount();
    error.hidden = true;
    sequence.focus();
  });

  let verified;
  try {
    verified = await loadVerifiedModel();
    state.textContent = "Verified model ready";
    state.className = "model-state ready";
    button.disabled = false;
  } catch (loadError) {
    state.textContent = "Model verification failed";
    state.className = "model-state failed";
    error.textContent = loadError.message;
    error.hidden = false;
    return;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const result = predictFromModel(sequence.value, verified.model);
      sequence.value = result.input.alignedSequence;
      updateCount();
      error.hidden = true;
      renderResult(result, verified.model, verified.artifactSha256);
      document.getElementById("results").scrollIntoView({ behavior: "smooth" });
    } catch (predictionError) {
      document.getElementById("results").hidden = true;
      error.textContent = predictionError.message;
      error.hidden = false;
    }
  });
}

if (typeof document !== "undefined") initialize();
