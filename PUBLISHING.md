# GitHub release and verification

The last verified public release, version 0.6.0, is available. Its successful CI
jobs on Python 3.10 and 3.12, browser deployment, and fresh-clone release check are
recorded in `reports/publication_receipt.json`.

## Last verified release

- Repository: <https://github.com/darwinxcai/IncretinSelect-AI>
- Browser application: <https://darwinxcai.github.io/IncretinSelect-AI/>
- Source commit: `19c70897e1df03900f0a4ef787c774da62f11bf0`
- CI run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33014760548>
- Pages run: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33014760488>

## Initial publication procedure

The repository-creation procedure below is retained for provenance. It has already
been completed and must not be run again for the existing repository.

```bash
# Read-only preflight
python scripts/bootstrap_github.py

# Initial repository creation only
python scripts/bootstrap_github.py --execute
```

The execution mode requires GitHub CLI authentication, a clean `main` branch, no
existing `origin`, a passing distribution check, and the configured public target
`darwinxcai/IncretinSelect-AI`. It creates the repository, pushes the current
commit, enables GitHub Pages when permitted, and verifies the resulting URL and
visibility.

If repository creation succeeds but Pages activation is unavailable, the script
records repository publication as complete and Pages activation as pending. After
selecting **Settings → Pages → Source → GitHub Actions**, request one deployment:

```bash
gh workflow run pages.yml --repo darwinxcai/IncretinSelect-AI
```

Avoid dispatching duplicate workflows during a GitHub service interruption. Wait
for service recovery and then request one CI run and one Pages run.

## Verification before a release

1. Run `make lint`, `make test`, `make product-smoke`, `make static-demo`, and
   `make release-check` from a clean working tree.
2. Push the release commit and confirm that both Python 3.10 and 3.12 CI jobs pass.
3. Confirm that the Pages workflow passes and open the browser application.
4. Run the bundled example and confirm that the displayed model SHA-256 matches
   `reports/static_demo_verification.json`.
5. Clone the public repository into a new directory and run `make release-check`
   and `make static-demo` from that checkout.
6. Record the repository URL, application URL, source commit, CI run, deployment
   run, and fresh-clone result in `reports/publication_receipt.json` and
   `reports/STATUS.md`.
7. Run the release-readiness audit with `--require-public`; see
   [`RELEASE_READINESS.md`](RELEASE_READINESS.md).

## Scientific and data boundaries

Do not publish raw source workbooks or the redundant label-bearing P1–P15 mirror.
The released endpoint is cell-based cAMP EC50 functional potency, not binding
affinity, maximal assay response, safety, or clinical activity. The locked retrospective
P1–P15 external evaluation remains mixed and must not be reused for model selection
or tuning.
