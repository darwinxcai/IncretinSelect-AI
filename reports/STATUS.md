# Project status

**Updated:** 2026-08-27
**Release:** 0.7.0
**State:** Public release verified

IncretinSelect-AI is a usable research-software release for estimating GLP-1R and
GCGR cell-based cAMP EC50 from aligned incretin-like peptide sequences. It supports
single-sequence review and guarded batch ranking for laboratory follow-up. It is not
a binding-affinity, efficacy, safety, or clinical-outcome predictor.

## Public release

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- Verified source commit: `517f97c1e31bc0c9fea5315184bde651bb6b671a`
- CI: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33083830513>
- Pages deployment: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33083916679>

The public source tree matches the audited local release. Python 3.10 and 3.12
both passed Ruff, 100 tests, product smoke tests, browser/Python parity, wheel
installation, deterministic source packaging, and the release-readiness audit. A
fresh public clone passed the same release checks and remained clean.

## Product capabilities

- Paste or import one aligned FASTA/text sequence and download JSON or CSV results.
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

1. Collect user feedback on alignment failures, CSV exclusions, and downloaded
   receipts before adding model complexity.
2. Test automatic alignment only with explicit mapping and failure-mode checks for
   the frozen 30-position input contract.
3. Add structural inputs only if a preregistered structure-aware model improves on
   this sequence baseline beyond seed variation.

No peptide–receptor structure prediction, prospective experimental result, or overall
external model-win claim is made in this release.
