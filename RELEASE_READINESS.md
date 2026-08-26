# Release readiness

IncretinSelect-AI separates two claims that are easy to blur:

1. **Local release ready** means the scientific boundaries, tests, built package,
   guarded batch-screening example, zero-install demo, public-bundle hygiene, and
   CI contract are present and internally auditable.
2. **Public release verified** additionally requires a public repository, a
   clean top-level GitHub Actions success, a deployed browser demo, and
   `make release-check` from a separate public clone.

Run the local audit without changing the repository:

```bash
make release-readiness
```

When `reports/publication_receipt.json` is present, this command automatically
audits its checked-in public evidence. A URL alone is not enough: the repository
must have a matching source-tree attestation, the clean clone must pass every
recorded check, the CI workflow itself must conclude successfully, and the demo
must be recorded as deployed. This prevents green child jobs inside a red
infrastructure-failed workflow from being mislabeled as a fully verified release.

Write a dated machine-readable receipt:

```bash
python scripts/audit_release_readiness.py \
  --as-of 2026-08-26 \
  --json-output reports/release_readiness.json
```

After a clean CI run and Pages deployment, update the publication receipt or
supply inspectable evidence and require all public gates:

```bash
python scripts/audit_release_readiness.py \
  --public-repository-url https://github.com/darwinxcai/IncretinSelect-AI \
  --public-demo-url https://darwinxcai.github.io/IncretinSelect-AI/ \
  --ci-run-url https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/RUN_ID \
  --fresh-clone-release-check \
  --require-public \
  --json-output reports/release_readiness.json
```

Do not set `--fresh-clone-release-check` unless the command actually passed in a
new checkout of the public repository. URLs are shape-validated and deliberately
restricted to the intended owner and repository.

The audit reads release metadata and tracked filenames. In a source archive that
does not contain `.git`, it audits the extracted release files instead. It does
not train a model, read P1–P15 outcome labels, run structure inference, or convert
EC50 into an affinity claim.
