# Publishing and verification

Version 0.8.0 is the current verified public release. Its source, CI, Pages, and
fresh-clone evidence are recorded in `reports/publication_receipt.json`.

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- Verified v0.8 source commit: `1e0e31b66d0ca417646e8bf42101b1bd243d3288`
- Verified source tree: `9eed525d88a3e375f2e7aa253e85614ec0b15fab`
- CI run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33197985085>
- Pages run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33198064933>

## Release procedure

1. Start from a clean working tree.
2. Run `make lint`, `make test`, `make product-smoke`, `make static-demo`, and
   `make release-check`.
3. Push the release commit and require successful Python 3.10 and 3.12 CI jobs.
4. Let the Pages workflow deploy only the exact commit accepted by CI.
5. Open the browser application and verify prediction, import, and download flows.
6. Clone the public repository into a new directory and repeat the release check.
7. Record the commit, CI, deployment, payload fingerprint, and clone result in
   `reports/publication_receipt.json`.

The release check builds the wheel and complete source distribution from an exact
Git-tracked allowlist. It installs the wheel outside the repository, exercises the
installed commands and browser application, rebuilds from the source distribution,
and checks that repeated builds are byte-deterministic.

## Scientific boundaries

The endpoint is cell-based cAMP EC50 functional potency, not binding affinity,
maximal response, safety, or clinical activity. The P1–P15 evaluation is a locked
retrospective test with mixed results and must not be reused for model selection.
Raw source workbooks and the label-bearing holdout mirror are not part of the public
release.

The initial repository-creation helper is retained only for provenance. Do not run
it again against the existing public repository.
