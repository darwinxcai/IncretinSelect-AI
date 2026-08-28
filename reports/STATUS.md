# Project status

**Updated:** 2026-08-28
**Local release candidate:** 0.8.0
**Latest verified public release:** 0.7.0
**State:** v0.8.0 local gates passed; public verification pending

IncretinSelect-AI is research software for estimating GLP-1R and GCGR cell-based
cAMP EC50 from compatible incretin-like peptide sequences. Version 0.8.0 adds a
guarded, label-free adapter for canonical 26–30-residue raw sequences while keeping
the fitted 30-column model unchanged. It supports single-sequence review and guarded
batch ranking for laboratory follow-up. It is not a binding-affinity, efficacy,
safety, or clinical-outcome predictor.

## Latest verified public release

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- Verified source commit: `517f97c1e31bc0c9fea5315184bde651bb6b671a`
- CI: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33083830513>
- Pages deployment: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33083916679>

The v0.7 public source tree matches its audited local release. Python 3.10 and 3.12
both passed Ruff, 100 tests, product smoke tests, browser/Python parity, wheel
installation, deterministic source packaging, and the release-readiness audit. A
fresh public clone passed the same release checks and remained clean.

## Product capabilities

- Paste or import one canonical 26–30-residue FASTA/text sequence; accept an automatic
  mapping only when all optimal reference-guided projections agree and nearest
  aligned identity is at least 85%.
- Use a reviewed 30-column alignment through a separate expert mode; residues are
  never trimmed in either mode.
- Read predicted functional potency, receptor profile, model applicability, and
  validation evidence as separate result fields rather than one quality score.
- Download single results as JSON, CSV, or Markdown.
- Import a candidate CSV and rank compatible sequences for GLP-1R, GCGR, or a dual
  objective.
- Keep invalid and out-of-scope rows visible instead of silently dropping them.
- Report the nearest development reference and per-position prediction differences.
- Generate checksum-bound batch outputs and an audit receipt entirely in the browser.
- Run the same model through the browser, Python API, or command line.

The browser processes imported sequences locally. Structure upload is intentionally
absent because the released model has no validated structural features.

## Scientific result

The strongest result is a reproducible, leakage-resistant benchmark—not a claim of
drug-discovery performance. On 125 cluster-held-out development records, ridge
regression reduced pooled receptor-potency MAE relative to tied 1-nearest-neighbour,
but selectivity did not improve and all paired component-bootstrap intervals included
zero. Performance also varied substantially across folds.

The locked retrospective evaluation on 15 published designs was mixed. GCGR error
was lower in the pooled comparison, while GLP-1R error was higher; the available
dependence-aware intervals did not support overall superiority. P1–P15 remain closed
to future tuning.

## Next work

1. Publish v0.8.0, require green Python 3.10/3.12 CI and Pages deployment, and
   repeat the release checks from a fresh public clone.
2. Collect user feedback on mapping failures, CSV exclusions, result wording, and
   downloaded receipts before adding model complexity.
3. Add structural inputs only if a preregistered structure-aware model improves on
   this sequence baseline beyond seed variation.

No peptide–receptor structure prediction, prospective experimental result, or overall
external model-win claim is made in this release.
