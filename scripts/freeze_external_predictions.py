#!/usr/bin/env python3
"""Freeze P1--P15 predictions using development labels and external sequences only."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from incretinselect.clustering import write_csv
from incretinselect.external_evaluation import (
    PARENT_CLUSTER_FIELDS,
    PREDICTION_FIELDS,
    build_locked_predictions,
    derive_parent_clusters,
)
from incretinselect.holdout import load_design_sequences
from incretinselect.sources import sha256_file
from incretinselect.training import load_training_records

def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _load_components(path: str | Path) -> dict[str, str]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    components: dict[str, str] = {}
    for row in rows:
        peptide_id = row.get("peptide_id", "")
        component = row.get("cluster_id", "")
        if not peptide_id or not component or peptide_id in components:
            raise ValueError("Component table contains a missing or duplicate assignment")
        components[peptide_id] = component
    return components


def _require_hash(path: str | Path, expected: str, label: str) -> str:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"{label} checksum mismatch: expected {expected}, observed {observed}")
    return observed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    # Deliberately no receptor-outcome or prospective-holdout argument exists.
    parser.add_argument("--training", default="data/raw/training_data.xlsx")
    parser.add_argument("--components", default="data/derived/outer_folds.csv")
    parser.add_argument("--sequences", default="data/raw/source_data_fig5.xlsx")
    parser.add_argument("--model-config", default="configs/cpu_sequence_model.json")
    parser.add_argument("--protocol", default="configs/external_evaluation.json")
    parser.add_argument(
        "--predictions", default="data/derived/external_predictions_locked.csv"
    )
    parser.add_argument(
        "--dependency-groups", default="data/derived/external_dependency_groups.csv"
    )
    parser.add_argument(
        "--receipt", default="reports/external_prediction_receipt.json"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    protocol = _load_json(args.protocol)
    model_config = _load_json(args.model_config)
    if protocol.get("schema_version") != 1 or protocol.get("lock_status") != (
        "locked_before_outcome_scoring"
    ):
        raise ValueError("External evaluation protocol is not locked")
    if model_config.get("prospective_holdout_access") != "forbidden":
        raise ValueError("Development model config must forbid holdout access")
    if (
        protocol["label_free_external_components"]["identity_threshold"]
        != protocol["label_free_combined_components"]["identity_threshold"]
    ):
        raise ValueError("External and combined dependency graphs must use one threshold")

    development_hashes = protocol["development_inputs"]
    external_hashes = protocol["external_inputs"]
    preparation_paths = {
        "preparation_script_sha256": Path(__file__),
        "external_evaluation_module_sha256": (
            project_root / "src/incretinselect/external_evaluation.py"
        ),
        "sequence_model_module_sha256": project_root / "src/incretinselect/sequence_model.py",
        "training_module_sha256": project_root / "src/incretinselect/training.py",
        "clustering_module_sha256": project_root / "src/incretinselect/clustering.py",
        "holdout_module_sha256": project_root / "src/incretinselect/holdout.py",
        "baseline_module_sha256": project_root / "src/incretinselect/baseline.py",
    }
    expected_preparation_hashes = protocol["preparation_implementation"]
    verified_preparation_hashes = {
        key: _require_hash(path, expected_preparation_hashes[key], key)
        for key, path in preparation_paths.items()
    }
    verified_inputs = {
        "training": _require_hash(
            args.training, development_hashes["training_sha256"], "training"
        ),
        "outer_folds_with_components": _require_hash(
            args.components,
            development_hashes["outer_folds_with_components_sha256"],
            "outer-fold/component table",
        ),
        "cpu_model_config": _require_hash(
            args.model_config,
            development_hashes["cpu_model_config_sha256"],
            "CPU model config",
        ),
        "design_sequences": _require_hash(
            args.sequences,
            external_hashes["design_sequences_sha256"],
            "P1--P15 design sequences",
        ),
        "external_evaluation_protocol": sha256_file(args.protocol),
        "sequence_model_code": _require_hash(
            project_root / "src/incretinselect/sequence_model.py",
            development_hashes["sequence_model_code_sha256"],
            "development sequence-model implementation",
        ),
        "baseline_code": _require_hash(
            project_root / "src/incretinselect/baseline.py",
            development_hashes["baseline_code_sha256"],
            "development baseline implementation",
        ),
    }

    records = load_training_records(args.training, expected_records=125)
    components = _load_components(args.components)
    sequences = load_design_sequences(args.sequences)
    rows, selected_alpha, inner_scores = build_locked_predictions(
        records,
        components,
        sequences,
        model_config["alpha_grid"],
        alphabet=str(model_config["alphabet"]),
        expected_length=int(model_config["aligned_length"]),
        external_identity_threshold=float(
            protocol["label_free_external_components"]["identity_threshold"]
        ),
    )
    write_csv(args.predictions, rows, list(PREDICTION_FIELDS))
    parent_cluster_rows = derive_parent_clusters(rows)
    write_csv(args.dependency_groups, parent_cluster_rows, list(PARENT_CLUSTER_FIELDS))

    observed_cluster_contract = {
        cluster_id: {
            "members": row["parent_cluster_members"].split(";"),
            "donors": row["parent_donor_ids"].split(";"),
        }
        for cluster_id in sorted({row["parent_cluster_id"] for row in parent_cluster_rows})
        for row in parent_cluster_rows
        if row["parent_cluster_id"] == cluster_id
    }
    expected_cluster_contract = protocol["label_free_parent_clusters"]["expected_clusters"]
    if observed_cluster_contract != expected_cluster_contract:
        raise ValueError("Derived P1--P15 parent clusters differ from the locked contract")
    observed_external_components = {
        component_id: [
            str(row["peptide_id"])
            for row in rows
            if row["external_sequence_component_id"] == component_id
        ]
        for component_id in sorted(
            {str(row["external_sequence_component_id"]) for row in rows}
        )
    }
    expected_external_components = protocol["label_free_external_components"][
        "expected_components"
    ]
    if observed_external_components != expected_external_components:
        raise ValueError("Derived external 0.85 components differ from the locked contract")
    observed_linked_components = {
        linked_id: {
            "members": [
                str(row["peptide_id"])
                for row in rows
                if row["linked_component_id"] == linked_id
            ],
            "development_components": sorted(
                {
                    component
                    for row in rows
                    if row["linked_component_id"] == linked_id
                    for component in str(row["linked_development_component_ids"]).split(";")
                    if component
                }
            ),
        }
        for linked_id in sorted({str(row["linked_component_id"]) for row in rows})
    }
    expected_linked_components = protocol["label_free_combined_components"][
        "expected_components"
    ]
    if observed_linked_components != expected_linked_components:
        raise ValueError("Derived combined components differ from the locked contract")

    payload = {
        "schema_version": 1,
        "receipt_type": "label_free_external_prediction_lock",
        "protocol_id": protocol["protocol_id"],
        "locked_on": protocol["locked_on"],
        "pre_evaluation_commit": protocol["pre_evaluation_commit"],
        "pre_evaluation_tree": protocol["pre_evaluation_tree"],
        "accessed_path_classes": [
            "locked protocol and model configuration",
            "125-record development workbook",
            "frozen development component table",
            "P1--P15 sequence workbook",
            "prediction implementation files",
        ],
        "forbidden_path_classes": [
            "GCGR P1--P15 outcome workbook",
            "GLP-1R P1--P15 outcome workbook",
            "data/derived/prospective_holdout.json",
        ],
        "holdout_sequences_accessed": True,
        "holdout_outcomes_accessed": False,
        "holdout_outcomes_accessed_by_this_command": False,
        "holdout_outcome_cells_read_by_this_command": False,
        "historical_outcome_audit_already_performed": True,
        "public_unblinded_labels": True,
        "outcome_isolation_scope": "prediction-freeze command only",
        "design_workbook_sheet_allowlist": list(
            f"P{index}" for index in range(1, 16)
        ),
        "design_workbook_cells_read_per_sheet": (
            "row 2, columns A:AE; A must equal sheet ID and B:AE encode the "
            "30-position aligned sequence"
        ),
        "outcome_hashes_declared_in_protocol_but_not_verified": {
            "gcgr": external_hashes["gcgr_outcomes_sha256"],
            "glp1r": external_hashes["glp1r_outcomes_sha256"],
        },
        "verified_input_sha256": verified_inputs,
        "implementation_sha256": verified_preparation_hashes,
        "development_records": len(records),
        "development_components": len(set(components.values())),
        "external_predictions": len(rows),
        "external_parent_clusters": len(observed_cluster_contract),
        "external_sequence_components": len(observed_external_components),
        "combined_linked_components": len(observed_linked_components),
        "parent_cluster_derivation": protocol["label_free_parent_clusters"]["derivation"],
        "parent_cluster_contract": observed_cluster_contract,
        "external_sequence_component_contract": observed_external_components,
        "combined_linked_component_contract": observed_linked_components,
        "selected_alpha": selected_alpha,
        "selection_objective": (
            "leave-one-development-component-out macro two-receptor MAE"
        ),
        "inner_scores": inner_scores,
        "prediction_file": str(args.predictions),
        "prediction_sha256": sha256_file(args.predictions),
        "dependency_group_file": str(args.dependency_groups),
        "dependency_group_sha256": sha256_file(args.dependency_groups),
        "model_ids": ["ridge", "nn", "median", "component_mean"],
    }
    receipt_path = Path(args.receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
