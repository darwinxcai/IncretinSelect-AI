# Contributing

Contributions that improve reproducibility, data validation, leakage controls,
usability, or biological interpretation are welcome.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
make lint
make test
make product-smoke
make static-demo
```

Keep tests offline and do not commit raw source workbooks. The authoritative model
artifact is stored in `src/incretinselect/assets/`; `docs/assets/` contains its
checksum-verified browser copy. Preserve the documented checksum and provenance,
regenerate the authoritative artifact from verified inputs only with
`make product-model`, and synchronize the browser copy with
`scripts/sync_static_demo.py`.

## Scientific requirements

- Describe EC50 as functional potency, not binding affinity, Kd, or maximal
  efficacy.
- Do not use P1–P15 outcome labels to select features, thresholds,
  hyperparameters, or models.
- Keep each sequence-identity component within one outer fold.
- Preserve censored measurements as one-sided bounds.
- Record source URLs, licenses, versions or commits, and checksums.
- Label newly proposed computational sequences as unvalidated until they are tested
  experimentally.
- Retain unfavorable endpoints, input failures, and out-of-scope cases in reports.

Changes to the frozen split configuration or evaluation policy require a written
rationale in `reports/` and regeneration of all affected artifacts. Changes to user
interfaces must preserve the input contract, ranking gates, and browser/Python
parity checks.
