# Publish IncretinSelect-AI to GitHub

The local product and source archive are accepted. Public release has one external
gate: create `darwinxcai/IncretinSelect-AI`, push the exact tested commit, and let
GitHub Actions verify the clean public checkout.

## Safe one-command path

Install and authenticate [GitHub CLI](https://cli.github.com/) once, then run these
commands from the repository root:

```bash
# Non-mutating preflight: checks clean main, no origin, and prints the exact plan.
python scripts/bootstrap_github.py

# Explicitly create the public repository, rerun distribution verification,
# add origin, push the exact main commit, enable GitHub Pages, and request a
# verified browser-demo deployment.
python scripts/bootstrap_github.py --execute
```

The script refuses to continue when:

- the working tree is dirty;
- the current branch is not `main`;
- an `origin` remote already exists;
- the repository target is not an explicit `owner/name`;
- the built-wheel verification changes tracked files;
- GitHub authentication is unavailable; or
- the resulting repository is not exactly the requested public repository.

The default target is intentionally fixed to `darwinxcai/IncretinSelect-AI` and
publication is intentionally public. No repository is created in the default
dry-run mode.

Pages activation uses GitHub's repository Pages endpoint with
`build_type=workflow`, then manually requests the checked `pages.yml` workflow.
The authenticated identity must be able to administer the new repository and
manage Pages. If that final step lacks permission, the script reports a partial
success without pretending the already-created public repository was rolled
back. Enable **Settings → Pages → GitHub Actions**, then run:

```bash
gh workflow run pages.yml --repo darwinxcai/IncretinSelect-AI
```

## Required verification after the push

1. Open the printed public URL.
2. Confirm both CI matrix jobs pass on Python 3.10 and 3.12.
3. Confirm the Pages deployment passes and open the zero-install demo URL.
4. Run the bundled example and confirm the displayed artifact SHA-256 matches
   `reports/static_demo_verification.json`.
5. Clone the public URL into a new directory.
6. Run `make release-check` and `make static-demo` in that clean clone.
7. Record the repository URL, demo URL, exact commit, and CI runs in
   `reports/STATUS.md` before
   adding the project to a CV.

The repository includes a separate evidence audit so local completion cannot be
mistaken for public verification. See `RELEASE_READINESS.md`; after the fresh
clone passes, rerun `scripts/audit_release_readiness.py` with the exact public
repository URL, Actions run URL, `--fresh-clone-release-check`, and
`--require-public`.

Do not publish raw source workbooks or the redundant label-bearing holdout mirror.
Do not describe EC50 estimates as affinity, efficacy, or validated drug activity.
The P1–P15 result remains a retrospective one-shot comparison with a mixed
conclusion; it must not be reused for further tuning.
