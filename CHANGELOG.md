# Changelog

All notable changes to this research artifact are documented here.

## [Unreleased]

- Complex-prediction pilot and structure-feature benchmark remain future work.

## [0.5.0] - 2026-08-26

### Added

- Added a guarded `incretin-screen` CSV workflow with explicit GLP-1R, GCGR, or
  dual objectives; applicability and residue-count rank gates; visible row-level
  errors and exclusions; dense ties; overwrite protection; per-file atomic
  replacement; and a checksum-bound machine-readable receipt.
- Added a deterministic, label-free four-row screening example and installed-wheel
  verification of the batch command. The example deliberately excludes P1–P15
  sequences and outcomes and demonstrates software behavior, not model accuracy.
- Added an offline distribution verifier that builds the wheel, checks required
  runtime files, installs it outside the source tree, and exercises the public
  JSON, CSV, and local-browser entry points.
- Added the distribution verifier to CI and retained its machine-readable receipt.
- Added a fail-safe GitHub publication bootstrap with dry-run default, explicit
  public target, clean-tree and branch checks, release re-verification, authenticated
  creation/push, and post-creation URL and visibility verification.
- Added a machine-readable release-readiness audit that independently gates local
  package evidence and public CV-verification evidence.
- Added a zero-install static browser demo with checksum verification, no external
  runtime service, browser/Python numerical parity tests, and a guarded GitHub
  Pages deployment workflow.

### Scientific boundary

- Batch ranks are exploratory model orderings for review, not experimental
  recommendations. Only close analogues with at least 26 standard residues are
  ranked; every other row stays visible with a reason.
- The batch example contains no assay outcomes or P1–P15 sequences. Its exact
  development references prove software behavior rather than predictive accuracy.

## [0.4.0] - 2026-08-20

### Added

- An installable `incretin-predict` CLI with readable, JSON, and CSV output.
- A dependency-free `incretin-web` local browser interface bound to loopback.
- A frozen, versioned ridge artifact that runs without raw source workbooks and
  reproduces all 15 predictions committed before external scoring.
- Label-free nearest-reference identity, applicability warnings, model checksum,
  benchmark error context, product guide, and offline smoke test.

### Scientific boundary

- Product input is exactly one curated 30-column alignment over standard amino
  acids plus `-`; arbitrary raw sequences are not silently aligned or truncated.
- Outputs remain cell-based cAMP EC50 functional-potency estimates—not affinity,
  efficacy, safety, candidate validation, or clinical predictions.
- The mixed external result is displayed in every prediction, and development
  MAE is presented as population-level context rather than a per-query interval.

## [0.3.0] - 2026-08-20

### Added

- Component-weighted aligned-sequence ridge regression with nested leave-one-
  component-out hyperparameter selection on the frozen outer folds.
- Exact pooled and component-macro metrics, per-fold results, matched 1-NN
  comparisons, and paired whole-component bootstrap intervals.
- Deterministic publication PNG/SVG with OOF observed-versus-predicted panels,
  paired MAE intervals, and a complete plotting-source CSV.
- Versioned CPU model contract, synthetic leakage tests, and reproducible sequence-
  model report and out-of-fold prediction artifacts.
- A checked-in, 10/10-resolved RCSB structure seed manifest after correcting
  deposited entity aliases for 6X18, 7FIY, and 8YW4.
- A label-independent, all-development final-model fit and committed P1–P15
  prediction lock with protocol, implementation, input, and dependency hashes.
- A one-shot, censor-aware external evaluation that aggregates triplicates at the
  peptide level, preserves one-sided bounds, and retains all four predeclared
  models (ridge plus three comparators) and all endpoints.
- Label-free dependence groupings, four-component descriptive resampling,
  leave-one-component-out checks, and sensitivity summaries that do not treat 45
  replicate cells or 15 related designs as independent evidence.
- A 45-row endpoint-level audit table, machine-readable metrics and scoring
  receipt, and deterministic PNG/SVG external-evaluation figure with source CSV.

### Scientific boundary

- The sequence-model command accepts only the training workbook, frozen fold
  table, and predeclared model config; it does not read P1–P15 data. A separate
  integrity command parses the public P1–P15 labels only to audit checksums,
  overlap, and censoring.
- Selectivity remains the difference of receptor predictions, and the unfavorable
  selectivity comparison is retained alongside receptor-potency improvements.
- The external result is explicitly retained as mixed rather than a model win:
  GCGR has a favorable but sign-unstable point difference, while pooled GLP-1R is
  unfavorable and dependence-weighting sensitive. Selectivity remains exploratory.
- A historical parser read public P1–P15 outcomes for integrity and censoring
  audits; only the separate post-lock scorer used them for prediction-error
  metrics. This is command-local isolation for a retrospective, unblinded local-
  analogue evaluation—not a virgin-label or newly prospective experiment.

## [0.2.0] - 2026-08-20

### Added

- Checksum-verified P1–P15 prospective holdout parser with censor preservation.
- Training-only identity-threshold audit and deterministic 42/42/41 outer folds.
- Tied 1-nearest-neighbour and training-fold median CPU baselines.
- Machine-readable out-of-fold predictions, metric tables, and JSON reports.
- Release documentation, citation metadata, data-license attribution, and CI.

### Scientific boundary

- P1–P15 labels remain excluded from threshold, fold, feature, and baseline
  decisions.
- EC50 is reported as functional potency and never relabeled as binding affinity.

## [0.1.0] - 2026-08-19

- Initial provenance, validation, structure-manifest, and feasibility scaffold.
