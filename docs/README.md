# Browser application

This directory contains the static, zero-install application deployed through
GitHub Pages. It uses the same frozen, label-free model artifact as the Python
package. Prediction math, aligned FASTA/text import, CSV screening, and result
downloads run locally in the browser. There is no server API, analytics service,
account, or outbound transmission of an imported sequence.

Preview it locally from the repository root:

```bash
python -m http.server 8000 --directory docs
```

Then open `http://127.0.0.1:8000`. Opening `index.html` directly with a `file://`
URL is intentionally unsupported because the demo fetches and verifies its model
file before enabling inference.

Verify that the copied model is current and that browser predictions match Python:

```bash
make static-demo
```

`scripts/sync_static_demo.py` is the only supported way to update the copied model
and checksum manifest. The deployment workflow refuses stale or numerically
inconsistent assets.

Single-sequence input must contain exactly one already-aligned 30-position core.
Batch input must be UTF-8 CSV with exactly `candidate_id,aligned_sequence`; the
browser requires an explicit GLP-1R, GCGR, or dual sorting objective and retains
invalid and out-of-scope rows in the downloaded result. Structure files are not
accepted because this release does not perform structure-aware inference.

Outputs remain point estimates of cell-based cAMP EC50 functional potency. They
are not affinity, efficacy, safety, experimental validation, or a drug-candidate
recommendation. Inputs outside the close-analogue and modeled-length ranking gate
receive a prominent do-not-rank warning.
