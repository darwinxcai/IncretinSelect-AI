#!/usr/bin/env python3
"""Score the frozen P1--P15 predictions once under the locked censoring policy."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from incretinselect.clustering import write_csv
from incretinselect.external_evaluation import (
    MODEL_IDS,
    PREDICTION_FIELDS,
    complete_case_metrics,
    dependency_group_macro_delta,
    derive_external_sequence_components,
    derive_parent_clusters,
    endpoint_evaluation_rows,
    external_component_paired_bootstrap_delta,
    group_loss_summaries,
    leave_one_dependency_group_out_delta,
    leave_one_parent_cluster_out_delta,
    parent_cluster_paired_bootstrap_delta,
    replicate_sensitivity_rows,
    sha256_path,
    stratified_paired_bootstrap_delta,
    summarize_endpoint_losses,
    verify_prediction_lock,
)
from incretinselect.holdout import DESIGN_IDS, design_group, load_receptor_replicates

ENDPOINT_FIELDS = [
    "peptide_id",
    "design_group",
    "parent_cluster_id",
    "external_sequence_component_id",
    "linked_component_id",
    "endpoint",
    "observation_status",
    "observation_log10_pm_or_bound",
    "observed_replicates",
    "right_censored_replicates",
] + [
    field
    for model in MODEL_IDS
    for field in (f"{model}_prediction", f"{model}_constraint_absolute_error")
]
REPLICATE_FIELDS = [
    "peptide_id",
    "design_group",
    "parent_cluster_id",
    "external_sequence_component_id",
    "linked_component_id",
    "receptor",
    "replicate",
    "observation_status",
    "observation_log10_pm_or_bound",
] + [
    field
    for model in MODEL_IDS
    for field in (f"{model}_prediction", f"{model}_constraint_absolute_error")
]
METRIC_FIELDS = [
    "model",
    "endpoint",
    "n_informative",
    "constraint_mae_lower_bound",
    "exact_complete_n",
    "exact_complete_mae_log10_pm",
    "bound_constraints",
    "bound_satisfaction_rate",
]


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _require_hash(path: str | Path, expected: str, label: str) -> str:
    observed = sha256_path(path)
    if observed != expected:
        raise ValueError(f"{label} checksum mismatch: expected {expected}, observed {observed}")
    return observed


def _git_lock(lock_commit: str, project_root: Path) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != lock_commit:
        raise ValueError(f"Scoring must run at lock commit {lock_commit}; observed {head}")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("Scoring requires a clean worktree at the committed prediction lock")


def _load_predictions(path: str | Path, selected_alpha: float) -> list[dict[str, object]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PREDICTION_FIELDS:
            raise ValueError("Prediction columns differ from the locked label-free schema")
        forbidden = ("actual", "outcome", "observed", "error", "loss", "label")
        if any(token in field.lower() for field in reader.fieldnames or () for token in forbidden):
            raise ValueError("Prediction CSV contains a forbidden outcome-bearing column")
        rows = list(reader)
    if len(rows) != 15 or {row["peptide_id"] for row in rows} != set(DESIGN_IDS):
        raise ValueError("Prediction CSV must contain exactly one row for P1--P15")
    numeric_fields = [
        field
        for field in PREDICTION_FIELDS
        if field
        not in {
            "peptide_id",
            "design_group",
            "parent_cluster_id",
            "external_sequence_component_id",
            "nearest_development_component_ids",
            "linked_component_id",
            "linked_development_component_ids",
            "aligned_sequence",
            "nearest_donor_ids",
        }
    ]
    parsed: list[dict[str, object]] = []
    for row in rows:
        peptide_id = row["peptide_id"]
        if row["design_group"] != design_group(peptide_id):
            raise ValueError(f"Unexpected design group for {peptide_id}")
        converted: dict[str, object] = dict(row)
        for field in numeric_fields:
            converted[field] = float(row[field])
        if float(converted["selected_alpha"]) != selected_alpha:
            raise ValueError("Prediction alpha differs from its preparation receipt")
        parsed.append(converted)
    return sorted(parsed, key=lambda row: int(str(row["peptide_id"])[1:]))


def _verify_dependency_groups(
    predictions: list[dict[str, object]], protocol: dict[str, Any]
) -> None:
    parent_rows = derive_parent_clusters(predictions)
    parent_contract = {
        cluster_id: {
            "members": row["parent_cluster_members"].split(";"),
            "donors": row["parent_donor_ids"].split(";"),
        }
        for cluster_id in sorted({row["parent_cluster_id"] for row in parent_rows})
        for row in parent_rows
        if row["parent_cluster_id"] == cluster_id
    }
    if parent_contract != protocol["label_free_parent_clusters"]["expected_clusters"]:
        raise ValueError("Prediction parent clusters differ from the locked protocol")
    parent_by_id = {row["peptide_id"]: row["parent_cluster_id"] for row in parent_rows}
    if any(
        row["parent_cluster_id"] != parent_by_id[row["peptide_id"]]
        for row in predictions
    ):
        raise ValueError("Prediction parent-cluster IDs are inconsistent with tied donors")

    threshold = float(protocol["label_free_external_components"]["identity_threshold"])
    external_contract = derive_external_sequence_components(predictions, threshold)
    if external_contract != protocol["label_free_external_components"]["expected_components"]:
        raise ValueError("External sequence components differ from the locked protocol")
    external_by_id = {
        peptide_id: component_id
        for component_id, members in external_contract.items()
        for peptide_id in members
    }
    if any(
        row["external_sequence_component_id"] != external_by_id[row["peptide_id"]]
        for row in predictions
    ):
        raise ValueError("Prediction external-component IDs are inconsistent with sequences")

    expected_linked = protocol["label_free_combined_components"]["expected_components"]
    linked_by_id = {
        peptide_id: (linked_id, payload["development_components"])
        for linked_id, payload in expected_linked.items()
        for peptide_id in payload["members"]
    }
    for row in predictions:
        linked_id, development_components = linked_by_id[row["peptide_id"]]
        if row["linked_component_id"] != linked_id or str(
            row["linked_development_component_ids"]
        ).split(";") != development_components:
            raise ValueError("Prediction linked-component provenance differs from protocol")


def _constraint_metric_rows(
    rows: list[dict[str, object]],
    losses: list[dict[str, object]],
    exact_metrics: list[dict[str, object]],
) -> list[dict[str, object]]:
    loss_by_key = {(row["model"], row["endpoint"]): row for row in losses}
    exact_by_key = {(row["model"], row["endpoint"]): row for row in exact_metrics}
    result: list[dict[str, object]] = []
    for model in MODEL_IDS:
        for endpoint in ("gcgr", "glp1r", "selectivity"):
            endpoint_rows = [row for row in rows if row["endpoint"] == endpoint]
            bound_rows = [
                row
                for row in endpoint_rows
                if row["observation_status"] in {"lower_bound", "upper_bound"}
            ]
            satisfied = sum(
                float(row[f"{model}_constraint_absolute_error"]) == 0.0
                for row in bound_rows
            )
            loss = loss_by_key[(model, endpoint)]
            exact = exact_by_key.get((model, endpoint))
            result.append(
                {
                    "model": model,
                    "endpoint": endpoint,
                    "n_informative": loss["n"],
                    "constraint_mae_lower_bound": loss["value"],
                    "exact_complete_n": exact["n"] if exact else 0,
                    "exact_complete_mae_log10_pm": exact["mae_log10_pm"] if exact else None,
                    "bound_constraints": len(bound_rows),
                    "bound_satisfaction_rate": (
                        satisfied / len(bound_rows) if bound_rows else None
                    ),
                }
            )
    return result


def _replicate_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for model in MODEL_IDS:
        for receptor in ("gcgr", "glp1r"):
            receptor_rows = [row for row in rows if row["receptor"] == receptor]
            losses = [float(row[f"{model}_constraint_absolute_error"]) for row in receptor_rows]
            summaries.append(
                {
                    "model": model,
                    "receptor": receptor,
                    "replicate_cells": len(losses),
                    "constraint_mae_lower_bound": statistics.fmean(losses),
                    "independence_warning": (
                        "Three cells per peptide are repeated assay replicates, "
                        "not independent units."
                    ),
                }
            )
    return summaries


def _fmt(value: object, decimals: int = 3) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _markdown(payload: dict[str, Any]) -> str:
    metric_lines = []
    for row in payload["primary_and_interval_metrics"]:
        metric_lines.append(
            (
                "| {model} | {endpoint} | {n} | {loss} | {exact_n} | "
                "{exact_mae} | {bounds} | {sat} |"
            ).format(
                model=row["model"],
                endpoint=row["endpoint"],
                n=row["n_informative"],
                loss=_fmt(row["constraint_mae_lower_bound"]),
                exact_n=row["exact_complete_n"],
                exact_mae=_fmt(row["exact_complete_mae_log10_pm"]),
                bounds=row["bound_constraints"],
                sat=_fmt(row["bound_satisfaction_rate"]),
            )
        )
    comparison_lines = []
    for row in payload["headline_external_component_resampling"]:
        comparison_lines.append(
            "| {endpoint} | {challenger} - {baseline} | {delta} | [{lower}, {upper}] |".format(
                endpoint=row["endpoint"],
                challenger=row["challenger"],
                baseline=row["baseline"],
                delta=_fmt(row["mae_delta_log10_pm"]),
                lower=_fmt(row["interval_lower"]),
                upper=_fmt(row["interval_upper"]),
            )
        )
    leave_out_lines = []
    for row in payload["leave_one_external_component_out"]:
        leave_out_lines.append(
            "| {endpoint} | {minimum} | {maximum} |".format(
                endpoint=row["endpoint"],
                minimum=_fmt(row["minimum_leave_one_group_out_delta"]),
                maximum=_fmt(row["maximum_leave_one_group_out_delta"]),
            )
        )
    status_counts = payload["observation_status_counts"]
    return f"""# One-shot P1--P15 external evaluation

**Status:** completed once from the prediction-lock commit
`{payload['prediction_lock_commit']}`. The label-freeze command accepted no
receptor-outcome inputs and read only the P1--P15 sequence cells. Those predictions
were committed before this separate scoring command read the receptor outcomes.
The public labels were historically parsed for integrity audits, so this is
command-local isolation—not blinded or virgin-label evaluation. The model was not
refit, recalibrated, or selected after this result.

## What was tested

The final component-balanced ridge model was trained on all 125 development
peptides after selecting alpha={_fmt(payload['selected_alpha'], 4)} by the locked
leave-one-development-component-out rule. P1--P15 are nearby designed analogues
(not a distant-family panel), and their labels are public; this is a retrospective
one-shot external evaluation, not a blinded prospective experiment.

The endpoint is cAMP EC50 functional potency in pM—not binding affinity, Kd,
efficacy, or clinical performance. Three assay replicates were collapsed to one
peptide-level receptor observation. Exact triplicates use log10 of the arithmetic
mean. Any right-censored replicate produces a lower bound on that arithmetic mean;
the reported constraint loss is therefore an optimistic lower bound on absolute
error, not an exact error.

Observation statuses: `{status_counts}`.

## Results

| Model | Endpoint | Informative n | Constraint MAE lower bound | Exact-only n | Exact-only MAE | Bounds | Bound satisfaction |
|:---|:---|---:|---:|---:|---:|---:|---:|
{chr(10).join(metric_lines)}

`ridge` is the locked model; tied `nn` is its primary comparator. `median` is the
existing all-development-row receptor median. `component_mean` is a separately
named component-balanced intercept. Exact-only point metrics are descriptive
because censoring makes that subset non-random.

### Paired comparisons

Delta is challenger loss minus comparator loss; negative favors the challenger.
The headline descriptive interval uses 10,000 paired resamples of the four frozen
P1--P15 sequence components at aligned identity 0.85. A sampled component retains
all member peptides, and the same seed and component draws are used for every model
comparison. This is not an inferential confidence interval. Four components are
too few for a significance or superiority claim, regardless of interval position.
The designs share a model-guided design process, so dependence may remain even
across these four components.

| Endpoint | Comparison | Delta | 95% descriptive resampling interval |
|:---|:---|---:|:---|
{chr(10).join(comparison_lines)}

For the primary ridge-versus-1-NN comparison, all four leave-one-external-component-
out estimates are retained. The range—not a p-value—is a direct stability check.

| Endpoint | Minimum leave-one-component-out delta | Maximum delta |
|:---|---:|---:|
{chr(10).join(leave_out_lines)}

The receipt also retains three dependence sensitivities: five shared-nearest-donor
parent proxies, a deliberately naive 15-peptide design-group-stratified bootstrap,
and three combined development/external linked components summarized by macro and
leave-one-linked-component-out deltas. The naive peptide interval is expected to
be anti-conservative. The receipt classifies direction stability only across the
three group-macro contrasts; every leave-one-group-out estimate and range remains
separate and must be inspected rather than folded into that classifier.

Selectivity is GCGR log10(mean EC50) minus GLP-1R log10(mean EC50). When one
receptor is censored, interval arithmetic gives a one-sided selectivity bound;
when both are censored, the record is uninformative and excluded from selectivity
constraint loss. No censored threshold is treated as an exact outcome.

## Interpretation boundary

This result tests whether a simple sequence model transfers to 15 local analogues
designed from the same source dataset. It does not establish distant sequence-family
generalization, structure-aware causality, receptor binding affinity, or superiority
to the source paper's CNN—or even model superiority within this four-component
panel. All receptor endpoints, intended design groups,
comparators, censoring cases, and negative results are retained.

Machine-readable aggregate metrics are in
`reports/external_evaluation_metrics.csv`; the complete receipt, exact-only metrics,
group summaries, sensitivity analysis, hashes, and bootstrap output are in
`reports/external_evaluation_receipt.json`.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-commit", required=True)
    parser.add_argument("--protocol", default="configs/external_evaluation.json")
    parser.add_argument(
        "--prediction-receipt", default="reports/external_prediction_receipt.json"
    )
    parser.add_argument(
        "--predictions", default="data/derived/external_predictions_locked.csv"
    )
    parser.add_argument(
        "--dependency-groups", default="data/derived/external_dependency_groups.csv"
    )
    parser.add_argument("--gcgr", default="data/raw/gcgr_prospective_ec50.xlsx")
    parser.add_argument("--glp1r", default="data/raw/glp1r_prospective_ec50.xlsx")
    parser.add_argument(
        "--endpoint-records", default="data/derived/external_evaluation_records.csv"
    )
    parser.add_argument(
        "--replicate-records",
        default="data/derived/external_evaluation_replicate_sensitivity.csv",
    )
    parser.add_argument(
        "--metrics", default="reports/external_evaluation_metrics.csv"
    )
    parser.add_argument(
        "--receipt", default="reports/external_evaluation_receipt.json"
    )
    parser.add_argument("--report", default="reports/EXTERNAL_EVALUATION.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    _git_lock(args.lock_commit, project_root)

    protocol = _load_json(args.protocol)
    prediction_receipt = verify_prediction_lock(
        args.prediction_receipt, args.predictions, args.protocol
    )
    if protocol.get("protocol_id") != prediction_receipt.get("protocol_id"):
        raise ValueError("Protocol ID differs from prediction receipt")

    dependency_paths = {
        "external_evaluation_module_sha256": (
            project_root / "src/incretinselect/external_evaluation.py"
        ),
        "sequence_model_module_sha256": project_root / "src/incretinselect/sequence_model.py",
        "training_module_sha256": project_root / "src/incretinselect/training.py",
        "clustering_module_sha256": project_root / "src/incretinselect/clustering.py",
        "holdout_module_sha256": project_root / "src/incretinselect/holdout.py",
        "baseline_module_sha256": project_root / "src/incretinselect/baseline.py",
    }
    preparation_paths = {
        "preparation_script_sha256": project_root / "scripts/freeze_external_predictions.py",
        **dependency_paths,
    }
    preparation_hashes = prediction_receipt["implementation_sha256"]
    for key, path in preparation_paths.items():
        _require_hash(path, preparation_hashes[key], f"locked preparation dependency {key}")

    scoring_paths = {
        "scoring_script_sha256": Path(__file__),
        **dependency_paths,
    }
    scoring_hashes = protocol["scoring_implementation"]
    for key, path in scoring_paths.items():
        _require_hash(path, scoring_hashes[key], f"locked scoring dependency {key}")

    _require_hash(
        args.dependency_groups,
        prediction_receipt["dependency_group_sha256"],
        "label-free dependency-group table",
    )
    predictions = _load_predictions(
        args.predictions, float(prediction_receipt["selected_alpha"])
    )
    _verify_dependency_groups(predictions, protocol)

    # Receptor outcome files are not opened until every prediction, protocol,
    # implementation, and label-free dependency-group lock has passed.
    external_hashes = protocol["external_inputs"]
    outcome_hashes = {
        "gcgr": _require_hash(
            args.gcgr, external_hashes["gcgr_outcomes_sha256"], "GCGR outcomes"
        ),
        "glp1r": _require_hash(
            args.glp1r, external_hashes["glp1r_outcomes_sha256"], "GLP-1R outcomes"
        ),
    }
    gcgr = load_receptor_replicates(args.gcgr, "GCGR")
    glp1r = load_receptor_replicates(args.glp1r, "GLP-1R")
    endpoint_rows = endpoint_evaluation_rows(predictions, gcgr, glp1r)
    replicate_rows = replicate_sensitivity_rows(predictions, gcgr, glp1r)
    write_csv(args.endpoint_records, endpoint_rows, ENDPOINT_FIELDS)
    write_csv(args.replicate_records, replicate_rows, REPLICATE_FIELDS)

    loss_summaries = summarize_endpoint_losses(endpoint_rows)
    exact_metrics = complete_case_metrics(endpoint_rows)
    metrics = _constraint_metric_rows(endpoint_rows, loss_summaries, exact_metrics)
    write_csv(args.metrics, metrics, METRIC_FIELDS)

    bootstrap = protocol["primary_scoring"]
    headline_comparisons = []
    parent_proxy_comparisons = []
    naive_peptide_comparisons = []
    for endpoint in ("gcgr", "glp1r"):
        for baseline in ("nn", "median", "component_mean"):
            headline_comparisons.append(
                external_component_paired_bootstrap_delta(
                    endpoint_rows,
                    endpoint,
                    challenger="ridge",
                    baseline=baseline,
                    resamples=10000,
                    seed=int(bootstrap["bootstrap_seed"]),
                    confidence_level=float(bootstrap["confidence_level"]),
                )
            )
            parent_proxy_comparisons.append(
                parent_cluster_paired_bootstrap_delta(
                    endpoint_rows,
                    endpoint,
                    challenger="ridge",
                    baseline=baseline,
                    resamples=10000,
                    seed=int(bootstrap["bootstrap_seed"]),
                    confidence_level=float(bootstrap["confidence_level"]),
                )
            )
            naive_peptide_comparisons.append(
                stratified_paired_bootstrap_delta(
                    endpoint_rows,
                    endpoint,
                    challenger="ridge",
                    baseline=baseline,
                    resamples=10000,
                    seed=int(bootstrap["bootstrap_seed"]),
                    confidence_level=float(bootstrap["confidence_level"]),
                )
            )

    leave_external = [
        leave_one_dependency_group_out_delta(
            endpoint_rows,
            endpoint,
            group_field="external_sequence_component_id",
            expected_group_count=4,
        )
        for endpoint in ("gcgr", "glp1r")
    ]
    leave_parent = [
        leave_one_parent_cluster_out_delta(endpoint_rows, endpoint)
        for endpoint in ("gcgr", "glp1r")
    ]
    leave_linked = [
        leave_one_dependency_group_out_delta(
            endpoint_rows,
            endpoint,
            group_field="linked_component_id",
            expected_group_count=3,
        )
        for endpoint in ("gcgr", "glp1r")
    ]
    dependence_macro = [
        dependency_group_macro_delta(
            endpoint_rows,
            endpoint,
            group_field=group_field,
            expected_group_count=group_count,
        )
        for endpoint in ("gcgr", "glp1r")
        for group_field, group_count in (
            ("external_sequence_component_id", 4),
            ("parent_cluster_id", 5),
            ("linked_component_id", 3),
        )
    ]
    dependence_stability = []
    for endpoint in ("gcgr", "glp1r"):
        endpoint_macros = [
            row for row in dependence_macro if row["endpoint"] == endpoint
        ]
        directions = {
            1 if float(row["macro_mae_delta_log10_pm"]) > 0 else -1
            if float(row["macro_mae_delta_log10_pm"]) < 0
            else 0
            for row in endpoint_macros
        }
        dependence_stability.append(
            {
                "endpoint": endpoint,
                "direction_stable_across_group_macros": len(directions) == 1,
                "directions": sorted(directions),
                "classification": (
                    "direction-stable but descriptive"
                    if len(directions) == 1
                    else "dependence-unstable"
                ),
            }
        )

    status_counts = Counter(
        f"{row['endpoint']}:{row['observation_status']}" for row in endpoint_rows
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "receipt_type": "one_shot_external_evaluation",
        "protocol_id": protocol["protocol_id"],
        "prediction_lock_commit": args.lock_commit,
        "pre_evaluation_commit": protocol["pre_evaluation_commit"],
        "prediction_receipt_sha256": sha256_path(args.prediction_receipt),
        "prediction_sha256": sha256_path(args.predictions),
        "dependency_group_table_sha256": sha256_path(args.dependency_groups),
        "protocol_sha256": sha256_path(args.protocol),
        "outcome_sha256": outcome_hashes,
        "preparation_implementation_sha256": preparation_hashes,
        "scoring_implementation_sha256": scoring_hashes,
        "outcomes_accessed": True,
        "historical_outcome_audit_already_performed": True,
        "public_unblinded_labels": True,
        "isolation_scope": "prediction-freeze and scoring commands were separated by a commit",
        "model_refit_after_outcomes": False,
        "hyperparameters_changed_after_outcomes": False,
        "censored_thresholds_imputed_as_exact": False,
        "selected_alpha": prediction_receipt["selected_alpha"],
        "external_peptides": 15,
        "external_sequence_components": 4,
        "nearest_donor_parent_proxies": 5,
        "combined_linked_components": 3,
        "endpoint_peptide_records": 30,
        "replicate_cells": 90,
        "observation_status_counts": dict(sorted(status_counts.items())),
        "primary_and_interval_metrics": metrics,
        "headline_external_component_resampling": headline_comparisons,
        "leave_one_external_component_out": leave_external,
        "nearest_parent_proxy_resampling_sensitivity": parent_proxy_comparisons,
        "leave_one_parent_proxy_out_sensitivity": leave_parent,
        "naive_stratified_peptide_bootstrap_sensitivity": naive_peptide_comparisons,
        "leave_one_combined_linked_component_out_sensitivity": leave_linked,
        "dependence_group_macro_sensitivity": dependence_macro,
        "dependence_definition_stability": dependence_stability,
        "exact_complete_case_point_metrics": exact_metrics,
        "ridge_intended_group_summaries": group_loss_summaries(endpoint_rows),
        "replicate_cell_sensitivity": _replicate_summaries(replicate_rows),
        "local_detail_artifact_sha256": {
            "endpoint_records": sha256_path(args.endpoint_records),
            "replicate_records": sha256_path(args.replicate_records),
        },
        "release_artifact_sha256": {
            "metrics_csv": sha256_path(args.metrics),
        },
        "claim_boundary": (
            "Retrospective public-label evaluation on local designed analogues; not blinded, "
            "prospective in this project, distant-family generalization, binding affinity, "
            "or a comparison with the source paper's CNN."
        ),
    }
    receipt_path = Path(args.receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
