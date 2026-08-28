export const EXAMPLE_SEQUENCE = "HSQGTFTSDYSKYLDSRAASEFVQWLISH";
export const SOFTWARE_VERSION = "0.9.0";
export const EXPECTED_MODEL_SHA256 = (
  "eb7e99bbc3d83fdfb11ded4ba215fd7f6107a6e7d254f68e1b9610da6eb7e321"
);
export const EXPECTED_ALIGNMENT_ADAPTER_SHA256 = (
  "a606f0edda342471dc5e42d667d05506ac604c53cd221ecd8e1821edff6fd5fe"
);

export const TIER_COPY = {
  close_analogue: {
    label: "Local analog",
    className: "close",
  },
  distant_analogue: {
    label: "Outside ranking scope",
    className: "distant",
  },
  outside_reference_neighborhood: {
    label: "Far outside ranking scope",
    className: "outside",
  },
};

export const EVIDENCE_COPY = {
  training_reference_match: { label: "Training-set match · in-sample", className: "close" },
  local_analogue_mixed_evidence: {
    label: "Within local-analog scope · exploratory use",
    className: "close",
  },
  outside_ranking_scope: { label: "Outside supported comparison scope", className: "distant" },
  far_outside_ranking_scope: {
    label: "Distant extrapolation · do not rank",
    className: "outside",
  },
};

export function validateAlignmentAdapter(adapter) {
  const acceptance = adapter?.acceptance_policy;
  const alignment = adapter?.alignment_policy;
  if (
    adapter?.schema_version !== 1 ||
    adapter?.adapter_id !== "raw_alignment_adapter_v1" ||
    adapter?.adapter_version !== "1.0.0" ||
    adapter?.canonical_alphabet !== "ACDEFGHIKLMNPQRSTVWY" ||
    adapter?.labels_accessed !== false ||
    adapter?.model_coefficients_changed !== false ||
    acceptance?.minimum_raw_residues !== AUTOALIGN_MIN_RESIDUES ||
    acceptance?.maximum_raw_residues !== AUTOALIGN_MAX_RESIDUES ||
    acceptance?.minimum_nearest_aligned_identity !== 0.85 ||
    acceptance?.ambiguous_projection !== "reject" ||
    acceptance?.terminal_trimming !== false ||
    alignment?.model_columns !== 30
  ) {
    throw new Error("Raw-alignment adapter contract is invalid.");
  }
  return adapter;
}

export function validateModelArtifact(model) {
  const alphabet = model?.input_contract?.alphabet;
  const alignedLength = model?.input_contract?.aligned_length;
  const featureCount = alignedLength * String(alphabet ?? "").length;
  const finiteVector = (value, length) => (
    Array.isArray(value) && value.length === length && value.every(Number.isFinite)
  );
  const validCoefficients = (
    Array.isArray(model?.model?.coefficients) &&
    model.model.coefficients.length === featureCount &&
    model.model.coefficients.every((row) => finiteVector(row, 2))
  );
  const references = model?.applicability_reference?.sequences;
  const uniqueReferenceIds = new Set(
    Array.isArray(references) ? references.map((row) => row?.peptide_id) : [],
  );
  const allowed = new Set(String(alphabet ?? ""));
  const validReferences = (
    Array.isArray(references) &&
    references.length === 125 &&
    uniqueReferenceIds.size === 125 &&
    references.every((row) => (
      typeof row?.peptide_id === "string" && row.peptide_id.length > 0 &&
      typeof row?.component_id === "string" && row.component_id.length > 0 &&
      typeof row?.aligned_sequence === "string" &&
      row.aligned_sequence.length === alignedLength &&
      [...row.aligned_sequence].every((symbol) => allowed.has(symbol))
    ))
  );
  const benchmarkMetrics = model?.benchmark_context?.metrics;
  const validBenchmark = ["gcgr", "glp1r", "selectivity"].every((endpoint) => (
    Number.isFinite(benchmarkMetrics?.[endpoint]?.development_oof_mae_log10) &&
    Number.isFinite(benchmarkMetrics?.[endpoint]?.development_oof_geometric_fold_error)
  ));
  if (
    model?.schema_version !== 1 ||
    model?.artifact_id !== "incretinselect_aligned_ridge_v1" ||
    alphabet !== "-ACDEFGHIKLMNPQRSTVWY" ||
    alignedLength !== 30 ||
    model?.applicability_reference?.labels_included !== false ||
    !finiteVector(model?.model?.feature_mean, featureCount) ||
    !finiteVector(model?.model?.target_mean, 2) ||
    !Number.isFinite(model?.model?.selected_alpha) ||
    model.model.selected_alpha <= 0 ||
    !validCoefficients ||
    !validReferences ||
    !validBenchmark
  ) {
    throw new Error("Frozen model contract is invalid.");
  }
  return model;
}

export const AUTOALIGN_MIN_RESIDUES = 26;
export const AUTOALIGN_MAX_RESIDUES = 30;

function normalizeSequenceText(value, model) {
  if (typeof value !== "string") throw new Error("Sequence input must be text.");
  if (value.includes(">")) {
    throw new Error(
      "FASTA headers cannot be pasted into the sequence field. Use the FASTA import control.",
    );
  }
  const compacted = value.replace(/\s/g, "");
  const nonAscii = [...new Set([...compacted].filter(
    (symbol) => !/^[\x00-\x7F]$/.test(symbol),
  ))].sort();
  if (nonAscii.length) {
    throw new Error(
      `Sequence input must use ASCII amino-acid letters; unsupported symbols: ` +
      nonAscii.join(""),
    );
  }
  const sequence = compacted.toUpperCase();
  if (!sequence) throw new Error("Sequence input is empty.");
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

function retainTwo(values) {
  return [...new Set(values)].sort().slice(0, 2);
}

function alignRawToReference(rawSequence, reference) {
  const queryLength = rawSequence.length;
  const columnCount = reference.length;
  const unreachable = -1e9;
  const scores = Array.from(
    { length: queryLength + 1 },
    () => Array(columnCount + 1).fill(unreachable),
  );
  const paths = Array.from(
    { length: queryLength + 1 },
    () => Array.from({ length: columnCount + 1 }, () => []),
  );
  scores[0][0] = 0;
  paths[0][0] = [""];

  const update = (queryIndex, columnIndex, score, candidates) => {
    if (score > scores[queryIndex][columnIndex]) {
      scores[queryIndex][columnIndex] = score;
      paths[queryIndex][columnIndex] = retainTwo(candidates);
    } else if (score === scores[queryIndex][columnIndex]) {
      paths[queryIndex][columnIndex] = retainTwo([
        ...paths[queryIndex][columnIndex],
        ...candidates,
      ]);
    }
  };

  for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
    const referenceSymbol = reference[columnIndex];
    for (let queryIndex = 0; queryIndex <= queryLength; queryIndex += 1) {
      const currentPaths = paths[queryIndex][columnIndex];
      if (!currentPaths.length) continue;
      update(
        queryIndex,
        columnIndex + 1,
        scores[queryIndex][columnIndex] + (referenceSymbol === "-" ? 0 : -1),
        currentPaths.map((path) => `${path}-`),
      );
      if (queryIndex === queryLength) continue;
      const querySymbol = rawSequence[queryIndex];
      const residueScore = referenceSymbol === querySymbol ? 0 : -1;
      update(
        queryIndex + 1,
        columnIndex + 1,
        scores[queryIndex][columnIndex] + residueScore,
        currentPaths.map((path) => `${path}${querySymbol}`),
      );
    }
  }
  return {
    score: scores[queryLength][columnCount],
    alignments: paths[queryLength][columnCount],
  };
}

/** Map a supported raw peptide into the frozen 30-column coordinate system. */
function prepareSequence(value, model) {
  const sequence = normalizeSequenceText(value, model);
  const alignedLength = model.input_contract.aligned_length;
  if (sequence.includes("-")) {
    if (sequence.length !== alignedLength) {
      throw new Error(
        `A sequence containing alignment gaps must provide all ${alignedLength} model ` +
        `columns; received ${sequence.length}.`,
      );
    }
    return {
      originalSequence: sequence,
      alignedSequence: sequence,
      inputResidueCount: [...sequence].filter((symbol) => symbol !== "-").length,
      alignmentMethod: "provided_30_column_alignment",
      alignmentStatus: "provided",
      alignmentReferenceIds: [],
      alignmentScore: null,
      alignmentNote: (
        "The user supplied all 30 model columns, including explicit alignment gaps."
      ),
      alignmentAdapterId: null,
      alignmentAdapterVersion: null,
      alignmentAdapterSha256: null,
    };
  }

  const adapter = validateAlignmentAdapter(model.raw_alignment_adapter);
  const adapterSha256 = model.raw_alignment_adapter_sha256;
  if (adapterSha256 !== EXPECTED_ALIGNMENT_ADAPTER_SHA256) {
    throw new Error("Raw-alignment adapter checksum is invalid.");
  }

  const residueCount = sequence.length;
  if (residueCount > AUTOALIGN_MAX_RESIDUES) {
    throw new Error(
      `The frozen model has ${alignedLength} alignment columns, but the raw sequence ` +
      `contains ${residueCount} residues. Terminal extensions or insertions are not ` +
      "truncated automatically.",
    );
  }
  if (residueCount < AUTOALIGN_MIN_RESIDUES) {
    throw new Error(
      `Automatic alignment supports ${AUTOALIGN_MIN_RESIDUES}–${AUTOALIGN_MAX_RESIDUES} ` +
      `standard residues, matching the development sequence range; received ` +
      `${residueCount}. A shorter peptide requires a scientifically reviewed ` +
      `${alignedLength}-column alignment.`,
    );
  }
  if (residueCount === alignedLength) {
    const nearestIdentity = Math.max(...model.applicability_reference.sequences.map(
      (reference) => alignedIdentity(sequence, reference.aligned_sequence),
    ));
    if (nearestIdentity < 0.85) {
      throw new Error(
        "Raw-sequence mode is limited to local analogs: the sequence is only " +
        `${(nearestIdentity * 100).toFixed(1)}% identical to the reference panel, ` +
        "below the preset 85% gate. Expert users may instead provide an explicit " +
        "30-column alignment for transparent out-of-scope inspection.",
      );
    }
    return {
      originalSequence: sequence,
      alignedSequence: sequence,
      inputResidueCount: residueCount,
      alignmentMethod: "direct_30_column_sequence",
      alignmentStatus: "not_required",
      alignmentReferenceIds: [],
      alignmentScore: null,
      alignmentNote: "The 30-residue input directly fills the 30 model columns.",
      alignmentAdapterId: adapter.adapter_id,
      alignmentAdapterVersion: adapter.adapter_version,
      alignmentAdapterSha256: adapterSha256,
    };
  }

  let bestScore = null;
  let bestAlignments = [];
  let bestReferenceIds = [];
  for (const reference of model.applicability_reference.sequences) {
    const candidate = alignRawToReference(sequence, reference.aligned_sequence);
    if (bestScore === null || candidate.score > bestScore) {
      bestScore = candidate.score;
      bestAlignments = [...candidate.alignments];
      bestReferenceIds = [reference.peptide_id];
    } else if (candidate.score === bestScore) {
      bestAlignments = retainTwo([...bestAlignments, ...candidate.alignments]);
      bestReferenceIds.push(reference.peptide_id);
    }
  }
  bestAlignments = retainTwo(bestAlignments);
  if (bestAlignments.length !== 1) {
    throw new Error(
      "Automatic alignment is ambiguous: equally scoring reference mappings place " +
      "residues in different model columns. Supply a reviewed 30-column alignment " +
      "with explicit '-' gaps.",
    );
  }
  const alignedSequence = bestAlignments[0];
  const nearestIdentity = Math.max(...model.applicability_reference.sequences.map(
    (reference) => alignedIdentity(alignedSequence, reference.aligned_sequence),
  ));
  if (nearestIdentity < 0.85) {
    throw new Error(
      "Automatic alignment is limited to local analogs: the best projected alignment " +
      `is only ${(nearestIdentity * 100).toFixed(1)}% identical to the reference panel, ` +
      "below the preset 85% gate. Supply a reviewed 30-column alignment only if an " +
      "expert mapping is available.",
    );
  }
  return {
    originalSequence: sequence,
    alignedSequence,
    inputResidueCount: residueCount,
    alignmentMethod: "reference_panel_auto_alignment",
    alignmentStatus: "mapped_unambiguously",
    alignmentReferenceIds: [...new Set(bestReferenceIds)].sort(),
    alignmentScore: bestScore,
    alignmentNote: (
      `The ${residueCount}-residue input was mapped without truncation to the frozen ` +
      "30-column coordinate system. The alignment score is an input-mapping heuristic, " +
      "not prediction confidence."
    ),
    alignmentAdapterId: adapter.adapter_id,
    alignmentAdapterVersion: adapter.adapter_version,
    alignmentAdapterSha256: adapterSha256,
  };
}

export function normalizeSequence(value, model) {
  const sequence = normalizeSequenceText(value, model);
  const length = model.input_contract.aligned_length;
  if (sequence.length !== length) {
    throw new Error(
      `The strict model requires exactly ${length} aligned characters; received ` +
      `${sequence.length}. Use the raw-sequence adapter for 26–30 canonical residues.`,
    );
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
  if (foldRatio >= 3) return "Lower predicted EC50 at GLP-1R";
  if (foldRatio <= 1 / 3) return "Lower predicted EC50 at GCGR";
  return "Predicted EC50 values within 3-fold";
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
  const exactReferenceMatch = maximum >= 1 - 1e-12;
  let tier = "outside_reference_neighborhood";
  let evidenceState = "far_outside_ranking_scope";
  let summary = (
    "The input is far from every reference peptide. Its numeric estimates are " +
    "extrapolations and should not be used to rank experiments."
  );
  if (exactReferenceMatch) {
    tier = "close_analogue";
    evidenceState = "training_reference_match";
    summary = (
      "The input matches a training reference exactly. This is an in-sample model " +
      "estimate and does not demonstrate predictive accuracy on a new peptide."
    );
  } else if (maximum >= 0.85) {
    tier = "close_analogue";
    evidenceState = "local_analogue_mixed_evidence";
    summary = (
      "The input meets the 0.85 local-analog software gate. This threshold defined " +
      "benchmark sequence components; it was not calibrated to prediction error. " +
      "Transfer among 15 published local analogs was mixed."
    );
  } else if (maximum >= 0.70) {
    tier = "distant_analogue";
    evidenceState = "outside_ranking_scope";
    summary = (
      "The input falls below the 0.85 identity gate. Its numeric estimates are shown " +
      "for inspection but are outside the supported ranking scope."
    );
  }
  return {
    tier,
    evidenceState,
    exactReferenceMatch,
    nearestAlignedIdentity: maximum,
    nearestReferenceIds: nearest.map((row) => row.peptideId),
    nearestComponentIds: [...new Set(nearest.map((row) => row.componentId))].sort(),
    thresholdNote: (
      "The 0.85 threshold defines sequence-identity components in the benchmark; " +
      "0.70 is an interface heuristic. Neither is calibrated to prediction error."
    ),
    summary,
  };
}

function predictLog10Values(sequence, model) {
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
  return values;
}

function nearestReferenceComparison(sequence, values, scope, model) {
  const referenceId = scope.nearestReferenceIds[0];
  const reference = model.applicability_reference.sequences.find(
    (row) => row.peptide_id === referenceId,
  );
  if (!reference) throw new Error("Nearest reference is missing from the model artifact.");
  const referenceSequence = reference.aligned_sequence;
  const referenceValues = predictLog10Values(referenceSequence, model);
  const alphabet = model.input_contract.alphabet;
  const coefficients = model.model.coefficients;
  const width = alphabet.length;
  const changes = [];
  const contributionSum = [0, 0];
  for (let index = 0; index < sequence.length; index += 1) {
    const referenceSymbol = referenceSequence[index];
    const querySymbol = sequence[index];
    if (referenceSymbol === querySymbol) continue;
    const queryIndex = index * width + alphabet.indexOf(querySymbol);
    const referenceIndex = index * width + alphabet.indexOf(referenceSymbol);
    const gcgrDelta = coefficients[queryIndex][0] - coefficients[referenceIndex][0];
    const glp1rDelta = coefficients[queryIndex][1] - coefficients[referenceIndex][1];
    contributionSum[0] += gcgrDelta;
    contributionSum[1] += glp1rDelta;
    changes.push({
      alignmentPosition: index + 1,
      referenceSymbol,
      querySymbol,
      gcgrDeltaLog10Ec50Pm: gcgrDelta,
      glp1rDeltaLog10Ec50Pm: glp1rDelta,
      selectivityDeltaLog10Ratio: gcgrDelta - glp1rDelta,
    });
  }
  const gcgrDelta = values[0] - referenceValues[0];
  const glp1rDelta = values[1] - referenceValues[1];
  const residuals = [
    gcgrDelta - contributionSum[0],
    glp1rDelta - contributionSum[1],
  ];
  return {
    referenceId,
    referenceComponentId: reference.component_id,
    referenceAlignedSequence: referenceSequence,
    nearestReferenceTieCount: scope.nearestReferenceIds.length,
    changedPositionCount: changes.length,
    referencePrediction: {
      gcgrLog10Ec50Pm: referenceValues[0],
      glp1rLog10Ec50Pm: referenceValues[1],
    },
    queryMinusReference: {
      gcgrDeltaLog10Ec50Pm: gcgrDelta,
      glp1rDeltaLog10Ec50Pm: glp1rDelta,
      selectivityDeltaLog10Ratio: gcgrDelta - glp1rDelta,
      gcgrEc50FoldRatio: 10 ** gcgrDelta,
      glp1rEc50FoldRatio: 10 ** glp1rDelta,
    },
    positionContributions: changes,
    decompositionMaxAbsResidualLog10: Math.max(...residuals.map(Math.abs)),
    interpretation: (
      "Positive deltas mean the query has a higher predicted EC50 than the reference; " +
      "negative deltas mean a lower predicted EC50."
    ),
    scientificBoundary: (
      "This is an exact decomposition of the fitted linear model, not a causal " +
      "substitution effect or experimental validation."
    ),
  };
}

function predictPrepared(prepared, model) {
  const sequence = prepared.alignedSequence;
  const values = predictLog10Values(sequence, model);
  const [gcgrLog10, glp1rLog10] = values;
  const selectivityLog10 = gcgrLog10 - glp1rLog10;
  const scope = applicability(sequence, model);
  const comparison = nearestReferenceComparison(sequence, values, scope, model);
  const residueCount = [...sequence].filter((symbol) => symbol !== "-").length;
  const rankingExclusions = [];
  if (scope.tier !== "close_analogue") rankingExclusions.push(scope.summary);
  if (residueCount < 26) {
    rankingExclusions.push(
      `The input contains ${residueCount} standard residues; exploratory ranking ` +
      "requires at least 26.",
    );
  }
  const exploratoryRanking = {
    enabled: rankingExclusions.length === 0,
    identityGate: 0.85,
    minimumStandardResidueCount: 26,
    exclusionReasons: rankingExclusions,
    boundary: (
      "Passing these software gates does not establish prediction accuracy or " +
      "experimental priority."
    ),
  };
  const warnings = [
    (
      "Estimates apply to the source study's cell-based cAMP assay and do not measure " +
      "binding affinity, maximal assay response, safety, or in vivo activity."
    ),
    (
      "The locked retrospective P1–P15 external evaluation was mixed: ridge had lower " +
      "GCGR point error, but its dependence-aware interval crossed zero, and higher " +
      "pooled GLP-1R error than 1-NN."
    ),
    (
      "The model cannot represent Aib, lipidation, amidation, cyclization, stapling, or " +
      "other noncanonical chemistry. '-' means an alignment gap only."
    ),
  ];
  warnings.push(...rankingExclusions);
  if (scope.exactReferenceMatch) warnings.push(scope.summary);
  return {
    input: {
      originalSequence: prepared.originalSequence,
      alignedSequence: sequence,
      standardResidueCount: residueCount,
      inputResidueCount: prepared.inputResidueCount,
      alignmentMethod: prepared.alignmentMethod,
      alignmentStatus: prepared.alignmentStatus,
      alignmentReferenceIds: prepared.alignmentReferenceIds,
      alignmentScore: prepared.alignmentScore,
      alignmentNote: prepared.alignmentNote,
      alignmentAdapterId: prepared.alignmentAdapterId,
      alignmentAdapterVersion: prepared.alignmentAdapterVersion,
      alignmentAdapterSha256: prepared.alignmentAdapterSha256,
    },
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
    exploratoryRanking,
    nearestReferenceComparison: comparison,
    warnings,
  };
}

export function predictFromModel(value, model) {
  const sequence = normalizeSequence(value, model);
  return predictPrepared({
    originalSequence: sequence,
    alignedSequence: sequence,
    inputResidueCount: [...sequence].filter((symbol) => symbol !== "-").length,
    alignmentMethod: "provided_30_column_alignment",
    alignmentStatus: "provided",
    alignmentReferenceIds: [],
    alignmentScore: null,
    alignmentNote: (
      "The user supplied all 30 model columns, including any explicit alignment gaps."
    ),
    alignmentAdapterId: null,
    alignmentAdapterVersion: null,
    alignmentAdapterSha256: null,
  }, model);
}

export function prepareRawSequence(value, model) {
  const sequence = normalizeSequenceText(value, model);
  if (sequence.includes("-")) {
    throw new Error(
      "Raw-sequence mode does not accept '-' gaps. Select expert 30-column mode " +
      "only when you have a reviewed alignment.",
    );
  }
  return prepareSequence(sequence, model);
}

export function predictRawFromModel(value, model) {
  return predictPrepared(prepareRawSequence(value, model), model);
}

export async function sha256Hex(bytes) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

export function formatNumber(value) {
  if (value >= 10000 || value < 0.001) return value.toExponential(3);
  return value.toFixed(3).replace(/\.?0+$/, "");
}
