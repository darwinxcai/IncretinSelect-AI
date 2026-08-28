# Project status

**Updated:** 2026-08-28
**Current verified public release:** 0.8.0
**State:** released; source, CI, Pages, and fresh-clone checks passed

IncretinSelect-AI is research software for estimating GLP-1R and GCGR cell-based
cAMP EC50 from compatible incretin-like peptide sequences. Version 0.8.0 adds a
guarded, label-free adapter for canonical 26–30-residue raw sequences while keeping
the fitted 30-column model unchanged. It supports single-sequence review and guarded
batch ranking for laboratory follow-up. It is not a binding-affinity, efficacy,
safety, or clinical-outcome predictor.

## Verified public release

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- Verified source commit: `1e0e31b66d0ca417646e8bf42101b1bd243d3288`
- Verified source tree: `9eed525d88a3e375f2e7aa253e85614ec0b15fab`
- CI: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33197985085>
- Pages deployment: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33198064933>

The v0.8 public source tree matches its audited local release. Python 3.10 and 3.12
both passed Ruff, 113 tests, product smoke tests, browser/Python parity, wheel
installation, deterministic source packaging, and the release-readiness audit. A
fresh public clone passed the same release checks and remained clean. All 125
label-free development references round-trip through the raw-sequence adapter, and
11 accepted/rejected adapter cases match between Python and the browser.

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

1. Collect user feedback on mapping failures, CSV exclusions, result wording, and
   downloaded receipts before adding model complexity.
2. Add structural inputs only if a preregistered structure-aware model improves on
   this sequence baseline beyond seed variation.

No peptide–receptor structure prediction, prospective experimental result, or overall
external model-win claim is made in this release.
