import copy
import unittest

from incretinselect.activity import validate_rows


def toy_config() -> dict:
    return {
        "dataset_sheet": "dataset",
        "alignment_sheet": "alignment",
        "expected_records": 1,
        "aligned_length": 4,
        "id_column": "pep_ID",
        "sequence_column": "sequence",
        "length_column": "length",
        "measurements": [
            {
                "receptor": "GCGR",
                "ec50_column": "EC50_T1",
                "log_column": "EC50_LOG_T1",
            },
            {
                "receptor": "GLP-1R",
                "ec50_column": "EC50_T2",
                "log_column": "EC50_LOG_T2",
            },
        ],
        "log_consistency_tolerance": 0.011,
    }


def toy_dataset_row() -> dict:
    # Synthetic test fixture; it is not a project activity record.
    return {
        "pep_ID": "toy-1",
        "sequence": "ACD",
        "length": 3,
        "EC50_T1": 1.0,
        "EC50_LOG_T1": -12.0,
        "EC50_T2": 10.0,
        "EC50_LOG_T2": -11.0,
    }


class ActivityValidationTests(unittest.TestCase):
    def test_valid_rows_pass(self) -> None:
        report = validate_rows(
            [toy_dataset_row()],
            [{"pep_ID": "toy-1", "sequence": "ACD-", "length": 4}],
            toy_config(),
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.to_dict()["error_count"], 0)

    def test_log_unit_mismatch_fails(self) -> None:
        row = toy_dataset_row()
        row["EC50_LOG_T1"] = -9.0
        report = validate_rows(
            [row],
            [{"pep_ID": "toy-1", "sequence": "ACD-", "length": 4}],
            toy_config(),
        )
        self.assertFalse(report.passed)
        self.assertIn("log_ec50_mismatch", {issue.code for issue in report.issues})

    def test_duplicate_ids_and_invalid_residue_fail(self) -> None:
        config = toy_config()
        config["expected_records"] = 2
        first = toy_dataset_row()
        second = copy.deepcopy(first)
        second["sequence"] = "ACX"
        alignment = [
            {"pep_ID": "toy-1", "sequence": "ACD-", "length": 4},
            {"pep_ID": "toy-1", "sequence": "ACD-", "length": 4},
        ]
        report = validate_rows([first, second], alignment, config)
        codes = {issue.code for issue in report.issues}
        self.assertIn("duplicate_id", codes)
        self.assertIn("invalid_residue", codes)


if __name__ == "__main__":
    unittest.main()

