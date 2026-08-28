# Publishing and verification

Version 0.9.0 is the current public release. Its exact source passed the
three-version CI matrix, real-browser acceptance/accessibility tests, Pages
deployment, and a clean public-clone check. The release assets are checksum-bound,
but the v0.9.0 workflow rebuilt them after distribution verification; therefore the
strengthened public audit does not claim that those uploaded bytes are the exact
verified bytes. Version 0.9.1 is a release-assurance patch that closes this gap.

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- v0.9.0 source commit: `d8fea1b6df862729a42bd19a997a5be6ca90f01f`
- v0.9.0 source tree: `7843817e055cfaf54a6ac11a103d57aac195b1ee`
- CI run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206129159>
- Pages run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206238008>
- Release workflow: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206238005>
- GitHub Release: <https://github.com/darwinxcai/IncretinSelect-AI/releases/tag/v0.9.0>

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

Versions 0.9.0 and 0.9.1 change usability, testing, and release assurance. They do
not refit the frozen model or adapter, access P1–P15 outcomes, or broaden the
26–30-residue scope.

The initial repository-creation helper is retained only for provenance. Do not run
it again against the existing public repository.
