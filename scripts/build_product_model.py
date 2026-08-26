#!/usr/bin/env python3
"""Build the portable frozen ridge artifact from checksum-verified source data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from incretinselect.sequence_model import (
    encode_aligned_sequences,
    fit_component_weighted_ridge,
    select_alpha_leave_one_component_out,
)
from incretinselect.sources import sha256_file
from incretinselect.training import load_training_records


def _json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _components(path: str | Path) -> dict[str, str]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, str] = {}
    for row in rows:
        peptide_id = str(row.get("peptide_id", ""))
        component_id = str(row.get("cluster_id", ""))
        if not peptide_id or not component_id or peptide_id in result:
            raise ValueError("Component table has missing or duplicate assignments")
        result[peptide_id] = component_id
    return result


def _metrics(path: str | Path) -> dict[str, dict[str, float]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    endpoint_keys = {
        "GCGR log10 EC50 (pM)": "gcgr",
        "GLP-1R log10 EC50 (pM)": "glp1r",
        "selectivity log10 ratio": "selectivity",
    }
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        if row.get("model") != "ridge" or row.get("endpoint") not in endpoint_keys:
            continue
        key = endpoint_keys[str(row["endpoint"])]
        mae = float(row["mae_log10_pm"])
        result[key] = {
            "development_oof_mae_log10": mae,
            "development_oof_geometric_fold_error": 10.0**mae,
        }
    if set(result) != set(endpoint_keys.values()):
        raise ValueError("Could not find all ridge benchmark endpoints")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", default="data/raw/training_data.xlsx")
    parser.add_argument("--components", default="data/derived/outer_folds.csv")
    parser.add_argument("--config", default="configs/cpu_sequence_model.json")
    parser.add_argument("--metrics", default="reports/cpu_sequence_model_metrics.csv")
    parser.add_argument("--prediction-receipt", default="reports/external_prediction_receipt.json")
    parser.add_argument(
        "--output",
        default="src/incretinselect/assets/incretin_ridge_v1.json",
    )
    parser.add_argument(
        "--receipt",
        default="reports/product_model_receipt.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _json(args.config)
    prediction_receipt = _json(args.prediction_receipt)
    expected_hashes = prediction_receipt.get("verified_input_sha256", {})
    observed_hashes = {
        "training": sha256_file(args.training),
        "outer_folds_with_components": sha256_file(args.components),
        "cpu_model_config": sha256_file(args.config),
    }
    for key, observed in observed_hashes.items():
        expected = expected_hashes.get(key)
        if not expected or observed != expected:
            raise ValueError(f"{key} checksum mismatch: expected {expected}, observed {observed}")

    records = sorted(load_training_records(args.training, expected_records=125), key=lambda x: x.peptide_id)
    components = _components(args.components)
    if {record.peptide_id for record in records} != set(components):
        raise ValueError("Component assignments do not exactly match training records")

    alphabet = str(config["alphabet"])
    aligned_length = int(config["aligned_length"])
    features = encode_aligned_sequences(
        [record.aligned_sequence for record in records],
        alphabet=alphabet,
        expected_length=aligned_length,
    )
    targets = np.asarray(
        [
            [record.gcgr_log10_ec50_pm, record.glp1r_log10_ec50_pm]
            for record in records
        ],
        dtype=float,
    )
    component_ids = [components[record.peptide_id] for record in records]
    selected_alpha, inner_scores = select_alpha_leave_one_component_out(
        features,
        targets,
        component_ids,
        config["alpha_grid"],
    )
    receipt_alpha = float(prediction_receipt["selected_alpha"])
    if selected_alpha != receipt_alpha:
        raise ValueError(
            f"Selected alpha {selected_alpha} does not match prediction lock {receipt_alpha}"
        )
    fitted = fit_component_weighted_ridge(
        features,
        targets,
        component_ids,
        selected_alpha,
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact_id": "incretinselect_aligned_ridge_v1",
        "artifact_version": "1.0.0",
        "created_on": "2026-08-20",
        "endpoint": {
            "assay": "cell-based cAMP accumulation",
            "targets": ["GCGR log10 EC50 (pM)", "GLP-1R log10 EC50 (pM)"],
            "warning": (
                "Functional potency only; not binding affinity, efficacy, safety, or "
                "clinical activity."
            ),
        },
        "input_contract": {
            "alphabet": alphabet,
            "aligned_length": aligned_length,
            "representation": "30-column aligned natural-amino-acid sequence",
            "alignment_policy": (
                "Input must already be aligned. Product code must not infer alignment, "
                "trim residues, or encode noncanonical chemistry."
            ),
        },
        "model": {
            "type": "component-weighted multi-output ridge regression",
            "selected_alpha": selected_alpha,
            "target_order": ["gcgr_log10_ec50_pm", "glp1r_log10_ec50_pm"],
            "feature_mean": fitted.feature_mean.tolist(),
            "target_mean": fitted.target_mean.tolist(),
            "coefficients": fitted.coefficients.tolist(),
        },
        "applicability_reference": {
            "labels_included": False,
            "identity_definition": (
                "Aligned identity over the 30 columns, excluding columns that are gap "
                "in both sequences."
            ),
            "sequences": [
                {
                    "peptide_id": record.peptide_id,
                    "component_id": components[record.peptide_id],
                    "aligned_sequence": record.aligned_sequence,
                }
                for record in records
            ],
        },
        "benchmark_context": {
            "development_records": 125,
            "development_sequence_components": 17,
            "metrics": _metrics(args.metrics),
            "metric_note": (
                "Development out-of-fold MAE is population-level benchmark context, not "
                "an individual prediction interval."
            ),
            "external_evaluation": (
                "Mixed result on 15 published designs: the GCGR point error was lower but "
                "its dependence-aware interval crossed zero, while pooled GLP-1R error "
                "was worse versus tied 1-NN; no overall superiority."
            ),
        },
        "provenance": {
            "primary_source": (
                "Puszkarska et al., Nature Chemistry (2024), "
                "doi:10.1038/s41557-024-01532-x"
            ),
            "upstream_data_license": "CC BY 4.0",
            "training_sha256": observed_hashes["training"],
            "components_sha256": observed_hashes["outer_folds_with_components"],
            "config_sha256": observed_hashes["cpu_model_config"],
            "external_prediction_lock_sha256": sha256_file(
                "data/derived/external_predictions_locked.csv"
            ),
            "fit_contract": (
                "All 125 development records, component-balanced weights, ridge alpha "
                "selected by leave-one-development-component-out two-receptor MAE."
            ),
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    artifact_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    receipt = {
        "schema_version": 1,
        "artifact": str(output),
        "artifact_sha256": artifact_hash,
        "artifact_id": payload["artifact_id"],
        "artifact_version": payload["artifact_version"],
        "source_sha256": observed_hashes,
        "selected_alpha": selected_alpha,
        "inner_scores": inner_scores,
        "portable_without_raw_workbooks": True,
        "contains_reference_activity_labels": False,
    }
    receipt_path = Path(args.receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
