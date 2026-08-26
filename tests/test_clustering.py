import unittest

from incretinselect.clustering import (
    aligned_identity,
    assign_clusters_to_folds,
    build_clusters,
    max_cross_fold_identity,
)


class ClusteringTests(unittest.TestCase):
    def test_identity_excludes_double_gap_columns(self) -> None:
        self.assertAlmostEqual(aligned_identity("AC--", "AT--"), 0.5)
        with self.assertRaises(ValueError):
            aligned_identity("---", "---")

    def test_components_and_fold_assignment_are_deterministic(self) -> None:
        sequences = {
            "p1": "AAAA",
            "p2": "AAAT",
            "p3": "CCCC",
            "p4": "CCCG",
            "p5": "GGGG",
            "p6": "TTTT",
        }
        clusters, edges = build_clusters(sequences, 0.75)
        self.assertEqual(edges, 2)
        self.assertEqual([cluster.size for cluster in clusters], [2, 2, 1, 1])
        first = assign_clusters_to_folds(clusters, 2)
        second = assign_clusters_to_folds(clusters, 2)
        self.assertEqual(first, second)

    def test_cross_fold_identity_is_auditable(self) -> None:
        sequences = {"p1": "AAAA", "p2": "AAAT", "p3": "CCCC"}
        identity, pair = max_cross_fold_identity(sequences, {"p1": 1, "p2": 2, "p3": 2})
        self.assertEqual(pair, ("p1", "p2"))
        self.assertEqual(identity, 0.75)


if __name__ == "__main__":
    unittest.main()
