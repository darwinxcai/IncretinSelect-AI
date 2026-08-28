# Release readiness

The audit separates two questions:

1. **Is the software locally release-ready?** Scientific boundaries, tests,
   packaging, browser parity, licensing, and workflow policy must pass.
2. **Is the public release verified?** The exact source payload must also have green
   CI, a successful Pages deployment, and a passing check from a fresh public clone.

Version 0.8.0 satisfies the local criteria. Public verification is intentionally
blocked until its exact source commit has green Python 3.10/3.12 CI, a successful
Pages deployment, and a passing fresh-clone release check. Version 0.7.0 is the
latest release satisfying both criteria; its verified CI run is
<https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33083830513>.

## Local audit

```bash
make release-readiness
```

This command displays the audit in the terminal. To update the checked
machine-readable report, run the auditor with
`--json-output reports/release_readiness.json`. The release payload fingerprint
covers every release-critical tracked path and its bytes. Post-verification
attestations are excluded so recording the result does not change the payload being
attested.

## Public audit

After CI, Pages, and a fresh-clone release check pass:

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

The automatic Pages workflow accepts only a successful CI run for the current
default-branch commit. A manual deployment runs the complete two-version test matrix
before publishing.

The audit does not train a model, access P1–P15 outcome labels, run structure
inference, or reinterpret cAMP EC50 as binding affinity.
