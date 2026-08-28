from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from incretinselect import __version__
from incretinselect.product import load_model, predict, predict_raw
from incretinselect.screen import (
    INPUT_COLUMNS,
    MAX_CANDIDATES,
    MAX_RAW_CANDIDATES,
    OBJECTIVES,
    ScreeningError,
    _atomic_write_pair,
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
                self.assertEqual(rows[0]["score_delta_from_first_log10"], "0")
                self.assertEqual(rows[0]["score_fold_ratio_from_first"], "1")
                self.assertEqual(
                    rows[0]["within_one_development_mae_of_first"], "true"
                )

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
        self.assertEqual(rows[0]["software_version"], __version__)
        self.assertEqual(rows[0]["applicability_evidence_state"], "training_reference_match")
        self.assertEqual(rows[0]["exact_reference_match"], "true")
        self.assertIn("Mixed result", rows[0]["validation_warning"])
        self.assertIn("no overall superiority", rows[0]["validation_warning"])
        self.assertEqual(receipt["counts"]["total_rows"], 3)
        self.assertEqual(receipt["model"]["software_version"], __version__)
        self.assertEqual(receipt["model"]["benchmark_context"], self.model.benchmark)
        self.assertFalse(receipt["scientific_boundaries"]["holdout_labels_accessed"])
        self.assertFalse(receipt["scientific_boundaries"]["p1_p15_outcomes_accessed"])
        self.assertFalse(receipt["scientific_boundaries"]["structure_inference_run"])
        self.assertIn("not an individual confidence interval", receipt["ranking_context"]["interpretation"])
        self.assertIn("not a calibrated", receipt["ranking_gate"]["scientific_boundary"])

    def test_raw_sequence_schema_maps_unambiguous_rows_and_retains_ambiguity(self) -> None:
        raw_sequence = REF_93.rstrip("-")
        ambiguous = "HAEGTFADVSSYLEGQAAKEFIAWLVKGR"
        raw = (
            "candidate_id,sequence\n"
            f"raw_local,{raw_sequence}\n"
            f"ambiguous,{ambiguous}\n"
        ).encode("utf-8")
        rendered, receipt, exit_code = build_screening(raw, "dual", model=self.model)
        rows = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["status"], "ranked")
        self.assertEqual(rows[0]["input_sequence"], raw_sequence)
        self.assertEqual(rows[0]["input_mode"], "raw_sequence")
        self.assertEqual(rows[0]["aligned_sequence"], REF_93)
        self.assertEqual(rows[0]["alignment_status"], "mapped_unambiguously")
        self.assertRegex(rows[0]["alignment_adapter_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(rows[1]["status"], "input_error")
        self.assertEqual(rows[1]["error_code"], "invalid_raw_sequence")
        self.assertIn("ambiguous", rows[1]["error_message"].lower())
        self.assertEqual(receipt["input"]["input_mode"], "raw_sequence")
        self.assertEqual(receipt["input"]["maximum_rows"], MAX_RAW_CANDIDATES)
        self.assertEqual(
            receipt["alignment_adapter"]["adapter_id"],
            "raw_alignment_adapter_v1",
        )
        self.assertRegex(receipt["alignment_adapter"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(receipt["alignment_adapter"]["used_for_input"])
        self.assertFalse(receipt["alignment_adapter"]["labels_accessed"])

    def test_unicode_row_cannot_alias_a_cached_canonical_sequence(self) -> None:
        raw_sequence = REF_93.rstrip("-")
        unicode_alias = raw_sequence.replace("S", "ſ", 1)
        raw = (
            "candidate_id,sequence\n"
            f"canonical,{raw_sequence}\n"
            f"unicode_alias,{unicode_alias}\n"
        ).encode("utf-8")
        rendered, receipt, exit_code = build_screening(raw, "dual", model=self.model)
        rows = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["status"], "ranked")
        self.assertEqual(rows[1]["status"], "input_error")
        self.assertIn("ASCII", rows[1]["error_message"])
        self.assertEqual(receipt["alignment_adapter"]["adapter_id"], "raw_alignment_adapter_v1")

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

        with self.assertRaises(ScreeningError) as raised:
            build_screening(
                input_csv([("duplicate\nid", REF_93), ("duplicate\nid", REF_11)]),
                "dual",
                model=self.model,
            )
        self.assertNotIn("\n", str(raised.exception))
        self.assertIn(r"\u000a", str(raised.exception))

    def test_candidate_row_limit_is_enforced_during_parsing(self) -> None:
        rows = ((f"candidate_{index}", REF_93) for index in range(MAX_CANDIDATES + 1))
        with self.assertRaisesRegex(ScreeningError, "more than 10000 rows"):
            build_screening(input_csv(list(rows)), "dual", model=self.model)

    def test_raw_sequence_row_limit_prevents_unbounded_alignment_work(self) -> None:
        rows = "".join(
            f"candidate_{index},{REF_93.rstrip('-')}\n"
            for index in range(MAX_RAW_CANDIDATES + 1)
        )
        raw = f"candidate_id,sequence\n{rows}".encode("utf-8")
        with self.assertRaisesRegex(ScreeningError, "alignment-adapter limit"):
            build_screening(raw, "dual", model=self.model)

    def test_repeated_raw_sequences_reuse_one_alignment_prediction(self) -> None:
        records = [
            {
                "candidate_id": f"copy_{index}",
                "sequence": REF_93.rstrip("-"),
                "input_mode": "raw_sequence",
            }
            for index in range(4)
        ]
        with mock.patch(
            "incretinselect.screen.predict_raw",
            wraps=predict_raw,
        ) as predictor:
            rows, counts = screen_records(records, "dual", model=self.model)
        self.assertEqual(predictor.call_count, 1)
        self.assertEqual(counts["ranked_rows"], 4)
        self.assertEqual({row["duplicate_sequence_count"] for row in rows}, {"4"})

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

    def test_invalid_receipt_targets_never_mutate_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidates.csv"
            output = root / "screened.csv"
            source.write_bytes(input_csv([("ref", REF_93)]))
            output.write_text("existing output\n", encoding="utf-8")
            base_arguments = [
                str(source),
                "--objective",
                "dual",
                "--output",
                str(output),
            ]

            receipt_directory = root / "receipt-directory"
            receipt_directory.mkdir()
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                exit_code = main(
                    base_arguments
                    + ["--receipt", str(receipt_directory), "--overwrite"]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("not a regular file", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "existing output\n")

            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("file\n", encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                exit_code = main(
                    base_arguments
                    + [
                        "--receipt",
                        str(blocked_parent / "receipt.json"),
                        "--overwrite",
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("parent is not a directory", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "existing output\n")

            receipt_target = root / "receipt-target.json"
            receipt_target.write_text("existing receipt\n", encoding="utf-8")
            receipt_link = root / "receipt-link.json"
            receipt_link.symlink_to(receipt_target)
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                exit_code = main(
                    base_arguments
                    + ["--receipt", str(receipt_link), "--overwrite"]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("must not be symbolic links", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "existing output\n")
            self.assertEqual(
                receipt_target.read_text(encoding="utf-8"), "existing receipt\n"
            )

    def test_commit_failure_rolls_back_both_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidates.csv"
            output = root / "screened.csv"
            receipt = root / "receipt.json"
            source.write_bytes(input_csv([("ref", REF_93)]))
            output.write_text("existing output\n", encoding="utf-8")
            receipt.write_text("existing receipt\n", encoding="utf-8")
            arguments = [
                str(source),
                "--objective",
                "dual",
                "--output",
                str(output),
                "--receipt",
                str(receipt),
                "--overwrite",
            ]
            real_replace = os.replace

            def fail_receipt_commit(source_path: object, destination_path: object) -> None:
                if (
                    Path(destination_path) == receipt
                    and str(source_path).endswith(".tmp")
                ):
                    raise OSError("simulated receipt commit failure")
                real_replace(source_path, destination_path)

            error = io.StringIO()
            with (
                mock.patch("incretinselect.screen.os.replace", fail_receipt_commit),
                contextlib.redirect_stderr(error),
            ):
                exit_code = main(arguments)

            self.assertEqual(exit_code, 2)
            self.assertIn("simulated receipt commit failure", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "existing output\n")
            self.assertEqual(receipt.read_text(encoding="utf-8"), "existing receipt\n")
            self.assertEqual(
                [path.name for path in root.iterdir() if path.name.startswith(".")],
                [],
            )

    def test_keyboard_interrupt_rolls_back_both_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "screened.csv"
            receipt = root / "receipt.json"
            output.write_text("existing output\n", encoding="utf-8")
            receipt.write_text("existing receipt\n", encoding="utf-8")
            real_replace = os.replace

            def interrupt_receipt_commit(
                source_path: object,
                destination_path: object,
            ) -> None:
                if (
                    Path(destination_path) == receipt
                    and str(source_path).endswith(".tmp")
                ):
                    raise KeyboardInterrupt
                real_replace(source_path, destination_path)

            with (
                mock.patch("incretinselect.screen.os.replace", interrupt_receipt_commit),
                self.assertRaises(KeyboardInterrupt),
            ):
                _atomic_write_pair(
                    output,
                    "new output\n",
                    receipt,
                    "new receipt\n",
                    overwrite=True,
                )

            self.assertEqual(output.read_text(encoding="utf-8"), "existing output\n")
            self.assertEqual(receipt.read_text(encoding="utf-8"), "existing receipt\n")
            self.assertEqual(
                [path.name for path in root.iterdir() if path.name.startswith(".")],
                [],
            )

    def test_failed_restore_preserves_original_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "screened.csv"
            receipt = root / "receipt.json"
            output.write_text("existing output\n", encoding="utf-8")
            receipt.write_text("existing receipt\n", encoding="utf-8")
            real_replace = os.replace

            def fail_commit_and_output_restore(
                source_path: object,
                destination_path: object,
            ) -> None:
                source = Path(source_path)
                destination = Path(destination_path)
                if destination == receipt and source.suffix == ".tmp":
                    raise OSError("simulated receipt commit failure")
                if destination == output and source.suffix == ".bak":
                    raise OSError("simulated output restore failure")
                real_replace(source, destination)

            with (
                mock.patch(
                    "incretinselect.screen.os.replace",
                    fail_commit_and_output_restore,
                ),
                self.assertRaises(ScreeningError) as raised,
            ):
                _atomic_write_pair(
                    output,
                    "new output\n",
                    receipt,
                    "new receipt\n",
                    overwrite=True,
                )

            backup_paths = sorted(root.glob(".screened.csv.*.bak"))
            self.assertEqual(len(backup_paths), 1)
            self.assertEqual(
                backup_paths[0].read_text(encoding="utf-8"),
                "existing output\n",
            )
            self.assertIn(str(backup_paths[0]), str(raised.exception))
            self.assertEqual(receipt.read_text(encoding="utf-8"), "existing receipt\n")
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob("*.tmp")), [])

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
