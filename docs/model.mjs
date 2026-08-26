export const EXAMPLE_SEQUENCE = "HSQGTFTSDYSKYLDSRAASEFVQWLISH-";

export const TIER_COPY = {
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
    throw new Error(
      "FASTA headers cannot be pasted into the sequence field. Use the FASTA import control.",
    );
  }
  const sequence = value.replace(/\s/g, "").toUpperCase();
  if (!sequence) throw new Error("Sequence input is empty.");
  const length = model.input_contract.aligned_length;
  if (sequence.length !== length) {
    throw new Error(
      `This model requires exactly ${length} aligned characters; received ` +
      `${sequence.length}. The software will not guess an alignment or trim residues.`,
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

export function formatNumber(value) {
  if (value >= 10000 || value < 0.001) return value.toExponential(3);
  return value.toFixed(3).replace(/\.?0+$/, "");
}
