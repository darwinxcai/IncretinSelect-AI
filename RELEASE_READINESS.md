# Release readiness

The release audit distinguishes local package verification from verification of the
public release:

1. **Locally release-ready** means that the scientific boundaries, tests,
   distribution checks, browser checks, and public-bundle checks pass in the source
   tree.
2. **Publicly verified** additionally requires a successful overall GitHub Actions
   workflow, a deployed browser application, and `make release-check` from a fresh
   clone of the public repository.

The last verified public release, version 0.6.0, satisfies both criteria. Its
checked receipt records the source commit, Python 3.10 and 3.12 CI results, browser
deployment, and fresh-clone verification. The verified CI run is
<https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33014760548>.

## Run the local audit

```bash
make release-readiness
```

When `reports/publication_receipt.json` is present, the audit also checks its public
release evidence. A URL alone is insufficient: the receipt must identify a matching
source tree, successful overall CI workflow, deployed application, and complete
fresh-clone release check.

The automatic Pages workflow accepts only a successful `CI` run for the exact
current default-branch commit. A manual Pages dispatch runs the complete Python
3.10/3.12 release matrix before it can deploy.

The receipt is also bound to a deterministic release-payload fingerprint. The
fingerprint covers the sorted tracked path set and every included file's bytes, so
an addition, deletion, rename, or same-version source edit invalidates earlier
public evidence. Only the post-verification attestation files listed by
`RELEASE_PAYLOAD_EXCLUDED_PATHS` are omitted to avoid a self-referential hash. Each
generated readiness report records the fingerprint it audited.

To write a dated machine-readable receipt:

```bash
python scripts/audit_release_readiness.py \
  --as-of YYYY-MM-DD \
  --json-output reports/release_readiness.json
```

## Verify a public release

After CI, deployment, and fresh-clone checks pass, update
`reports/publication_receipt.json` or supply the corresponding evidence directly:

```bash
python scripts/audit_release_readiness.py \
  --public-repository-url https://github.com/darwinxcai/IncretinSelect-AI \
  --public-demo-url https://darwinxcai.github.io/IncretinSelect-AI/ \
  --ci-run-url https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/RUN_ID \
  --verified-release-payload-sha256 PAYLOAD_SHA256 \
  --fresh-clone-release-check \
  --require-public \
  --json-output reports/release_readiness.json
```

Use `--fresh-clone-release-check` only after the check has passed in a new checkout
of the public repository. The audit restricts public URLs to the configured owner
and repository and requires the overall workflow—not only individual jobs—to have
succeeded.

The audit reads release metadata and tracked filenames. In a source archive without
`.git`, it evaluates the extracted release files. It does not train a model, access
P1–P15 outcome labels, run structure inference, or reinterpret cAMP EC50 as binding
affinity.
