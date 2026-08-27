# CPU sequence baseline

**Status:** completed on the frozen 125-record, training-only outer folds.
**External-evaluation boundary:** this command does not read the P1–P15 sequence or
activity workbooks, and no P1–P15 outcome was used for model choice or reporting.

## Result

All endpoints are represented as log10(EC50 / 1 pM). Selectivity is
`log10(GCGR EC50 / GLP-1R EC50)`, so positive values indicate relatively stronger
GLP-1R potency. The tied 1-NN prediction is the mean endpoint value among all
equally nearest sequences outside the query's entire sequence-cluster fold. The
comparator is the receptor-wise median of the other two folds.

| Model | Endpoint | n | MAE | RMSE | Fold error | Spearman rho | R2 |
|:---|:---|---:|---:|---:|---:|---:|---:|
| training-fold median | GCGR log10(EC50 / 1 pM) | 125 | 1.504 | 1.945 | 31.89× | -0.597 | -0.693 |
| training-fold median | GLP-1R log10(EC50 / 1 pM) | 125 | 1.535 | 1.753 | 34.30× | -0.273 | -0.403 |
| training-fold median | selectivity log10 ratio | 125 | 1.375 | 1.678 | 23.69× | 0.288 | -0.339 |
| tied 1-NN | GCGR log10(EC50 / 1 pM) | 125 | 0.769 | 1.119 | 5.87× | 0.671 | 0.440 |
| tied 1-NN | GLP-1R log10(EC50 / 1 pM) | 125 | 1.178 | 1.468 | 15.06× | 0.464 | 0.016 |
| tied 1-NN | selectivity log10 ratio | 125 | 1.095 | 1.328 | 12.44× | 0.576 | 0.162 |

### Tied 1-NN stability across folds

| Outer fold | n | GCGR MAE | GLP-1R MAE | Selectivity MAE |
|---:|---:|---:|---:|---:|
| 1 | 42 | 0.227 | 1.227 | 1.339 |
| 2 | 42 | 0.797 | 0.858 | 1.279 |
| 3 | 41 | 1.294 | 1.455 | 0.656 |

Nearest cross-fold sequence identity ranged from
**0.0667–0.8333**;
the maximum remains below the frozen 0.85 clustering boundary. There were
**98** queries with more than one equally
nearest donor.

## Interpretation

This is a deliberately simple, zero-tuning baseline—not a claim that nearest
neighbors are the best sequence model. Its scientific job is to establish the
performance that later sequence embeddings and predicted-complex features must
beat under the exact same held-cluster folds. Negative R2 or weak rank correlation
is valid evidence that local-analog transfer is unreliable after the leakage
barrier is enforced.

The 125 training endpoints are published as exact numeric EC50 values. The metric
library also represents right- and left-censored bounds using a constraint-
violation loss without converting bounds into exact measurements. That machinery
was used for the locked retrospective P1–P15 evaluation; a
zero bound loss was not described as zero exact error. See
`reports/EXTERNAL_EVALUATION.md`.

EC50 is functional potency from a cell-based cAMP assay. It is not binding
affinity, efficacy, Kd, or delta-delta-G.

## Reproduce

```bash
python scripts/run_cpu_baseline.py
```

Machine-readable outputs are `reports/cpu_baseline_metrics.csv`,
`reports/cpu_baseline.json`, and
`data/derived/baseline_oof_predictions.csv`.
