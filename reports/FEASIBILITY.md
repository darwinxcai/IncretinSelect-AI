# IncretinSelect-AI feasibility audit

**Audit date:** 2026-08-20
**Current decision:** feasible as a narrow GCGR/GLP-1R benchmark; do not expand to
a general triple-agonist predictor yet.

## Objective

Test whether reproducibly extracted features from AI-predicted peptide–receptor
complexes improve leakage-resistant prediction of cAMP EC50 at human GCGR and
GLP-1R beyond sequence-only baselines.

The useful result is an estimate of incremental predictive value. A null
result—predicted structural features add no held-out signal—would still be a valid
benchmark if the evaluation and uncertainty analysis are rigorous.

## Verified data

The authors' public `amp91/PeptideModels` repository was inspected at commit
`0a23c0bb86ed251acb671db09295aeac7c9c11cf`.

- `training_data.xlsx` is downloadable and checksum-pinned in the source manifest.
- It contains `dataset` and `alignment` sheets with 125 data rows each.
- The dataset sheet exposes peptide IDs, raw sequences and lengths, pM EC50 values,
  and log10(M) values for T1=GCGR and T2=GLP-1R.
- The workbook's pM and log columns are internally consistent within the rounding
  tolerance encoded in `configs/activity_schema.json`.
- The paper describes a single CHO-cell cAMP assay framework for both human
  receptors, which makes this cleaner than merging unrelated literature assays.
- The separate `reference_data.xlsx` workbook is available but represents an
  external literature assay context; it should be used only as a domain-shift test.

Raw activity workbooks are not copied into the repository. The fetcher retrieves
the exact upstream files and validates SHA-256 before installing them in
`data/raw/`. Derived fold assignments, out-of-fold predictions, and benchmark
metrics are released under the source dataset's attribution terms.

## Verified structural resources

The seed panel includes native GLP-1–GLP-1R (6X18), native glucagon–GCGR (6LMK),
paired Peptide-20 complexes, tirzepatide complexes, and the retatrutide trio. RCSB
entry identifiers, titles, resolutions, and primary-citation relationships were
verified through official RCSB records.

The native structures are the safest pilot. Peptide 20, tirzepatide, and retatrutide
contain chemistry such as Aib and/or lipid-linked groups that is not represented by
the natural-amino-acid sequence model used for the 125-peptide dataset. Those cases
are valuable stress tests, not clean first-pass benchmarks.

GIPR structures are explicitly labeled `context_only`: the primary activity dataset
does not contain matched GIPR labels.

## Novelty boundary

Puszkarska *et al.* already trained sequence-only multi-task models and used them to
design dual agonists. Reproducing a CNN or proposing another sequence-only triple
agonist would be repetitive. The independent contribution must instead be:

1. a leakage-resistant comparison of sequence-only versus structure-aware models;
2. explicit calibration of predicted interface geometry against experimental
   peptide–GPCR structures; and
3. a mechanistic error analysis asking when structural features help or mislead.

This boundary was rechecked against Wong *et al.* (2025), which already performs
ML-guided triple-agonist optimization, and DeorphaNN (2025 preprint; 2026 public
dataset), which already combines predicted active-state GPCR–peptide complexes
with learned embeddings. Accordingly, novelty cannot rest on generic triple-
agonist ML or on using predicted complexes alone. It must come from the same-
assay, held-cluster incremental-value test and its error analysis.

## Source-study prospective designs

The source paper's P1–P15 designs were checksum-pinned and parser-validated for a
locked retrospective external evaluation. Right-censored replicate measurements remained
censored during scoring.
There are no exact training-sequence overlaps, but the designs are close analogs:
3/15 are one mutation and 12/15 are three mutations from the nearest training
sequence. They were prospective in the source study, but their outcomes are public;
this repository evaluates them retrospectively to test local-analog transfer and
do not replace cluster-held-out evaluation. See `reports/HOLDOUT_AUDIT.md`.

## Completed CPU sequence analysis

The clustering threshold and three outer folds are frozen using sequence topology
alone. At 0.85 aligned identity, 17 connected components produce folds of
42/42/41; the maximum identity across folds is 0.8333. A tied 1-NN baseline now
provides a quantitative floor for GCGR EC50, GLP-1R EC50, and the selectivity
ratio. A component-weighted aligned-sequence ridge model now adds nested,
training-component-only model selection on those same outer folds. It lowers
pooled GCGR and GLP-1R MAE relative to 1-NN but does not improve selectivity; all
paired component-bootstrap intervals cross zero. See
`reports/SEQUENCE_SPLIT_AUDIT.md`, `reports/CPU_BASELINE.md`, and
`reports/CPU_SEQUENCE_MODEL.md`.

## Completed external evaluation

P1–P15 predictions and dependence groups were frozen without outcome inputs and
committed before a separate censor-aware scoring command read the public receptor
outcomes exactly once. The result is not an overall model win. Ridge has a
favorable GCGR constraint-MAE point difference versus tied 1-NN (-0.241), but the
four-component descriptive interval and leave-one-component-out range cross zero.
Pooled GLP-1R is unfavorable (+0.337) and reverses direction under group-macro
weighting; its four component effects span -2.120 to +1.380. Selectivity is a
secondary exploratory signal without predeclared component uncertainty. See
`reports/EXTERNAL_EVALUATION.md`.

## Minimum viable benchmark

1. **Data audit and baseline**
   - Validate the pinned workbook. **Complete.**
   - Define sequence clusters before splitting. **Complete.**
   - Run the nearest-neighbor floor. **Complete.**
   - Add one stronger, regularized sequence-only model using identical outer folds.
     **Complete.**
2. **Prediction feasibility pilot**
   - Predict the native GLP-1–GLP-1R and glucagon–GCGR complexes with at least
     three seeds per supported model.
   - Measure peptide/interface RMSD, contact recovery, insertion depth, confidence,
     and seed-to-seed stability.
   - Add the Peptide-20 GLP-1R/GCGR pair only after noncanonical-input policy is
     explicit.
3. **Small variant pilot**
   - Select 12–20 peptides spanning sequence clusters and both receptors' potency
     ranges without looking at the eventual test folds.
   - Extract a prespecified, compact structural feature set.
4. **Go/no-go**
   - Proceed to all 125 variants only if features are reproducible across seeds and
     compute cost is compatible with a November deliverable.
5. **Final comparison**
   - Fit sequence-only and sequence-plus-structure models on identical nested,
     cluster-held-out folds.
   - Report paired fold differences and uncertainty, not a single favorable split.

## Success criteria

- All public inputs pass provenance/checksum/schema validation.
- No peptide family crosses an outer train/test boundary.
- Experimental-structure metrics and feature definitions are versioned before the
  full run.
- Baselines and the hybrid model use identical splits.
- The conclusion distinguishes EC50 prediction, receptor selectivity, binding, and
  complex confidence.
- Negative results and failed model/entity cases remain in the released benchmark.

## Main risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Only 125 labeled peptides | High variance and overfitting | Small models, nested cluster-held-out CV, paired uncertainty |
| Similar analog series | Random splits inflate performance | Cluster/family split before model fitting |
| Censored assay bounds | Ordinary regression can misread censored labels | Preserve one-sided bounds; report exact-only and constraint-aware metrics |
| EC50 is not affinity | Structural-binding claims can be overstated | Frame endpoint as functional potency throughout |
| Amidation and noncanonical chemistry | Sequence/structure inputs may be incomplete | Track modifications; native anchors first; sensitivity analyses |
| Structure predictor cost | Full 125 x 2 x models x seeds may be large | 12–20 peptide pilot and one primary predictor before scaling |
| Training-data contamination | Modern predictors may have seen PDB targets | Date-aware reporting and held-out perturbation tests; no novelty claim from reconstruction alone |
| GIPR label mismatch | Triple-receptor model would mix incompatible evidence | Keep GIPR context-only in MVP |

## Compute estimate

Data validation and classical baselines are CPU-scale. Complex inference is the
unknown cost driver and has **not** been run here. The pilot must measure actual
wall time, GPU memory, failure rate, and per-seed storage before committing to the
full matrix. A single predictor with three seeds is the MVP; additional predictors
are extensions, not requirements.

## Current blockers

- No complex-prediction runtime or GPU has yet been selected or benchmarked.
- Noncanonical/lipidated peptide representation must be specified before those
  structures enter quantitative comparisons.
- The completed P1–P15 result cannot be used to choose structural features or
  tune the next model; incremental value must be assessed inside the frozen
  development folds.
