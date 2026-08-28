# Project status

**Updated:** 2026-08-28  
**Current public release:** 0.9.0  
**Next patch:** 0.9.1 release-assurance candidate

IncretinSelect-AI is research software for estimating GLP-1R and GCGR cell-based
cAMP EC50 from compatible incretin-like peptide sequences. It supports guarded
single-sequence review and batch ordering for laboratory follow-up. It is not a
binding-affinity, efficacy, safety, or clinical-outcome predictor.

Version 0.9.0 strengthens product and release assurance without refitting the model
or changing its 26–30-residue local-analog scope. It adds Python 3.11 CI, measured
branch coverage, real-Chromium acceptance/accessibility testing, clearer first-use
and interpretation copy, versioned release assets, and security/dependency policy.
Version 0.9.1 closes the remaining release-provenance gap by publishing the exact
deterministic wheel and source archive exercised by distribution verification.

## Public evidence for v0.9.0

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- Source commit: `d8fea1b6df862729a42bd19a997a5be6ca90f01f`
- Source tree: `7843817e055cfaf54a6ac11a103d57aac195b1ee`
- CI: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206129159>
- Pages deployment: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206238008>
- Release workflow: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206238005>
- GitHub Release: <https://github.com/darwinxcai/IncretinSelect-AI/releases/tag/v0.9.0>

Python 3.10, 3.11, and 3.12 each passed 113 tests. Python 3.12 measured 72%
branch-mode coverage against a 70% floor, and four real-Chromium
acceptance/accessibility tests passed. A clean clone of the exact v0.9.0 tag passed
Ruff, the complete Python suite, product smoke, static parity, and distribution
verification without changing tracked files.

The v0.9.0 release assets have published SHA-256 digests, but their wheel bytes were
rebuilt after the verifier completed and do not equal its recorded deterministic
wheel. The strengthened public audit records this rather than overstating the
release. Version 0.9.1 makes exact uploaded-artifact equality mandatory.

## Product capabilities

- Paste or import one canonical 26–30-residue FASTA/text sequence; accept an
  automatic mapping only when all optimal reference-guided projections agree and
  nearest aligned identity is at least 85%.
- Use a reviewed 30-column alignment through a separate expert mode; residues are
  never trimmed in either mode.
- Read predicted functional potency, receptor profile, model applicability, and
  validation evidence as separate result fields rather than one quality score.
- Download single results as JSON, CSV, or Markdown.
- Import a candidate CSV and rank compatible sequences for GLP-1R, GCGR, or the
  both-receptors minimax objective (not evidence of dual agonism).
- Keep invalid and out-of-scope rows visible instead of silently dropping them.
- Report the nearest development reference and per-position prediction differences.
- Generate checksum-bound batch outputs and an audit receipt entirely in the browser.
- Run the same frozen model through the browser, Python API, or command line.

The browser processes imported sequences locally. Structure upload is intentionally
absent because the released model has no validated structural features.

## Scientific result

The strongest result is a reproducible, leakage-resistant benchmark—not a claim of
drug-discovery performance. On 125 cluster-held-out development records, ridge
regression reduced pooled receptor-potency MAE relative to tied 1-nearest-neighbour,
but selectivity did not improve and all paired component-bootstrap intervals
included zero. Performance also varied substantially across folds.

The locked retrospective evaluation on 15 published designs was mixed. GCGR error
was lower in the pooled comparison, while GLP-1R error was higher; the available
dependence-aware intervals did not support overall superiority. P1–P15 remain closed
to future tuning.

The frozen coefficients, adapter, benchmark, and locked retrospective evaluation are
unchanged from v0.8.0.

## Next work

1. Collect user feedback on mapping failures, CSV exclusions, result wording, and
   downloaded receipts before adding model complexity.
2. Add structural inputs only if a preregistered structure-aware model improves on
   this sequence baseline beyond seed variation.

No peptide–receptor structure prediction, prospective experimental result, or
overall external model-win claim is made in this release.
