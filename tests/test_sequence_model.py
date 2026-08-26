import unittest

import numpy as np

from incretinselect.sequence_model import (
    SequenceModelError,
    component_sample_weights,
    encode_aligned_sequences,
    nested_component_ridge_predictions,
    paired_component_bootstrap_mae_delta,
)
from incretinselect.training import TrainingRecord


def record(peptide_id: str, sequence: str, gcgr: float, glp1r: float) -> TrainingRecord:
    return TrainingRecord(peptide_id, sequence.replace("-", ""), sequence, gcgr, glp1r)


class SequenceModelTests(unittest.TestCase):
    def test_one_hot_encoding_has_one_active_symbol_per_position(self) -> None:
        features = encode_aligned_sequences(["ACD-", "A-DG"], expected_length=4)
        self.assertEqual(features.shape, (2, 4 * 21))
        np.testing.assert_array_equal(features.sum(axis=1), [4.0, 4.0])
        with self.assertRaises(SequenceModelError):
            encode_aligned_sequences(["ACDX"])

    def test_component_weights_give_components_equal_total_weight(self) -> None:
        weights = component_sample_weights(["family-a", "family-a", "family-b"])
        self.assertAlmostEqual(float(weights[:2].sum()), float(weights[2]))
        self.assertAlmostEqual(float(weights.mean()), 1.0)

    def test_outer_prediction_does_not_use_held_fold_labels(self) -> None:
        records = [
            record("p1", "AAAA", 1.0, 2.0),
            record("p2", "AAAT", 2.0, 3.0),
            record("p3", "CCCC", 10.0, 20.0),
            record("p4", "CCCG", 20.0, 30.0),
            record("p5", "GGGG", 100.0, 200.0),
            record("p6", "GGGA", 200.0, 300.0),
        ]
        folds = {f"p{index}": (index + 1) // 2 for index in range(1, 7)}
        components = {f"p{index}": f"c{index}" for index in range(1, 7)}
        original = nested_component_ridge_predictions(
            records, folds, components, [0.1, 1.0], expected_length=4
        )
        changed_records = [
            record(item.peptide_id, item.aligned_sequence, 1e6, 1e7)
            if folds[item.peptide_id] == 1
            else item
            for item in records
        ]
        changed = nested_component_ridge_predictions(
            changed_records, folds, components, [0.1, 1.0], expected_length=4
        )
        original_fold = [row for row in original.rows if row["outer_fold"] == 1]
        changed_fold = [row for row in changed.rows if row["outer_fold"] == 1]
        for first, second in zip(original_fold, changed_fold, strict=True):
            self.assertAlmostEqual(
                float(first["ridge_gcgr_log10_ec50_pm"]),
                float(second["ridge_gcgr_log10_ec50_pm"]),
            )
            self.assertAlmostEqual(
                float(first["ridge_glp1r_log10_ec50_pm"]),
                float(second["ridge_glp1r_log10_ec50_pm"]),
            )

    def test_component_cannot_cross_outer_folds(self) -> None:
        records = [
            record("p1", "AAAA", 1.0, 2.0),
            record("p2", "AAAT", 2.0, 3.0),
            record("p3", "CCCC", 10.0, 20.0),
        ]
        with self.assertRaises(SequenceModelError):
            nested_component_ridge_predictions(
                records,
                {"p1": 1, "p2": 2, "p3": 2},
                {"p1": "shared", "p2": "shared", "p3": "other"},
                [1.0],
                expected_length=4,
            )

    def test_paired_component_bootstrap_is_reproducible(self) -> None:
        first = paired_component_bootstrap_mae_delta(
            [1.0, 2.0, 3.0, 4.0],
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0, 5.0],
            ["a", "a", "b", "b"],
            resamples=100,
            seed=7,
            confidence_level=0.95,
        )
        second = paired_component_bootstrap_mae_delta(
            [1.0, 2.0, 3.0, 4.0],
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0, 5.0],
            ["a", "a", "b", "b"],
            resamples=100,
            seed=7,
            confidence_level=0.95,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["mae_delta_log10_pm"], -1.0)
        self.assertEqual(first["ci_lower"], -1.0)
        self.assertEqual(first["ci_upper"], -1.0)


if __name__ == "__main__":
    unittest.main()
