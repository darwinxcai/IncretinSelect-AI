# Project state

## Current release status

- Release `0.9.1` is the current verified public release.
- The default branch currently points to commit `096beed` (`Record verified v0.9.1 public release (#8)`), recorded on 2026-08-28.
- The verified public release payload is tag `v0.9.1` from source commit `366accfea5178bbabccddf9f1791c4a392f05764`, with its publication receipt bound to the exact CI, Pages, release, asset, and clean-clone evidence.
- The public product remains a frozen, sequence-only research model for cell-based cAMP EC50 functional potency. EC50 is not binding affinity, and the release does not establish validated therapeutic candidates or overall model superiority.

## Completed work

- Versions `0.9.0` and `0.9.1` strengthened product and release assurance without refitting the frozen coefficients.
- The browser application now accepts canonical 26–30-residue raw FASTA or text inputs through a checksum-bound adapter that maps into the frozen 30-column coordinate system only when the best reference-guided projections agree and the nearest aligned identity is at least `0.85`.
- The product now exposes the same guarded prediction path across browser, Python, and CLI workflows, including single-result JSON/CSV/Markdown export and checksum-bound batch-screening receipts.
- Release assurance now includes Python `3.10`, `3.11`, and `3.12` CI, measured branch coverage, real-Chromium acceptance and accessibility checks, Pages deployment gating, and versioned release assets whose published wheel and source archive are verified byte-for-byte against clean-clone distribution verification.
- Open GitHub work is currently limited to routine workflow-action dependency bumps rather than unresolved product bugs or an existing automation review branch.

## Verification evidence

- GitHub Actions CI run `33207902327` succeeded for the release payload, including `browser-acceptance` plus the `3.10`, `3.11`, and `3.12` Python matrices.
- GitHub Actions Pages run `33208008086` succeeded and the browser application remains published at <https://darwinxcai.github.io/IncretinSelect-AI/>.
- GitHub Actions release run `33208008122` produced the public `v0.9.1` release.
- The public release assets currently record these SHA-256 digests:
  - `incretinselect_ai-0.9.1-py3-none-any.whl`: `a2c1dc156aaace51420838596312b21f1df8822eae86a3e4caea9ab98104286c`
  - `incretinselect_ai-0.9.1.tar.gz`: `6eb8473769e3c37fe918f7d5e71af9618700cdee4a755d4cbc57bc6b432d1f32`
  - `SHA256SUMS`: `fa6a0c15dafcb943872aab111b4c05b1cb073c88922744c637b3a7a7c60331f4`
- `RELEASE_READINESS.md` and `reports/STATUS.md` both reflect `0.9.1` as publicly verified.
- This state snapshot was assembled from live GitHub repository evidence on 2026-09-03 because the local mirror available to this automation is behind the current default branch.

## Known limitations

- The released model is still limited to compatible incretin-like local analogs represented with the 20 standard amino-acid letters.
- The adapter rejects ambiguous mappings, sequences outside 26–30 residues, and raw inputs outside the local-analog gate; expert users must provide a reviewed 30-column alignment when automatic projection is out of scope.
- The software does not represent Aib, lipidation, amidation, cyclization, stapling, D-amino acids, or other noncanonical chemistry.
- Structure upload remains intentionally absent because the released model has no validated structural features.
- The applicability threshold of `0.85` is a benchmark-derived software gate, not a calibrated probability that an individual prediction is correct.
- The locked retrospective P1–P15 evaluation remains mixed and does not justify an overall external-win or therapeutic-selection claim.

## Next three prioritized tasks

1. Keep `PROJECT_STATE.md` on the default-branch review path and refresh it whenever release status, workflow evidence, or public artifact receipts change.
2. Decide whether to merge the currently green GitHub Actions dependency-upgrade pull requests after confirming they preserve the existing release-verification policy.
3. Collect user feedback on adapter failures, CSV exclusion reasons, and result wording before expanding model scope or adding structure-derived inputs.
