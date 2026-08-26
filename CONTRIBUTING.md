# Contributing

Contributions that improve reproducibility, data validation, leakage controls, or
biological interpretation are welcome.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
make test
make lint
```

Please keep tests offline. Raw source workbooks must not be committed. The one
exception to the former model-weight rule is the versioned portable inference
artifact in `src/incretinselect/assets/`: it is checksum-receipted, derived from
CC BY 4.0 data with attribution, contains no per-reference assay labels, and must
continue to reproduce the committed pre-score prediction lock. Regenerate it only
with `make product-model` from checksum-verified inputs.

## Scientific requirements

- Never describe EC50 as affinity, Kd, or efficacy.
- Do not use the P1–P15 labels to select features, thresholds, hyperparameters, or
  models.
- Keep complete sequence components in one outer fold.
- Preserve censored measurements as one-sided bounds.
- Record source URLs, licenses, versions/commits, and checksums.
- Mark prospective computational designs as unvalidated until experimentally
  tested.

Changes to the frozen split config or evaluation policy require a written rationale
in `reports/` and regeneration of all affected artifacts.
