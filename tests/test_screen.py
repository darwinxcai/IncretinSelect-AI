from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from incretinselect.product import load_model, predict
from incretinselect.screen import (
    INPUT_COLUMNS,
    OBJECTIVES,
    ScreeningError,
    build_screening,
    main,
    screen_records,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REF_93 = "HSQGTFTSDYSKYLDSRAASEFVQWLISE-"
REF_11 = "HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG"
REF_27 = "YSEGTFTSDYSKLLERQAIDEFVNWLLKGG"
OUTSIDE = "A" * 30


def input_csv(rows: list[tuple[str, str]], *, bom: bool = False) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(INPUT_COLUMNS)
    writer.writerows(rows)
    prefix = "\ufeff" if bom else ""
    return (prefix + handle.getvalue()).encode("utf-8")


class BatchScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def test_all_objective_scores_are_explicit_and_mathematically_exact(self) -> None:
        records = [{"candidate_id": "ref", "aligned_sequence": REF_93}]
        prediction = predict(REF_93, self.model)["predictions"]
        expected = {
            "glp1r": prediction["glp1r"]["log10_ec50_pm"],
            "gcgr": prediction["gcgr"]["log10_ec50_pm"],
            "dual": max(
                prediction["glp1r"]["log10_ec50_pm"],
                prediction["gcgr"]["log10_ec50_pm"],
            ),
        }
        self.assertEqual(set(OBJECTIVES), set(expected))
        self.assertNotIn("selectivity", OBJECTIVES)
        for objective, expected_score in expected.items():
            with self.subTest(objective=objective):
                rows, counts = screen_records(records, objective, model=self.model)
                self.assertEqual(counts["ranked_rows"], 1)
                self.assertAlmostEqual(float(rows[0]["ranking_score"]), expected_score, places=11)

    def test_valid_invalid_and_out_of_scope_rows_all_remain_auditable(self) -> None:
        raw = input_csv(
            [
                ("close", REF_93),
                ("outside", OUTSIDE),
                ("bad_sequence", "TOO-SHORT"),
            ]
        )
        rendered, receipt, exit_code = build_screening(raw, "dual", model=self.model)
        rows = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            [row["status"] for row in rows],
            ["ranked", "not_ranked_out_of_scope", "input_error"],
        )
        self.assertEqual(rows[0]["rank"], "1")
        self.assertEqual(rows[1]["rank"], "")
        self.assertIn("outside_reference_neighborhood", rows[1]["ranking_exclusion_reason"])
        self.assertEqual(rows[2]["error_code"], "invalid_aligned_sequence")
        self.assertEqual(rows[0]["software_version"], "0.5.0")
        self.assertIn("Mixed result", rows[0]["validation_warning"])
        self.assertIn("no overall superiority", rows[0]["validation_warning"])
        self.assertEqual(receipt["counts"]["total_rows"], 3)
        self.assertEqual(receipt["model"]["software_version"], "0.5.0")
        self.assertEqual(receipt["model"]["benchmark_context"], self.model.benchmark)
        self.assertFalse(receipt["scientific_boundaries"]["holdout_labels_accessed"])
        self.assertFalse(receipt["scientific_boundaries"]["p1_p15_outcomes_accessed"])
        self.assertFalse(receipt["scientific_boundaries"]["structure_inference_run"])

    def test_duplicate_sequences_tie_but_duplicate_ids_are_fatal(self) -> None:
        raw = input_csv([("copy_a", REF_93), ("copy_b", REF_93), ("other", REF_11)])
        rendered, receipt, exit_code = build_screening(raw, "dual", model=self.model)
        rows = list(csv.DictReader(io.StringIO(rendered)))
        copies = [row for row in rows if row["candidate_id"].startswith("copy_")]
        self.assertEqual(exit_code, 0)
        self.assertEqual({row["rank"] for row in copies}, {"1"})
        self.assertEqual({row["duplicate_sequence_count"] for row in copies}, {"2"})
        self.assertEqual(receipt["counts"]["ranked_rows"], 3)

        with self.assertRaisesRegex(ScreeningError, "must be unique"):
            build_screening(
                input_csv([("duplicate", REF_93), ("duplicate", REF_11)]),
                "dual",
                model=self.model,
            )

    def test_utf8_bom_is_accepted_and_schema_is_strict(self) -> None:
        rendered, _, exit_code = build_screening(
            input_csv([("ref", REF_93)], bom=True), "glp1r", model=self.model
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(rendered)))), 1)

        for invalid in (
            b"candidate_id\nref\n",
            b"candidate_id,aligned_sequence,secret\nref," + REF_93.encode() + b",x\n",
            b"candidate_id,candidate_id\nref,ref\n",
            b"candidate_id,aligned_sequence\nref," + REF_93.encode() + b",trailing\n",
            b"candidate_id,aligned_sequence\nref," + REF_93.encode() + b",\n",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ScreeningError):
                build_screening(invalid, "dual", model=self.model)

    def test_zero_rankable_rows_have_distinct_exit_code_and_keep_predictions(self) -> None:
        rendered, receipt, exit_code = build_screening(
            input_csv([("outside", OUTSIDE)]), "gcgr", model=self.model
        )
        row = next(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(exit_code, 3)
        self.assertEqual(receipt["status"], "no_rankable_rows")
        self.assertEqual(row["rank"], "")
        self.assertTrue(row["gcgr_log10_ec50_pm"])

    def test_outputs_and_receipts_are_byte_deterministic_and_checksum_bound(self) -> None:
        raw = input_csv([("ref_93", REF_93), ("ref_11", REF_11), ("ref_27", REF_27)])
        first_csv, first_receipt, _ = build_screening(raw, "dual", model=self.model)
        second_csv, second_receipt, _ = build_screening(raw, "dual", model=self.model)
        self.assertEqual(first_csv, second_csv)
        self.assertEqual(first_receipt, second_receipt)
        self.assertEqual(first_receipt["input"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            first_receipt["output"]["sha256"],
            hashlib.sha256(first_csv.encode("utf-8")).hexdigest(),
        )

    def test_model_is_loaded_once_for_a_multirow_build(self) -> None:
        raw = input_csv([("ref_93", REF_93), ("ref_11", REF_11), ("ref_27", REF_27)])
        with mock.patch("incretinselect.screen.load_model", wraps=load_model) as loader:
            build_screening(raw, "dual")
        loader.assert_called_once_with()

    def test_rejected_spreadsheet_formula_text_is_escaped(self) -> None:
        raw = input_csv([("=FORMULA", "=FORMULA")])
        rendered, _, exit_code = build_screening(raw, "dual", model=self.model)
        row = next(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(exit_code, 3)
        self.assertEqual(row["candidate_id"], "'=FORMULA")
        self.assertEqual(row["aligned_sequence"], "'=FORMULA")
        self.assertEqual(row["status"], "input_error")

    def test_cli_writes_both_artifacts_and_refuses_accidental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidates.csv"
            output = root / "screened.csv"
            receipt = root / "receipt.json"
            source.write_bytes(input_csv([("ref", REF_93)]))
            arguments = [
                str(source),
                "--objective",
                "dual",
                "--output",
                str(output),
                "--receipt",
                str(receipt),
            ]
            self.assertEqual(main(arguments), 0)
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(receipt.read_text())["status"], "completed")
            self.assertEqual(main(arguments), 2)
            self.assertEqual(main(arguments + ["--overwrite"]), 0)
            self.assertEqual(
                main(
                    [
                        str(source),
                        "--objective",
                        "dual",
                        "--output",
                        str(source),
                        "--receipt",
                        str(receipt),
                        "--overwrite",
                    ]
                ),
                2,
            )

    def test_checked_example_regenerates_byte_for_byte(self) -> None:
        example = PROJECT_ROOT / "examples" / "candidate_screening"
        raw = (example / "candidates.csv").read_bytes()
        rendered, receipt, exit_code = build_screening(
            raw,
            "dual",
            input_filename="candidates.csv",
            output_filename="screened_dual.csv",
            model=self.model,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(rendered, (example / "screened_dual.csv").read_text(encoding="utf-8"))
        expected_receipt = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        self.assertEqual(
            expected_receipt,
            (example / "screening_receipt.json").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
