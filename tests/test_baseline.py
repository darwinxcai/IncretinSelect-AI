import unittest

from incretinselect.baseline import (
    BaselineError,
    CensoredObservation,
    censor_constraint_absolute_error,
    out_of_fold_predictions,
    point_metrics,
)
from incretinselect.training import TrainingRecord


def record(peptide_id: str, sequence: str, gcgr: float, glp1r: float) -> TrainingRecord:
    return TrainingRecord(peptide_id, sequence.replace("-", ""), sequence, gcgr, glp1r)


class BaselineTests(unittest.TestCase):
    def test_censor_constraint_does_not_impute_a_bound(self) -> None:
        right = CensoredObservation("right_censored", 3.0)
        self.assertEqual(censor_constraint_absolute_error(4.0, right), 0.0)
        self.assertEqual(censor_constraint_absolute_error(2.5, right), 0.5)
        observed = CensoredObservation("observed", 3.0)
        self.assertEqual(censor_constraint_absolute_error(4.0, observed), 1.0)

    def test_point_metrics_are_exact_for_perfect_predictions(self) -> None:
        metrics = point_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        self.assertEqual(metrics["mae_log10_pm"], 0.0)
        self.assertEqual(metrics["spearman_rho"], 1.0)
        self.assertEqual(metrics["r_squared"], 1.0)

    def test_nearest_neighbour_never_uses_the_query_fold(self) -> None:
        records = [
            record("p1", "AAAA", 1.0, 10.0),
            record("p2", "AAAT", 10.0, 100.0),
            record("p3", "CCCC", 100.0, 1000.0),
            record("p4", "CCCG", 1000.0, 10000.0),
        ]
        rows = out_of_fold_predictions(records, {"p1": 1, "p2": 1, "p3": 2, "p4": 2})
        first = next(row for row in rows if row["peptide_id"] == "p1")
        self.assertNotIn("p2", str(first["nearest_donor_ids"]))
        self.assertTrue(set(str(first["nearest_donor_ids"]).split(";")) <= {"p3", "p4"})

    def test_fold_ids_must_match_records(self) -> None:
        with self.assertRaises(BaselineError):
            out_of_fold_predictions([record("p1", "AAAA", 1.0, 1.0)], {"other": 1})


if __name__ == "__main__":
    unittest.main()
