#!/usr/bin/env python3
"""Run locked outer-fold CPU baselines using training records only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from incretinselect.baseline import out_of_fold_predictions, point_metrics, summarize_predictions
from incretinselect.clustering import load_peptide_folds, write_csv
from incretinselect.sources import sha256_file
from incretinselect.training import load_training_records

PREDICTION_FIELDS = [
    "peptide_id",
    "outer_fold",
    "nearest_identity",
    "nearest_tie_count",
    "nearest_donor_ids",
    "actual_gcgr_log10_ec50_pm",
    "actual_glp1r_log10_ec50_pm",
    "actual_selectivity_log10_ratio",
    "nn_gcgr_log10_ec50_pm",
    "nn_glp1r_log10_ec50_pm",
    "nn_selectivity_log10_ratio",
    "median_gcgr_log10_ec50_pm",
    "median_glp1r_log10_ec50_pm",
    "median_selectivity_log10_ratio",
]
METRIC_FIELDS = [
    "model",
    "endpoint",
    "n",
    "mae_log10_pm",
    "rmse_log10_pm",
    "geometric_fold_error",
    "pearson_r",
    "spearman_rho",
    "r_squared",
]


def _display(value: object, decimals: int = 3) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _markdown(payload: dict[str, object]) -> str:
    metric_rows = []
    for row in payload["pooled_metrics"]:  # type: ignore[union-attr]
        metric_rows.append(
            "| {model} | {endpoint} | {n} | {mae} | {rmse} | {fold_error}× | "
            "{rho} | {r2} |".format(
                model="tied 1-NN" if row["model"] == "nn" else "training-fold median",
                endpoint=row["endpoint"],
                n=row["n"],
                mae=_display(row["mae_log10_pm"]),
                rmse=_display(row["rmse_log10_pm"]),
                fold_error=_display(row["geometric_fold_error"], 2),
                rho=_display(row["spearman_rho"]),
                r2=_display(row["r_squared"]),
            )
        )
    fold_rows = []
    for row in payload["nn_fold_metrics"]:  # type: ignore[union-attr]
        fold_rows.append(
            "| {fold} | {n} | {gcgr} | {glp1r} | {selectivity} |".format(
                fold=row["outer_fold"],
                n=row["n"],
                gcgr=_display(row["gcgr_mae_log10_pm"]),
                glp1r=_display(row["glp1r_mae_log10_pm"]),
                selectivity=_display(row["selectivity_mae_log10_ratio"]),
            )
        )
    return f"""# CPU sequence baseline

**Status:** completed on the frozen 125-record, training-only outer folds.
**Holdout boundary:** this command does not read the P1–P15 sequence or activity
workbooks, and no prospective label was used for model choice or reporting.

## Result

Receptor endpoints are represented as log10(EC50 / 1 pM). Selectivity is
`log10(GCGR EC50 / GLP-1R EC50)`, so positive values indicate relatively stronger
GLP-1R potency. The tied 1-NN prediction is the mean endpoint value among all
equally nearest sequences outside the query's entire sequence-cluster fold. The
comparator is the receptor-wise median of the other two folds.

| Model | Endpoint | n | MAE | RMSE | Fold error | Spearman rho | R2 |
|:---|:---|---:|---:|---:|---:|---:|---:|
{chr(10).join(metric_rows)}

### Tied 1-NN stability across folds

| Outer fold | n | GCGR MAE | GLP-1R MAE | Selectivity MAE |
|---:|---:|---:|---:|---:|
{chr(10).join(fold_rows)}

Nearest cross-fold sequence identity ranged from
**{payload['nearest_identity_min']:.4f}–{payload['nearest_identity_max']:.4f}**;
the maximum remains below the frozen 0.85 clustering boundary. There were
**{payload['queries_with_nearest_ties']}** queries with more than one equally
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
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", default="data/raw/training_data.xlsx")
    parser.add_argument("--folds", default="data/derived/outer_folds.csv")
    parser.add_argument("--predictions", default="data/derived/baseline_oof_predictions.csv")
    parser.add_argument("--metrics-csv", default="reports/cpu_baseline_metrics.csv")
    parser.add_argument("--report-json", default="reports/cpu_baseline.json")
    parser.add_argument("--report-md", default="reports/CPU_BASELINE.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = load_training_records(args.training, expected_records=125)
    peptide_folds = load_peptide_folds(args.folds)
    predictions = out_of_fold_predictions(records, peptide_folds)
    pooled_metrics = summarize_predictions(predictions)

    fold_metrics = []
    for fold in sorted(set(peptide_folds.values())):
        rows = [row for row in predictions if row["outer_fold"] == fold]
        endpoint_metrics = {}
        for endpoint in ("gcgr_log10_ec50_pm", "glp1r_log10_ec50_pm", "selectivity_log10_ratio"):
            endpoint_metrics[endpoint] = point_metrics(
                [float(row[f"actual_{endpoint}"]) for row in rows],
                [float(row[f"nn_{endpoint}"]) for row in rows],
            )
        fold_metrics.append(
            {
                "outer_fold": fold,
                "n": len(rows),
                "gcgr_mae_log10_pm": endpoint_metrics["gcgr_log10_ec50_pm"]["mae_log10_pm"],
                "glp1r_mae_log10_pm": endpoint_metrics["glp1r_log10_ec50_pm"]["mae_log10_pm"],
                "selectivity_mae_log10_ratio": endpoint_metrics["selectivity_log10_ratio"]["mae_log10_pm"],
            }
        )

    write_csv(Path(args.predictions), predictions, PREDICTION_FIELDS)
    write_csv(Path(args.metrics_csv), pooled_metrics, METRIC_FIELDS)
    identities = [float(row["nearest_identity"]) for row in predictions]
    payload: dict[str, object] = {
        "schema_version": 1,
        "endpoint": "cAMP accumulation EC50",
        "unit": "log10(pM)",
        "endpoint_warning": "Functional potency, not binding affinity or efficacy.",
        "model_selection": "none",
        "holdout_labels_accessed": False,
        "training_records": len(records),
        "training_sha256": sha256_file(args.training),
        "folds_sha256": sha256_file(args.folds),
        "observed_training_labels": len(records) * 2,
        "censored_training_labels": 0,
        "nearest_identity_min": min(identities),
        "nearest_identity_max": max(identities),
        "queries_with_nearest_ties": sum(int(row["nearest_tie_count"]) > 1 for row in predictions),
        "pooled_metrics": pooled_metrics,
        "nn_fold_metrics": fold_metrics,
    }
    report_json = Path(args.report_json)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    Path(args.report_md).write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
