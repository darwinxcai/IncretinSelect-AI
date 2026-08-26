import importlib.util
import inspect
import json
import math
import tempfile
import unittest
from pathlib import Path

from incretinselect.external_evaluation import (
    MODEL_IDS,
    PREDICTION_FIELDS,
    ExternalEvaluationError,
    aggregate_replicates,
    build_locked_predictions,
    constraint_absolute_error,
    derive_parent_clusters,
    endpoint_evaluation_rows,
    external_component_paired_bootstrap_delta,
    leave_one_dependency_group_out_delta,
    sha256_path,
    stratified_paired_bootstrap_delta,
    verify_prediction_lock,
)
from incretinselect.holdout import DESIGN_IDS, design_group
from incretinselect.training import TrainingRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def development_record(
    peptide_id: str, sequence: str, gcgr_pm: float, glp1r_pm: float
) -> TrainingRecord:
    return TrainingRecord(peptide_id, sequence.replace("-", ""), sequence, gcgr_pm, glp1r_pm)


def replicate(value: float) -> dict[str, object]:
    return {"status": "observed", "value_pm": value}


def censored(threshold: float) -> dict[str, object]:
    return {"status": "right_censored", "threshold_pm": threshold}


class ExternalEvaluationTests(unittest.TestCase):
    def test_final_alpha_tie_break_and_tied_nn_use_development_only(self) -> None:
        records = [
            development_record("d1", "AAAAAAAAAA", 10.0, 100.0),
            development_record("d2", "AAAAAAAAAT", 10.0, 100.0),
        ]
        external = {peptide_id: "AAAAAAAAAG" for peptide_id in DESIGN_IDS}
        rows, alpha, scores = build_locked_predictions(
            records,
            {"d1": "c1", "d2": "c2"},
            external,
            [10.0, 0.1],
            alphabet="-ACGT",
            expected_length=10,
            external_identity_threshold=0.85,
        )
        self.assertEqual(alpha, 0.1)
        self.assertTrue(all(score["component_macro_two_receptor_mae"] == 0.0 for score in scores))
        self.assertEqual(rows[0]["nearest_tie_count"], 2)
        self.assertEqual(rows[0]["nearest_donor_ids"], "d1;d2")
        self.assertAlmostEqual(float(rows[0]["nn_gcgr_log10_ec50_pm"]), 1.0)
        signature = inspect.signature(build_locked_predictions)
        self.assertFalse(
            {"gcgr_replicates", "glp1r_replicates", "holdout_labels"}
            & set(signature.parameters)
        )

    def test_peptide_aggregate_preserves_right_censoring(self) -> None:
        observation = aggregate_replicates(
            [replicate(100.0), replicate(200.0), censored(300.0)]
        )
        self.assertEqual(observation.status, "lower_bound")
        self.assertAlmostEqual(observation.value_log10_pm, math.log10(200.0))
        self.assertAlmostEqual(
            float(constraint_absolute_error(2.0, observation.status, observation.value_log10_pm)),
            math.log10(2.0),
        )
        self.assertEqual(
            constraint_absolute_error(3.0, observation.status, observation.value_log10_pm),
            0.0,
        )

    def test_selectivity_interval_arithmetic_and_both_censored_exclusion(self) -> None:
        predictions = []
        for peptide_id in DESIGN_IDS:
            row: dict[str, object] = {
                "peptide_id": peptide_id,
                "design_group": design_group(peptide_id),
                "parent_cluster_id": "PC001",
                "external_sequence_component_id": "EC001",
                "linked_component_id": "LC001",
            }
            for model in MODEL_IDS:
                row[f"{model}_gcgr_log10_ec50_pm"] = 0.0
                row[f"{model}_glp1r_log10_ec50_pm"] = 0.0
                row[f"{model}_selectivity_log10_ratio"] = 0.0
            predictions.append(row)
        gcgr = {peptide_id: [replicate(10.0)] * 3 for peptide_id in DESIGN_IDS}
        glp1r = {peptide_id: [replicate(10.0)] * 3 for peptide_id in DESIGN_IDS}
        gcgr["P1"] = [censored(100.0)] * 3
        glp1r["P2"] = [censored(100.0)] * 3
        gcgr["P3"] = [censored(100.0)] * 3
        glp1r["P3"] = [censored(100.0)] * 3

        rows = endpoint_evaluation_rows(predictions, gcgr, glp1r)
        selectivity = {
            row["peptide_id"]: row for row in rows if row["endpoint"] == "selectivity"
        }
        self.assertEqual(selectivity["P1"]["observation_status"], "lower_bound")
        self.assertAlmostEqual(float(selectivity["P1"]["observation_log10_pm_or_bound"]), 1.0)
        self.assertEqual(selectivity["P2"]["observation_status"], "upper_bound")
        self.assertAlmostEqual(float(selectivity["P2"]["observation_log10_pm_or_bound"]), -1.0)
        self.assertEqual(selectivity["P3"]["observation_status"], "uninformative")
        self.assertIsNone(selectivity["P3"]["ridge_constraint_absolute_error"])

    def test_stratified_bootstrap_is_deterministic(self) -> None:
        rows = []
        for index, peptide_id in enumerate(DESIGN_IDS, start=1):
            rows.append(
                {
                    "peptide_id": peptide_id,
                    "design_group": design_group(peptide_id),
                    "parent_cluster_id": (
                        "PC001" if index == 1 else "PC002" if index <= 5 else
                        "PC003" if index <= 10 else "PC004" if index == 11 else "PC005"
                    ),
                    "external_sequence_component_id": (
                        "EC001" if index <= 5 else "EC002" if index <= 10 else
                        "EC003" if index == 11 else "EC004"
                    ),
                    "endpoint": "gcgr",
                    "ridge_constraint_absolute_error": index / 10,
                    "nn_constraint_absolute_error": 1.0,
                }
            )
        first = stratified_paired_bootstrap_delta(
            rows,
            "gcgr",
            resamples=100,
            seed=7,
            confidence_level=0.95,
        )
        second = stratified_paired_bootstrap_delta(
            rows,
            "gcgr",
            resamples=100,
            seed=7,
            confidence_level=0.95,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["n_peptides"], 15)

        component_first = external_component_paired_bootstrap_delta(
            rows,
            "gcgr",
            resamples=100,
            seed=7,
            confidence_level=0.95,
        )
        component_second = external_component_paired_bootstrap_delta(
            rows,
            "gcgr",
            resamples=100,
            seed=7,
            confidence_level=0.95,
        )
        self.assertEqual(component_first, component_second)
        self.assertEqual(component_first["n_dependency_groups"], 4)
        leave_out = leave_one_dependency_group_out_delta(
            rows,
            "gcgr",
            group_field="external_sequence_component_id",
            expected_group_count=4,
        )
        self.assertEqual(len(leave_out["estimates"]), 4)

    def test_parent_cluster_rule_is_permutation_invariant_and_transitive(self) -> None:
        donors = {
            "P1": "d1",
            "P2": "d2",
            "P3": "d2;d3",
            "P4": "d3",
            "P5": "d2",
            **{f"P{index}": "d4" for index in range(6, 11)},
            "P11": "d5",
            **{f"P{index}": "d6" for index in range(12, 16)},
        }
        rows = [
            {"peptide_id": peptide_id, "nearest_donor_ids": donors[peptide_id]}
            for peptide_id in DESIGN_IDS
        ]
        first = derive_parent_clusters(rows)
        second = derive_parent_clusters(list(reversed(rows)))
        self.assertEqual(first, second)
        cluster_by_id = {row["peptide_id"]: row["parent_cluster_id"] for row in first}
        self.assertEqual(
            {cluster_by_id[peptide_id] for peptide_id in ("P2", "P3", "P4", "P5")},
            {"PC002"},
        )
        p3 = next(row for row in first if row["peptide_id"] == "P3")
        self.assertEqual(p3["parent_donor_ids"], "d2;d3")

    def test_prediction_receipt_rejects_file_or_protocol_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            prediction = root / "predictions.csv"
            receipt = root / "receipt.json"
            protocol.write_text("{}\n", encoding="utf-8")
            prediction.write_text("peptide_id\nP1\n", encoding="utf-8")
            receipt.write_text(
                json.dumps(
                    {
                        "receipt_type": "label_free_external_prediction_lock",
                        "holdout_outcomes_accessed": False,
                        "prediction_sha256": sha256_path(prediction),
                        "verified_input_sha256": {
                            "external_evaluation_protocol": sha256_path(protocol)
                        },
                    }
                ),
                encoding="utf-8",
            )
            verify_prediction_lock(receipt, prediction, protocol)
            prediction.write_text("peptide_id\nP2\n", encoding="utf-8")
            with self.assertRaises(ExternalEvaluationError):
                verify_prediction_lock(receipt, prediction, protocol)
            prediction.write_text("peptide_id\nP1\n", encoding="utf-8")
            protocol.write_text('{"changed": true}\n', encoding="utf-8")
            with self.assertRaises(ExternalEvaluationError):
                verify_prediction_lock(receipt, prediction, protocol)

    def test_prediction_schema_is_outcome_free(self) -> None:
        forbidden = ("actual", "outcome", "observed", "error", "loss", "label")
        self.assertFalse(
            [field for field in PREDICTION_FIELDS if any(token in field for token in forbidden)]
        )

    def test_preparation_cli_has_no_outcome_path(self) -> None:
        script = PROJECT_ROOT / "scripts/freeze_external_predictions.py"
        specification = importlib.util.spec_from_file_location(
            "freeze_external_predictions", script
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        destinations = {action.dest for action in module.build_parser()._actions}
        self.assertFalse(
            {"gcgr", "glp1r", "outcomes", "labels", "holdout"} & destinations
        )


if __name__ == "__main__":
    unittest.main()
