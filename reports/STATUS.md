# Status

**Updated:** 2026-08-26
**Decision:** continue the public product release. The locked P1–P15 external
score is complete and mixed, the local application is functional, and further
modeling is not on the release-critical path. Publish and independently verify
the exact tested source before beginning a complex-prediction pilot.

## Complete

- [x] Created an installable Python package, reproducible command-line workflow,
      and offline unit-test suite.
- [x] Added a release check that builds the wheel, verifies bundled runtime files,
      installs it outside the source tree, and exercises JSON, single-row CSV,
      guarded batch-screening, and local-web entry points. The machine-readable
      receipt preserves the EC50 boundary and records that no holdout labels or
      structure inference were accessed.
- [x] Added `incretin-screen` for a practical shortlist workflow. It requires an
      explicit GLP-1R, GCGR, or dual objective, ranks only close analogues with at
      least 26 standard residues, retains errors and exclusions, and writes a
      checksum-bound audit receipt. Its checked demo uses label-free development
      references rather than P1–P15.
- [x] Added a guarded GitHub publication bootstrap. Dry-run is the default;
      `--execute` requires a clean `main`, no existing `origin`, a passing release
      check, GitHub authentication, the exact public target, and post-creation URL
      and visibility verification.
- [x] Added a machine-readable release-readiness audit. It passes seven local
      gates and separately blocks public-verification status until exact public
      repository, browser-demo, Actions-run, and fresh-clone evidence exists.
- [x] Added a zero-install browser demo that verifies the frozen model checksum
      before inference, sends no sequences to a server, and matches Python on 12
      label-free references within `1e-12`. A guarded Pages workflow deploys it
      only after the parity and privacy checks pass.
- [x] Pinned primary source files, repository commit, licenses, assay mappings,
      and SHA-256 checksums.
- [x] Validated 125 training records and the T1=GCGR / T2=GLP-1R mapping.
- [x] Frozen the official P1–P15 evaluation set with right-censoring retained:
      9/45 GCGR and 12/45 GLP-1R replicate cells are bounds.
- [x] Confirmed 0 exact P1–P15 training overlaps; nearest training distance is one
      mutation for 3 designs and three mutations for 12 designs.
- [x] Audited six sequence-identity thresholds without reading potency labels.
- [x] Frozen 17 components at 0.85 identity and deterministic outer folds of
      42/42/41; maximum cross-fold identity is 0.8333.
- [x] Ran a zero-tuning, training-only tied 1-NN baseline for GCGR potency,
      GLP-1R potency, and their log10 selectivity ratio.
- [x] Ran a nested, component-weighted aligned-sequence ridge model on the same
      outer folds, with whole-component bootstrap uncertainty.
- [x] Committed label-independent final-model predictions, protocol, dependence
      groups, and hashes before the separate outcome-scoring command.
- [x] Scored P1–P15 exactly once from lock commit
      `7feed50339e6695859efdddcd92efd7197c7d1d3`, preserving receptor censoring,
      selectivity intervals, all comparators, and unfavorable results.
- [x] Released the 45-row peptide-endpoint audit table, machine-readable metrics
      and receipt, plus a deterministic PNG/SVG summary and source CSV.
- [x] Added machine-readable predictions/metrics, scientific reports, MIT/CC BY
      licensing metadata, citation metadata, contribution guidance, and CI.
- [x] Curated a structure seed panel with GIPR marked context-only and added an
      RCSB metadata resolver; all 10 receptor/peptide entity pairs are resolved.

## Sequence-model headline

On the 125 cluster-held-out records, nested ridge versus tied 1-NN achieved:

- GCGR MAE 0.627 versus 0.769 log10(pM);
- GLP-1R MAE 1.070 versus 1.178 log10(pM);
- selectivity MAE 1.136 versus 1.095 log10 ratio.

The ridge improvements are confined to pooled receptor-potency MAE. Component-
macro results are mixed, selectivity does not improve, and all paired component-
bootstrap intervals include zero. Fold-specific errors vary substantially. These
are development-CV results, not claims about P1–P15.

## External-evaluation headline

There is no overall external superiority result. On all 15 designs, ridge versus
tied 1-NN has a favorable GCGR constraint-MAE difference of -0.241, but the
four-external-component descriptive interval [-0.818, 0.343] and leave-one-
component-out range [-0.553, 0.047] cross zero. GLP-1R is unfavorable in the
pooled comparison (1.699 versus 1.361; delta +0.337) and unstable across
dependence weighting: component effects span -2.120 to +1.380 and the leave-one-
component-out range spans -0.184 to +0.513. Its pooled sign is also opposite to
all three group-macro signs.

Selectivity is exploratory only: on 10 exact complete cases, ridge versus 1-NN
has MAE 0.427 versus 0.622 and R2 0.805 versus 0.607; across 13 informative
records, constraint MAE is 0.447 versus 0.479. No component-resampling uncertainty
was predeclared for this secondary endpoint. Full results are in
`reports/EXTERNAL_EVALUATION.md`.

## Next

- [ ] Authenticate GitHub CLI and run
      `python scripts/bootstrap_github.py --execute` to create and push the exact
      clean commit to public `darwinxcai/IncretinSelect-AI`, enable Pages, and
      request the verified browser-demo deployment.
- [ ] Push the exact tested release commit and require the two-version GitHub
      Actions matrix, built-wheel check, browser parity check, and Pages
      deployment to pass.
- [ ] Clone the public repository into a fresh directory, run `make release-check`,
      and record the public URL and CI run before any structure benchmark begins.
- [ ] Only after publication, lock structural-pilot inputs, noncanonical-residue
      policy, predictor version, seed plan, and noise threshold.

No peptide–GPCR prediction, structural-feature result, new prospective experiment,
or external model-win claim is currently made.
