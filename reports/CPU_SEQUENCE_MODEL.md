# Nested CPU sequence model

**Status:** completed on all 125 training records under the frozen, cluster-intact
outer folds. **Reserved-set boundary:** this model command did not read P1–P15
sequences or activity labels. The later external-evaluation scoring command read
the published outcomes only after predictions were locked; they were not used for
this model's fitting, tuning, feature selection, or development-CV metrics.

## Method

The model is a multi-output ridge regression over a fixed 630-column encoding:
one indicator for each of 20 standard residues plus alignment gap at each of 30
positions. It predicts GCGR and GLP-1R log10(EC50 / 1 pM) jointly with one shared ridge
strength; selectivity is their predicted difference, not a separately optimized
target.

For every outer test fold, ridge strength is selected using leave-one-sequence-
component-out validation on that outer fold's training records only. Each component
gets equal total weight in every fit and equal weight in the inner objective. This
prevents the 40-, 34-, and 16-member analog series from dominating model
selection simply because they contain more variants. Preprocessing and the final
fit are repeated inside each outer split.

## Results

All metrics use out-of-fold predictions. Component-macro MAE first computes MAE
within each of the 17 frozen sequence components and then averages components.

![Out-of-fold sequence-model comparison](cpu_sequence_model_oof_figure.png)

| Model | Endpoint | Pooled MAE | Component-macro MAE | RMSE | Spearman rho | R2 |
|:---|:---|---:|---:|---:|---:|---:|
| tied 1-NN | GCGR log10(EC50 / 1 pM) | 0.769 | 0.638 | 1.119 | 0.671 | 0.440 |
| tied 1-NN | GLP-1R log10(EC50 / 1 pM) | 1.178 | 1.080 | 1.468 | 0.464 | 0.016 |
| tied 1-NN | selectivity log10 ratio | 1.095 | 0.895 | 1.328 | 0.576 | 0.162 |
| component-weighted ridge | GCGR log10(EC50 / 1 pM) | 0.627 | 0.612 | 0.846 | 0.740 | 0.680 |
| component-weighted ridge | GLP-1R log10(EC50 / 1 pM) | 1.070 | 1.189 | 1.375 | 0.576 | 0.136 |
| component-weighted ridge | selectivity log10 ratio | 1.136 | 1.017 | 1.425 | 0.538 | 0.034 |

### Paired comparison with tied 1-NN

Delta is `ridge MAE - 1-NN MAE`; negative values favor ridge. Intervals are
percentile intervals from 10000 paired resamples of
the 17 whole sequence components with seed 20260820.

| Endpoint | Ridge MAE | 1-NN MAE | Delta | Component-bootstrap 95% interval |
|:---|---:|---:|---:|:---|
| GCGR log10(EC50 / 1 pM) | 0.627 | 0.769 | -0.142 | [-0.779, 0.182] |
| GLP-1R log10(EC50 / 1 pM) | 1.070 | 1.178 | -0.108 | [-0.727, 0.249] |
| selectivity log10 ratio | 1.136 | 1.095 | 0.041 | [-0.139, 0.229] |

The ridge model lowers pooled MAE for both receptor potencies, but not for the
derived selectivity ratio. The three endpoints and both pooled and component-macro
summaries are retained; no favorable endpoint was selected after outer-fold
evaluation. With only 17 components and three outer folds, bootstrap intervals are
descriptive uncertainty summaries rather than a definitive hypothesis test.

### Training-only hyperparameter selection

| Outer test fold | Training records | Training components | Selected alpha |
|---:|---:|---:|---:|
| 1 | 83 | 14 | 1.0000 |
| 2 | 83 | 11 | 10.0000 |
| 3 | 84 | 9 | 1.0000 |

The complete inner-validation curve for every outer fold is stored in the JSON
report. The candidate grid and feature contract are versioned in
`configs/cpu_sequence_model.json`.

### Ridge MAE by outer fold

| Outer fold | n | GCGR | GLP-1R | Selectivity |
|---:|---:|---:|---:|---:|
| 1 | 42 | 0.293 | 1.514 | 1.606 |
| 2 | 42 | 1.047 | 0.928 | 1.155 |
| 3 | 41 | 0.538 | 0.760 | 0.634 |

Fold variability remains substantial, as expected when entire sequence families
are held out. EC50 is cell-based functional potency—not affinity, Kd, efficacy, or
a structural score. This is an exploratory development-CV comparison. P1–P15 was
prospective in the source study; this repository uses it as a locked retrospective
local-analog external evaluation. Predictions were generated without P1–P15 outcome
access and then scored once under the locked policy; the mixed result is reported in
`reports/EXTERNAL_EVALUATION.md`.

## Reproduce

```bash
python scripts/run_cpu_sequence_model.py
```

Machine-readable outputs are `reports/cpu_sequence_model_metrics.csv`,
`reports/cpu_sequence_model.json`, and
`data/derived/sequence_model_oof_predictions.csv`. The publication figure is
available as PNG and SVG, with its complete plotting table in
`data/derived/cpu_sequence_model_figure_source.csv`.
