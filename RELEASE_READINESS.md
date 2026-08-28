# Release readiness

The audit separates two questions:

1. **Is the software locally release-ready?** Scientific boundaries, tests,
   packaging, browser parity, licensing, and workflow policy must pass.
2. **Is the public release verified?** The exact source payload must also have green
   Python 3.10/3.11/3.12 CI, real-browser acceptance/accessibility, a successful
   Pages deployment, a clean public-clone check, and a versioned GitHub Release whose
   wheel and source archive are the exact bytes exercised by distribution
   verification.

Version 0.9.0 is publicly released and its source passed CI, Pages deployment, the
release workflow, and a clean-clone check. The strengthened audit deliberately does
not mark it fully public-release verified because the workflow rebuilt the upload
assets after verification. Version 0.9.1 changes the workflow to publish the exact
verified artifacts and makes that equality a required receipt gate.

- v0.9.0 CI: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206129159>
- v0.9.0 Pages: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206238008>
- v0.9.0 release workflow: <https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/33206238005>
- v0.9.0 Release: <https://github.com/darwinxcai/IncretinSelect-AI/releases/tag/v0.9.0>

## Local audit

```bash
make release-readiness
```

This command displays the audit in the terminal. To update the checked
machine-readable report, run the auditor with
`--json-output reports/release_readiness.json`. The release payload fingerprint
covers every release-critical tracked path and its bytes. Post-verification
attestations are excluded so recording a result does not change the payload being
attested.

## Public audit

After CI, Pages, the versioned release, and a clean-clone release check pass, update
`reports/publication_receipt.json` with the exact commit, tree, run URLs, asset names,
asset SHA-256 digests, and verified artifact digests. Then run:

```bash
python scripts/audit_release_readiness.py \
  --require-public \
  --as-of YYYY-MM-DD \
  --json-output reports/release_readiness.json
```

The automatic Pages workflow accepts only successful CI for the current
default-branch commit. A manual deployment runs the complete three-version matrix,
with browser acceptance/accessibility on Python 3.12.

The audit does not train a model, access P1–P15 outcome labels, run structure
inference, or reinterpret cAMP EC50 as binding affinity.
