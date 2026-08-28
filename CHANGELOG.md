# Changelog

All notable changes to this research artifact are documented here.

## [Unreleased]

- Complex-prediction pilot and structure-feature benchmark remain future work.

## [0.9.1] - 2026-08-28

### Improved

- Public-release verification now requires successful Python 3.10, 3.11, and 3.12
  jobs plus the exact version tag, release workflow, wheel, source archive, and
  checksum manifest.
- The release workflow publishes the same deterministic wheel and source archive
  exercised by distribution verification, and fails if verification changes any
  tracked source receipt.
- Distribution receipts record the supported Python minor line rather than an
  environment-specific patch number, keeping clean-runner verification stable.

### Scientific boundaries

- This patch changes release assurance only. The frozen model, adapter, benchmark,
  P1–P15 evaluation, and 26–30-residue local-analog scope are unchanged.

## [0.9.0] - 2026-08-28

### Added

- Added real-Chromium acceptance tests for single-sequence prediction, batch
  screening, and checksum-bound downloads.
- Added automated WCAG 2.1 A/AA accessibility scans for the initial, single-result,
  and batch-result interfaces.
- Added a tag-producing release workflow that publishes a GitHub Release with the
  wheel, source distribution, and SHA-256 checksum manifest only after exact-commit
  CI succeeds.
- Added branch-coverage reporting, a security disclosure policy, and monthly
  dependency maintenance for Python, npm, and GitHub Actions.

### Improved

- Added Python 3.11 to the supported-version CI matrix.
- Added an in-browser batch example and a short first-use path for readers who want
  to evaluate the product before reading the complete methods.
- Reorganized dense input guidance behind progressive disclosure and clarified the
  automatic-alignment, noncanonical-chemistry, minimax-ranking, and benchmark-error
  boundaries.
- Replaced receptor-"favored" output labels with neutral descriptions of which
  predicted EC50 is lower; the numerical model and threefold descriptive boundary
  are unchanged.

### Scientific boundaries

- Browser and release engineering changes do not refit the model, change its
  coefficients, access P1–P15 outcomes, or broaden the 26–30-residue local-analog
  scope.
- Passing accessibility, software, distribution, or applicability gates does not
  establish experimental accuracy, binding affinity, safety, or therapeutic value.

## [0.8.0] - 2026-08-28

### Added

- Added a separately frozen, checksum-bound adapter for canonical 26–30-residue
  raw sequences. It uses only the label-free 125-sequence reference panel, retains
  every residue, requires at least 85% nearest aligned identity, and rejects
  distinct tied projections rather than guessing an alignment.
- Added preferred `candidate_id,sequence` batch input while retaining the reviewed
  `candidate_id,aligned_sequence` expert path.
- Added adapter provenance to JSON/CSV results and receipts, 125-reference
  round-trip tests, ambiguity/no-truncation regression tests, and Python/browser
  acceptance parity.
- Batch receipts now bind the adapter ID, version, checksum, and frozen policy even
  when every row is invalid; displayed and recorded row limits are mode-specific.

### Improved

- Reorganized browser, terminal, and Markdown results around four separate
  questions: predicted functional potency, receptor profile, model applicability,
  and validation evidence.
- Added directional closest-sequence comparisons and human-readable batch states;
  raw internal labels remain available in machine-readable downloads.
- The bundled browser and command-line examples now demonstrate raw 29-residue
  input and show the 30-column representation used by the unchanged model.
- Sequence validation now rejects non-ASCII glyphs before case normalization, and
  batch caches retain pre-validation characters so Unicode case expansion cannot
  alias a canonical peptide.
- Browser length feedback follows the explicitly selected raw or expert contract,
  and batch screening paints a progress state before local alignment begins.

### Scientific boundaries

- The adapter is input preprocessing, not a new fitted model. It does not access
  activity labels or alter the frozen ridge coefficients, benchmark, or P1–P15
  evaluation.
- Inputs longer than 30 residues, shorter than 26 residues, ambiguous mappings,
  and unsupported chemistry are rejected. A reviewed 30-column expert input does
  not make an out-of-scope prediction suitable for ranking.
- Outputs remain estimates of cell-based cAMP EC50—not binding affinity, maximal
  response, safety, in vivo efficacy, or an overall peptide-quality score.

## [0.7.0] - 2026-08-27

### Added

- Exact nearest-reference attribution for the additive ridge model, including
  position-level contributions and an explicit noncausal interpretation boundary.
- Markdown reports for single predictions and a file/stdin input path for the
  command-line interface.
- Batch score distance from the first result, fold ratio, and development-MAE
  context. These population-level summaries are not individual confidence
  intervals or significance tests.
- Cross-runtime contract tests spanning 601 single-position variants, tied nearest
  references, applicability evidence states, and canonical CSV safety fields.

### Improved

- The installed `incretin-web` command now serves the same verified application as
  GitHub Pages, including FASTA import, CSV screening, attribution, and downloads.
- Browser and Python CSV parsing, field order, warnings, version metadata, and
  spreadsheet-safe exports now follow one tested contract. Browser receipts hash
  the original uploaded bytes and reject malformed UTF-8.
- Input changes invalidate prior results and downloads. File-loading and screening
  revisions prevent an older asynchronous task from replacing newer input state.
- Model loading validates the full artifact structure against an immutable expected
  checksum and returns concise product errors for malformed custom artifacts.
- Sequence-file reads are byte-bounded, reject nonregular files, and cannot overwrite
  their own input. Paired batch writes preserve the original backup even if rollback
  itself fails. Release evidence is bound to a deterministic source-payload hash.
- Pages deployment follows successful CI for the exact commit, and workflow
  dependencies are pinned to immutable commit SHAs. Pages write permissions are
  available only to the deployment job.
- Public documentation and interface copy were shortened and standardized for
  scientific clarity.
- Installed provenance and validation commands now use packaged resources instead
  of repository-relative defaults. The wheel includes citation and data-license
  notices, and the source distribution contains the complete reproducibility tree.

### Scientific boundaries

- The 0.85 identity rule is described as a software gate inherited from benchmark
  grouping, not as calibrated evidence of prediction accuracy.
- Structure upload remains unavailable because this release has no validated
  structure-derived inputs.
- Outputs remain point estimates of cell-based cAMP EC50, not binding affinity,
  maximal assay response, safety, in vivo activity, or experimental validation.

## [0.6.0] - 2026-08-27

### Added

- Added local single-record FASTA/TXT import to the browser application, with
  strict 30-position alignment validation and no server-side sequence transfer.
- Added bounded CSV screening in the browser with explicit GLP-1R, GCGR, or dual
  objectives, conservative applicability gates, row-level error retention, and
  Python-policy parity tests.
- Added downloadable single-result JSON/CSV and batch CSV/audit JSON. Downloads
  bind results to the frozen model checksum and protect spreadsheet users from
  formula-like sequence text.

### Improved

- Reworked the public application copy and result hierarchy around its practical
  purpose, required interpretation, privacy boundary, and validation limits.
- Fixed the short local-analog edge case so sequences with fewer than 26
  standard residues are visibly blocked from candidate ranking.
- Added guarded, atomic output handling for single and batch command-line files,
  including rollback if a paired batch-artifact commit fails.
- Added concise occupied-port handling and visible out-of-scope styling to the
  dependency-free local web interface.

### Scientific boundary

- Structure upload remains intentionally unavailable because the released model
  has no validated structure-derived features. PDB/mmCIF input would not add a
  scientifically supported inference in this version.
- All outputs remain estimates of cell-based cAMP EC50 functional potency—not
  affinity, efficacy, safety, clinical benefit, or an experimental recommendation.

## [0.5.0] - 2026-08-26

### Added

- Added a guarded `incretin-screen` CSV workflow with explicit GLP-1R, GCGR, or
  dual objectives; applicability and residue-count rank gates; visible row-level
  errors and exclusions; dense ties; overwrite protection; per-file atomic
  replacement; and a checksum-bound machine-readable receipt.
- Added a deterministic four-row screening example without assay outcomes and installed-wheel
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
  package evidence and public-release verification evidence.
- Added a zero-install static browser demo with checksum verification, no external
  runtime service, browser/Python numerical parity tests, and a guarded GitHub
  Pages deployment workflow.

### Scientific boundary

- Batch ranks are exploratory model orderings for review, not experimental
  recommendations. Only local analogs with at least 26 standard residues are
  ranked; every other row stays visible with a reason.
- The batch example contains no assay outcomes or P1–P15 sequences. Its exact
  development references exercise software behavior rather than predictive accuracy.

## [0.4.0] - 2026-08-20

### Added

- An installable `incretin-predict` CLI with readable, JSON, and CSV output.
- A dependency-free `incretin-web` local browser interface bound to loopback.
- A frozen, versioned ridge artifact that runs without raw source workbooks and
  reproduces all 15 predictions committed before external scoring.
- Nearest-reference identity from references stored without activity outcomes,
  applicability warnings, model checksum,
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
- An all-development final-model fit completed without P1–P15 outcomes and a committed
  P1–P15
  prediction lock with protocol, implementation, input, and dependency hashes.
- A locked retrospective, censor-aware external evaluation that aggregates triplicates at the
  peptide level, preserves one-sided bounds, and retains all four predeclared
  models (ridge plus three comparators) and all endpoints.
- Outcome-independent sequence-dependence groupings, four-component descriptive resampling,
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
  analog evaluation—not a blinded evaluation on previously unseen outcomes or a
  newly prospective experiment.

## [0.2.0] - 2026-08-20

### Added

- Checksum-verified P1–P15 published-design parser with censor preservation.
- Training-only identity-threshold audit and deterministic 42/42/41 outer folds.
- Tied 1-nearest-neighbor and training-fold median CPU baselines.
- Machine-readable out-of-fold predictions, metric tables, and JSON reports.
- Release documentation, citation metadata, data-license attribution, and CI.

### Scientific boundary

- P1–P15 labels remain excluded from threshold, fold, feature, and baseline
  decisions.
- EC50 is reported as functional potency and never relabeled as binding affinity.

## [0.1.0] - 2026-08-19

- Initial provenance, validation, structure-manifest, and feasibility scaffold.
