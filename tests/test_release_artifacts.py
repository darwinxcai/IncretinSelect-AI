import csv
import hashlib
import json
import math
import unittest
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleaseArtifactTests(unittest.TestCase):
    def test_frozen_fold_table_is_complete_and_balanced(self) -> None:
        with (PROJECT_ROOT / "data/derived/outer_folds.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 125)
        self.assertEqual(len({row["peptide_id"] for row in rows}), 125)
        sizes = Counter(int(row["outer_fold"]) for row in rows)
        self.assertEqual(sizes, {1: 42, 2: 42, 3: 41})
        cluster_folds: dict[str, set[str]] = {}
        for row in rows:
            cluster_folds.setdefault(row["cluster_id"], set()).add(row["outer_fold"])
        self.assertTrue(all(len(folds) == 1 for folds in cluster_folds.values()))

    def test_baseline_metric_table_has_six_finite_rows(self) -> None:
        with (PROJECT_ROOT / "reports/cpu_baseline_metrics.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 6)
        self.assertEqual({row["model"] for row in rows}, {"median", "nn"})
        for row in rows:
            self.assertEqual(int(row["n"]), 125)
            for column in ("mae_log10_pm", "rmse_log10_pm", "spearman_rho"):
                self.assertTrue(math.isfinite(float(row[column])))

    def test_sequence_model_artifacts_are_complete(self) -> None:
        with (PROJECT_ROOT / "reports/cpu_sequence_model_metrics.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            metrics = list(csv.DictReader(handle))
        self.assertEqual(len(metrics), 6)
        self.assertEqual({row["model"] for row in metrics}, {"nn", "ridge"})
        with (PROJECT_ROOT / "data/derived/sequence_model_oof_predictions.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            predictions = list(csv.DictReader(handle))
        self.assertEqual(len(predictions), 125)
        self.assertEqual(len({row["peptide_id"] for row in predictions}), 125)
        self.assertEqual(len({row["cluster_id"] for row in predictions}), 17)
        self.assertEqual({float(row["selected_alpha"]) for row in predictions}, {1.0, 10.0})

    def test_external_prediction_lock_has_label_free_dependency_groups(self) -> None:
        with (PROJECT_ROOT / "data/derived/external_predictions_locked.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            predictions = list(csv.DictReader(handle))
        self.assertEqual(len(predictions), 15)
        self.assertEqual(
            {row["peptide_id"] for row in predictions},
            {f"P{i}" for i in range(1, 16)},
        )
        self.assertEqual(
            sorted(Counter(row["parent_cluster_id"] for row in predictions).values()),
            [1, 1, 4, 4, 5],
        )
        self.assertEqual(
            sorted(Counter(row["external_sequence_component_id"] for row in predictions).values()),
            [1, 4, 5, 5],
        )
        self.assertEqual(
            sorted(Counter(row["linked_component_id"] for row in predictions).values()),
            [1, 4, 10],
        )
        with (PROJECT_ROOT / "data/derived/external_dependency_groups.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            dependency_rows = list(csv.DictReader(handle))
        self.assertEqual(len(dependency_rows), 15)
        receipt = json.loads(
            (PROJECT_ROOT / "reports/external_prediction_receipt.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(receipt["holdout_outcomes_accessed_by_this_command"])
        self.assertFalse(receipt["holdout_outcome_cells_read_by_this_command"])
        self.assertEqual(receipt["external_parent_clusters"], 5)
        self.assertEqual(receipt["external_sequence_components"], 4)
        self.assertEqual(receipt["combined_linked_components"], 3)

    def test_external_evaluation_release_is_complete(self) -> None:
        with (PROJECT_ROOT / "data/derived/external_evaluation_records.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            records = list(csv.DictReader(handle))
        self.assertEqual(len(records), 45)
        self.assertEqual(
            Counter(row["endpoint"] for row in records),
            {"gcgr": 15, "glp1r": 15, "selectivity": 15},
        )
        self.assertEqual(len({row["peptide_id"] for row in records}), 15)
        self.assertEqual(
            Counter((row["endpoint"], row["observation_status"]) for row in records),
            {
                ("gcgr", "exact"): 12,
                ("gcgr", "lower_bound"): 3,
                ("glp1r", "exact"): 11,
                ("glp1r", "lower_bound"): 4,
                ("selectivity", "exact"): 10,
                ("selectivity", "lower_bound"): 1,
                ("selectivity", "upper_bound"): 2,
                ("selectivity", "uninformative"): 2,
            },
        )

        with (PROJECT_ROOT / "reports/external_evaluation_metrics.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            metrics = list(csv.DictReader(handle))
        self.assertEqual(len(metrics), 12)
        self.assertEqual(
            {row["model"] for row in metrics},
            {"ridge", "nn", "median", "component_mean"},
        )
        self.assertEqual(
            {row["endpoint"] for row in metrics},
            {"gcgr", "glp1r", "selectivity"},
        )

        receipt = json.loads(
            (PROJECT_ROOT / "reports/external_evaluation_receipt.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(receipt["outcomes_accessed"])
        self.assertEqual(receipt["external_peptides"], 15)
        self.assertEqual(receipt["replicate_cells"], 90)
        self.assertEqual(
            receipt["prediction_lock_commit"],
            "7feed50339e6695859efdddcd92efd7197c7d1d3",
        )
        records_hash = hashlib.sha256(
            (PROJECT_ROOT / "data/derived/external_evaluation_records.csv").read_bytes()
        ).hexdigest()
        self.assertEqual(
            records_hash,
            receipt["local_detail_artifact_sha256"]["endpoint_records"],
        )
        ignore_rules = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!data/derived/external_evaluation_records.csv", ignore_rules)
        self.assertNotIn(
            "!data/derived/external_evaluation_replicate_sensitivity.csv",
            ignore_rules,
        )

        report = (PROJECT_ROOT / "reports/EXTERNAL_EVALUATION.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("no overall external superiority result", report.lower())
        self.assertIn("pooled-versus-macro sign reversal", report.lower())

    def test_external_figure_and_source_are_complete(self) -> None:
        with (PROJECT_ROOT / "data/derived/external_evaluation_figure_source.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(
            Counter(row["row_type"] for row in rows),
            {"model_metric": 12, "primary_delta": 2, "external_component_delta": 8},
        )
        self.assertEqual(
            {row["endpoint"] for row in rows if row["row_type"] == "primary_delta"},
            {"gcgr", "glp1r"},
        )
        self.assertEqual(
            {
                row["dependency_group"]
                for row in rows
                if row["row_type"] == "external_component_delta"
            },
            {"EC001", "EC002", "EC003", "EC004"},
        )
        png = PROJECT_ROOT / "reports/external_evaluation_figure.png"
        svg = PROJECT_ROOT / "reports/external_evaluation_figure.svg"
        self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("<svg", svg.read_text(encoding="utf-8")[:1000])

    def test_external_prediction_lock_hashes_are_unchanged(self) -> None:
        expected = {
            "configs/external_evaluation.json": (
                "3112b14e773213635ab292c6f2c8773b3914e1888062d57372267e8bfdea39fe"
            ),
            "data/derived/external_predictions_locked.csv": (
                "b85e47af4bc25041f17007e050b8152a24cd1d7e57e29e70f3b87fe61cc645bd"
            ),
            "data/derived/external_dependency_groups.csv": (
                "a643b58cde245fb1a74846dbfd4505ce916e02a81d4038afc2c0fc4387a36661"
            ),
            "reports/external_prediction_receipt.json": (
                "29799e9ec9688b61cd153928880fb06cf7fb8d253feae8f9a00e7e56adb75163"
            ),
            "scripts/score_external_evaluation.py": (
                "409727d9e51c35f817a587f7b21c7da97e2e265e713a1c56b2ea1755b9962653"
            ),
            "src/incretinselect/external_evaluation.py": (
                "99d20f6720fc936509b94760307e457776587a37da3516ebedb623c3a2f80cbc"
            ),
        }
        for relative_path, expected_hash in expected.items():
            with self.subTest(path=relative_path):
                actual_hash = hashlib.sha256(
                    (PROJECT_ROOT / relative_path).read_bytes()
                ).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_structure_seed_manifest_is_fully_resolved(self) -> None:
        with (PROJECT_ROOT / "data/derived/structures.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row["pdb_id"] for row in rows}), 10)
        self.assertTrue(all(row["query_status"] == "resolved" for row in rows))
        self.assertTrue(
            all(
                row["receptor_entity_id"]
                and row["receptor_auth_chains"]
                and row["ligand_entity_id"]
                and row["ligand_auth_chains"]
                for row in rows
            )
        )

    def test_sequence_model_figure_and_source_are_complete(self) -> None:
        with (PROJECT_ROOT / "data/derived/cpu_sequence_model_figure_source.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        oof_rows = [row for row in rows if row["row_type"] == "oof_prediction"]
        comparison_rows = [
            row for row in rows if row["row_type"] == "paired_mae_comparison"
        ]
        self.assertEqual(len(oof_rows), 250)
        self.assertEqual(len({row["peptide_id"] for row in oof_rows}), 125)
        self.assertEqual({row["endpoint"] for row in oof_rows}, {"GCGR", "GLP-1R"})
        self.assertEqual(len(comparison_rows), 3)
        for row in comparison_rows:
            self.assertLess(float(row["ci_lower"]), 0.0)
            self.assertGreater(float(row["ci_upper"]), 0.0)
        png = PROJECT_ROOT / "reports/cpu_sequence_model_oof_figure.png"
        svg = PROJECT_ROOT / "reports/cpu_sequence_model_oof_figure.svg"
        self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("<svg", svg.read_text(encoding="utf-8")[:1000])

    def test_machine_reports_record_closed_holdout(self) -> None:
        for name in (
            "sequence_split_audit.json",
            "cpu_baseline.json",
            "cpu_sequence_model.json",
        ):
            payload = json.loads((PROJECT_ROOT / "reports" / name).read_text(encoding="utf-8"))
            self.assertFalse(payload["holdout_labels_accessed"])
            if name == "cpu_sequence_model.json":
                self.assertFalse(payload["holdout_sequences_accessed"])
                self.assertEqual(payload["censored_values_imputed"], 0)


if __name__ == "__main__":
    unittest.main()
