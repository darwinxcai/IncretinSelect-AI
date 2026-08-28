# Publishing and verification

Version 0.9.1 is the current verified public release. Its exact source passed the
three-version CI matrix, real-browser acceptance/accessibility tests, Pages
deployment, versioned release workflow, and a clean public-clone check. The
published wheel and source archive are the exact deterministic bytes exercised by
distribution verification.

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- v0.9.1 source commit: `366accfea5178bbabccddf9f1791c4a392f05764`
- v0.9.1 source tree: `b47cbea88ba57b460b721e78fcf4c352bc9795e0`
- CI run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33207902327>
- Pages run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33208008086>
- Release workflow: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33208008122>
- GitHub Release: <https://github.com/darwinxcai/IncretinSelect-AI/releases/tag/v0.9.1>

## Release procedure

1. Start from a clean working tree.
2. Run `make lint`, `make test`, `make coverage`, `make product-smoke`,
   `make static-demo`, `make browser-acceptance`, and `make release-check`.
3. Push the release commit and require successful Python 3.10, 3.11, and 3.12 CI
   jobs plus the real-Chromium acceptance/accessibility job.
4. Let the Pages workflow deploy only the exact default-branch commit accepted by
   CI.
5. Let the release workflow reverify that exact commit, require a source-stable
   working tree, and publish the exact verified wheel and source archive with
   `SHA256SUMS`.
6. Verify the tag, GitHub Release, asset names, asset digests, and workflow result.
7. Repeat the release check in a clean public clone and confirm that the checks do
   not modify tracked files.
8. Record the commit, CI, deployment, release, payload fingerprint, asset digests,
   and clean-clone result in `reports/publication_receipt.json`.

The distribution verifier builds from an exact Git-tracked allowlist, installs the
wheel outside the repository, exercises the installed commands and browser
application, rebuilds from the source distribution, and checks byte determinism.
The public audit accepts a versioned release only when the uploaded wheel and source
archive digests equal the artifacts exercised by that verifier.

## Scientific boundaries

The endpoint is cell-based cAMP EC50 functional potency, not binding affinity,
maximal response, safety, or clinical activity. The P1–P15 evaluation is a locked
retrospective test with mixed results and must not be reused for model selection.
Raw source workbooks and the label-bearing holdout mirror are not part of the public
release.

The 0.9 release series changes usability, testing, and release assurance. It does
not refit the frozen model or adapter, access P1–P15 outcomes, or broaden the
26–30-residue scope.

The initial repository-creation helper is retained only for provenance. Do not run
it again against the existing public repository.
