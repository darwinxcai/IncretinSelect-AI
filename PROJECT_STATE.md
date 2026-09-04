# Project state

## Current release status

- Release `0.9.1` remains public-release verified.
- The current default-branch head is commit `096beed` (`Record verified v0.9.1 public release (#8)`), created on 2026-08-28.
- The audited release payload remains commit `366accf` (`Release v0.9.1 with exact-artifact verification (#7)`), which passed all public gates:
  - CI run `33207902327`
  - Pages run `33208008086`
  - release workflow run `33208008122`
  - GitHub Release `v0.9.1`
- The public product remains a frozen, sequence-based research model for cell-based cAMP EC50 functional potency. EC50 is not binding affinity, and the release does not establish validated therapeutic candidates or overall model superiority.
- On 2026-08-29, later `workflow_run` listener entries on `main` were skipped by design after the receipt-only commit advanced the default branch beyond the validated release payload SHA. Those skipped listeners do not indicate a product or deployment regression.

## Completed work

- Version `0.9.1` added raw 26-30 residue sequence handling, browser download/export paths, broader Python and browser verification, measured coverage gates, versioned release automation, and exact-artifact publication checks.
- GitHub Pages deployment follows successful CI for the exact current validated SHA, and the release workflow publishes only when the validated commit still matches the default-branch head.
- As of 2026-09-03, GitHub shows six open Dependabot pull requests (`#2`-`#6`, `#10`) and no open automation-authored review PR.

## Verification evidence

- GitHub Actions CI run `33207902327` succeeded on the release payload commit for Python `3.10`, `3.11`, and `3.12`, plus the `browser-acceptance` job.
- GitHub Actions Pages run `33208008086` succeeded on the release payload commit. The `verify` and `deploy` jobs both passed, and the browser application remains published at <https://darwinxcai.github.io/IncretinSelect-AI/>.
- GitHub Actions release run `33208008122` succeeded on the release payload commit and published release `v0.9.1`.
- `reports/release_readiness.json` records `PUBLIC_RELEASE_VERIFIED` for version `0.9.1`.
- `reports/distribution_verification.json` records a passed isolated wheel installation, prediction export, guarded screening export, browser smoke check, resource sync, and deterministic source-package rebuild.
- The published release assets currently report these SHA-256 digests:
  - `incretinselect_ai-0.9.1-py3-none-any.whl`: `a2c1dc156aaace51420838596312b21f1df8822eae86a3e4caea9ab98104286c`
  - `incretinselect_ai-0.9.1.tar.gz`: `6eb8473769e3c37fe918f7d5e71af9618700cdee4a755d4cbc57bc6b432d1f32`
  - `SHA256SUMS`: `fa6a0c15dafcb943872aab111b4c05b1cb073c88922744c637b3a7a7c60331f4`
- This run did not rerun local code against the live `main` checkout because the workspace mirror is behind the GitHub default branch. Current GitHub workflow and release evidence were used as the trustworthy validation source.

## Known limitations

- The product is intended for canonical 26-30 residue sequence inputs and does not model noncanonical chemistry such as Aib substitutions, lipidation, amidation, or cyclization.
- It does not perform structure inference, docking, or structure-conditioned prediction.
- The external 15-peptide comparison remains mixed and dependence-sensitive. No justified overall-superiority claim should be made.
- The `0.85` nearest-identity threshold is a benchmark-derived software applicability gate, not a calibrated probability that an individual prediction is correct.
- Browser and CLI outputs should continue to preserve the distinction between functional potency ranking support and therapeutic decision-making.

## Next three prioritized tasks

1. Keep `PROJECT_STATE.md` current whenever release evidence, deployment evidence, or open dependency PR state changes.
2. Decide whether to consolidate or selectively merge the six open Dependabot PRs without weakening full-SHA action pinning or the validated-SHA deployment safeguards.
3. Improve user-facing workflow guidance around raw-sequence versus already-aligned expert inputs and the interpretation limits on applicability and ranking output.
