# Browser demo

This directory is a static, zero-install inference demo for GitHub Pages. It uses
the same frozen, label-free model artifact as the Python package. Prediction math
runs in the browser; there is no server API, analytics, account, or sequence
upload.

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

The output remains a point estimate of cell-based cAMP EC50 functional potency.
It is not affinity, efficacy, safety, experimental validation, or a drug-candidate
recommendation. Inputs outside the close-analogue neighborhood receive a prominent
do-not-rank warning.
