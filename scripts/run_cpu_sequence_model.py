#!/usr/bin/env python3
"""Run nested, sequence-component-aware ridge analysis on frozen outer folds."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from incretinselect.baseline import out_of_fold_predictions, point_metrics
from incretinselect.clustering import write_csv
from incretinselect.sequence_model import (
    component_macro_mae,
    nested_component_ridge_predictions,
    paired_component_bootstrap_mae_delta,
)
from incretinselect.sources import sha256_file
from incretinselect.training import load_training_records

ENDPOINTS = {
    "GCGR log10 EC50 (pM)": "gcgr_log10_ec50_pm",
    "GLP-1R log10 EC50 (pM)": "glp1r_log10_ec50_pm",
    "selectivity log10 ratio": "selectivity_log10_ratio",
}
PREDICTION_FIELDS = [
    "peptide_id",
    "cluster_id",
    "outer_fold",
    "selected_alpha",
    "actual_gcgr_log10_ec50_pm",
    "actual_glp1r_log10_ec50_pm",
    "actual_selectivity_log10_ratio",
    "ridge_gcgr_log10_ec50_pm",
    "ridge_glp1r_log10_ec50_pm",
    "ridge_selectivity_log10_ratio",
    "nn_gcgr_log10_ec50_pm",
    "nn_glp1r_log10_ec50_pm",
    "nn_selectivity_log10_ratio",
    "nearest_identity",
    "nearest_tie_count",
    "nearest_donor_ids",
]
METRIC_FIELDS = [
    "model",
    "endpoint",
    "n",
    "mae_log10_pm",
    "component_macro_mae_log10_pm",
    "rmse_log10_pm",
    "geometric_fold_error",
    "pearson_r",
    "spearman_rho",
    "r_squared",
]


def _load_assignments(path: str | Path) -> tuple[dict[str, int], dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    folds: dict[str, int] = {}
    components: dict[str, str] = {}
    for row in rows:
        peptide_id = row.get("peptide_id", "")
        component = row.get("cluster_id", "")
        if not peptide_id or not component or not row.get("outer_fold"):
            raise ValueError("Fold table requires peptide_id, cluster_id, and outer_fold")
        if peptide_id in folds:
            raise ValueError(f"Duplicate peptide in fold table: {peptide_id}")
        folds[peptide_id] = int(row["outer_fold"])
        components[peptide_id] = component
    return folds, components


def _load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("schema_version") != 1:
        raise ValueError("Only CPU sequence model config schema version 1 is supported")
    if config.get("prospective_holdout_access") != "forbidden":
        raise ValueError("The sequence-model config must forbid prospective holdout access")
    return config


def _display(value: object, decimals: int = 3) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _metric_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    components = [str(row["cluster_id"]) for row in rows]
    for model in ("nn", "ridge"):
        for endpoint, column in ENDPOINTS.items():
            actual = [float(row[f"actual_{column}"]) for row in rows]
            predicted = [float(row[f"{model}_{column}"]) for row in rows]
            result = point_metrics(actual, predicted)
            metrics.append(
                {
                    "model": model,
                    "endpoint": endpoint,
                    "component_macro_mae_log10_pm": component_macro_mae(
                        actual, predicted, components
                    ),
                    **result,
                }
            )
    return metrics


def _comparisons(
    rows: list[dict[str, object]], bootstrap: dict[str, object]
) -> list[dict[str, object]]:
    comparisons: list[dict[str, object]] = []
    components = [str(row["cluster_id"]) for row in rows]
    for endpoint, column in ENDPOINTS.items():
        actual = [float(row[f"actual_{column}"]) for row in rows]
        ridge = [float(row[f"ridge_{column}"]) for row in rows]
        nearest = [float(row[f"nn_{column}"]) for row in rows]
        uncertainty = paired_component_bootstrap_mae_delta(
            actual,
            ridge,
            nearest,
            components,
            resamples=int(bootstrap["resamples"]),
            seed=int(bootstrap["seed"]),
            confidence_level=float(bootstrap["confidence_level"]),
        )
        comparisons.append(
            {
                "endpoint": endpoint,
                "ridge_mae_log10_pm": point_metrics(actual, ridge)["mae_log10_pm"],
                "nn_mae_log10_pm": point_metrics(actual, nearest)["mae_log10_pm"],
                **uncertainty,
            }
        )
    return comparisons


def _fold_metrics(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for fold in sorted({int(row["outer_fold"]) for row in rows}):
        fold_rows = [row for row in rows if int(row["outer_fold"]) == fold]
        result: dict[str, object] = {"outer_fold": fold, "n": len(fold_rows)}
        for endpoint, column in ENDPOINTS.items():
            prefix = {
                "GCGR log10 EC50 (pM)": "gcgr",
                "GLP-1R log10 EC50 (pM)": "glp1r",
                "selectivity log10 ratio": "selectivity",
            }[endpoint]
            metrics = point_metrics(
                [float(row[f"actual_{column}"]) for row in fold_rows],
                [float(row[f"ridge_{column}"]) for row in fold_rows],
            )
            result[f"{prefix}_mae_log10_pm"] = metrics["mae_log10_pm"]
        results.append(result)
    return results


def _markdown(payload: dict[str, object]) -> str:
    metric_lines = []
    for row in payload["pooled_metrics"]:  # type: ignore[union-attr]
        metric_lines.append(
            "| {model} | {endpoint} | {mae} | {macro} | {rmse} | {rho} | {r2} |".format(
                model="component-weighted ridge" if row["model"] == "ridge" else "tied 1-NN",
                endpoint=row["endpoint"],
                mae=_display(row["mae_log10_pm"]),
                macro=_display(row["component_macro_mae_log10_pm"]),
                rmse=_display(row["rmse_log10_pm"]),
                rho=_display(row["spearman_rho"]),
                r2=_display(row["r_squared"]),
            )
        )
    comparison_lines = []
    for row in payload["paired_comparisons"]:  # type: ignore[union-attr]
        comparison_lines.append(
            "| {endpoint} | {ridge} | {nn} | {delta} | [{lower}, {upper}] |".format(
                endpoint=row["endpoint"],
                ridge=_display(row["ridge_mae_log10_pm"]),
                nn=_display(row["nn_mae_log10_pm"]),
                delta=_display(row["mae_delta_log10_pm"]),
                lower=_display(row["ci_lower"]),
                upper=_display(row["ci_upper"]),
            )
        )
    selection_lines = []
    for row in payload["hyperparameter_selections"]:  # type: ignore[union-attr]
        selection_lines.append(
            f"| {row['outer_fold']} | {row['outer_training_records']} | "
            f"{row['outer_training_components']} | {_display(row['selected_alpha'], 4)} |"
        )
    fold_lines = []
    for row in payload["ridge_fold_metrics"]:  # type: ignore[union-attr]
        fold_lines.append(
            "| {fold} | {n} | {gcgr} | {glp1r} | {selectivity} |".format(
                fold=row["outer_fold"],
                n=row["n"],
                gcgr=_display(row["gcgr_mae_log10_pm"]),
                glp1r=_display(row["glp1r_mae_log10_pm"]),
                selectivity=_display(row["selectivity_mae_log10_pm"]),
            )
        )
    return f"""# Nested CPU sequence model

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
{chr(10).join(metric_lines)}

### Paired comparison with tied 1-NN

Delta is `ridge MAE - 1-NN MAE`; negative values favor ridge. Intervals are
percentile intervals from {payload['bootstrap']['resamples']} paired resamples of
the 17 whole sequence components with seed {payload['bootstrap']['seed']}.

| Endpoint | Ridge MAE | 1-NN MAE | Delta | Component-bootstrap 95% interval |
|:---|---:|---:|---:|:---|
{chr(10).join(comparison_lines)}

The ridge model lowers pooled MAE for both receptor potencies, but not for the
derived selectivity ratio. The three endpoints and both pooled and component-macro
summaries are retained; no favorable endpoint was selected after outer-fold
evaluation. With only 17 components and three outer folds, bootstrap intervals are
descriptive uncertainty summaries rather than a definitive hypothesis test.

### Training-only hyperparameter selection

| Outer test fold | Training records | Training components | Selected alpha |
|---:|---:|---:|---:|
{chr(10).join(selection_lines)}

The complete inner-validation curve for every outer fold is stored in the JSON
report. The candidate grid and feature contract are versioned in
`configs/cpu_sequence_model.json`.

### Ridge MAE by outer fold

| Outer fold | n | GCGR | GLP-1R | Selectivity |
|---:|---:|---:|---:|---:|
{chr(10).join(fold_lines)}

Fold variability remains substantial, as expected when entire sequence families
are held out. EC50 is cell-based functional potency—not affinity, Kd, efficacy, or
a structural score. This is an exploratory development-CV comparison. P1–P15 was
prospective in the source study; this repository uses it as a locked retrospective
local-analog external evaluation. Its predictions were generated without outcome
access, and its scoring
policy were subsequently locked and scored once; the mixed result is reported in
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
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", default="data/raw/training_data.xlsx")
    parser.add_argument("--folds", default="data/derived/outer_folds.csv")
    parser.add_argument("--config", default="configs/cpu_sequence_model.json")
    parser.add_argument(
        "--predictions", default="data/derived/sequence_model_oof_predictions.csv"
    )
    parser.add_argument("--metrics-csv", default="reports/cpu_sequence_model_metrics.csv")
    parser.add_argument("--report-json", default="reports/cpu_sequence_model.json")
    parser.add_argument("--report-md", default="reports/CPU_SEQUENCE_MODEL.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _load_config(args.config)
    records = load_training_records(args.training, expected_records=125)
    peptide_folds, peptide_components = _load_assignments(args.folds)
    ridge_result = nested_component_ridge_predictions(
        records,
        peptide_folds,
        peptide_components,
        config["alpha_grid"],
        alphabet=str(config["alphabet"]),
        expected_length=int(config["aligned_length"]),
    )

    nearest_by_id = {
        str(row["peptide_id"]): row
        for row in out_of_fold_predictions(records, peptide_folds)
    }
    rows = [dict(row) for row in ridge_result.rows]
    for row in rows:
        nearest = nearest_by_id[str(row["peptide_id"])]
        for column in (
            "nn_gcgr_log10_ec50_pm",
            "nn_glp1r_log10_ec50_pm",
            "nn_selectivity_log10_ratio",
            "nearest_identity",
            "nearest_tie_count",
            "nearest_donor_ids",
        ):
            row[column] = nearest[column]

    pooled_metrics = _metric_rows(rows)
    paired_comparisons = _comparisons(rows, config["bootstrap"])
    ridge_fold_metrics = _fold_metrics(rows)
    write_csv(args.predictions, rows, PREDICTION_FIELDS)
    write_csv(args.metrics_csv, pooled_metrics, METRIC_FIELDS)

    payload: dict[str, object] = {
        "schema_version": 1,
        "model_id": config["model_id"],
        "endpoint": "cAMP accumulation EC50",
        "unit": "log10(pM)",
        "endpoint_warning": "Functional potency, not binding affinity or efficacy.",
        "training_records": len(records),
        "observed_training_labels": len(records) * 2,
        "censored_training_labels": 0,
        "sequence_components": len(set(peptide_components.values())),
        "feature_count": int(config["aligned_length"]) * len(str(config["alphabet"])),
        "training_sha256": sha256_file(args.training),
        "folds_sha256": sha256_file(args.folds),
        "config_sha256": sha256_file(args.config),
        "holdout_sequences_accessed": False,
        "holdout_labels_accessed": False,
        "censored_values_imputed": 0,
        "model_contract": config,
        "hyperparameter_selections": list(ridge_result.selections),
        "pooled_metrics": pooled_metrics,
        "paired_comparisons": paired_comparisons,
        "ridge_fold_metrics": ridge_fold_metrics,
        "bootstrap": config["bootstrap"],
    }
    report_json = Path(args.report_json)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    Path(args.report_md).write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
