# Published P1–P15 external-evaluation audit

**Frozen:** 2026-08-20
**Decision:** validated and scored once as a locked retrospective local-analog set;
not evidence of distant sequence-family generalization. It was prospective in
the source study, but its labels are public and this project uses it retrospectively.

## Provenance

The 15 sequences and two receptor-specific potency tables were taken from the
official source data and supplementary workbooks for Puszkarska *et al.*,
*Nature Chemistry* (2024), DOI
[10.1038/s41557-024-01532-x](https://doi.org/10.1038/s41557-024-01532-x).
All four inputs, including the 125-sequence training workbook, are pinned by
SHA-256 in `data/manifests/sources.json`. The generated record is
`data/derived/prospective_holdout.json` and is deliberately gitignored.

## Parser and integrity checks

- Recovered exactly P1–P15: 15 unique, 30-position aligned sequences.
- Matched receptor identity from workbook sheets `data_GCGR` and `data_GLP-1R`.
- Recovered three EC50 replicate cells per peptide and receptor; no values were
  imputed.
- Preserved 9/45 GCGR and 12/45 GLP-1R replicates as right-censored observations.
- Computed an exact replicate mean only when all three values were observed:
  12/15 GCGR records and 11/15 GLP-1R records.
- Ignored the publisher summary columns because their Greek-symbol headers are
  transposed relative to the numerical mean and standard deviation.
- Kept the endpoint as cell-based cAMP EC50 in pM. It is functional potency, not
  binding affinity, efficacy, Kd, or delta-delta-G.

## Training-overlap audit

Against the 125 aligned training sequences:

- exact overlaps: **0/15**;
- nearest Hamming distance of one mutation: **3/15** (P1, P6, P11);
- nearest Hamming distance of three mutations: **12/15**.

This set was experimentally prospective in the source study, but it was created by
optimizing from the training set and lies close to it. It is suitable for testing
prediction on nearby designed analogs. It must not replace cluster-held-out
cross-validation for claims about new peptide families.

## Evaluation policy

The public P1–P15 labels had already been parsed for checksum, overlap, and
censoring integrity checks, so this was not a blinded holdout. They remained
excluded from model development. Predictions generated without P1–P15 outcomes,
dependency
groups, protocol, and implementation hashes were committed before a separate
scoring command read the receptor outcomes exactly once. The evaluation aggregates
replicates at peptide level, retains one-sided censoring constraints, and reports
all three intended design groups. The lock commit and complete result are recorded
in `reports/EXTERNAL_EVALUATION.md` and
`reports/external_evaluation_receipt.json`.

The result is mixed: GCGR's favorable point difference is not stable to the
four-component interval or leave-one-component-out analysis, and pooled GLP-1R is
unfavorable and weighting-sensitive. It does not support external superiority.

## Novelty boundary checked on 2026-08-20

- Puszkarska *et al.* already performed sequence-only modeling and prospective
  design on this exact system. Reproducing their CNN or optimizing more sequences
  is not an independent contribution.
- Wong *et al.* (2025), DOI
  [10.3389/fbinf.2025.1687617](https://doi.org/10.3389/fbinf.2025.1687617),
  already reported ML-guided triple-agonist sequence optimization.
- DeorphaNN (2025 preprint; 2026 public dataset), DOI
  [10.1101/2025.03.19.644234](https://doi.org/10.1101/2025.03.19.644234),
  already integrates predicted active-state GPCR–peptide complexes and learned
  representations for peptide-agonist prioritization, albeit in a different
  receptor/organism setting.

The defensible contribution remains narrower: determine whether a small,
predeclared set of complex-derived features adds reproducible held-cluster signal
over sequence baselines for same-assay human GCGR/GLP-1R functional potency.

## Next bounded task

The CPU sequence benchmark and locked retrospective external evaluation are complete. No GPU
inference has run. The next bounded task is the prespecified complex-prediction
pilot: native GLP-1–GLP-1R and glucagon–GCGR anchors, at least three seeds, and
predeclared geometry/stability measures before any structure-derived feature is
added to the development benchmark. P1–P15 outcomes will not be reused to choose
that model.
