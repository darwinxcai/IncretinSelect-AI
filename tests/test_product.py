import csv
import contextlib
import hashlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path

from incretinselect.cli import EXAMPLE_SEQUENCE, format_csv, format_text, main as cli_main
from incretinselect.product import ProductError, load_model, model_info, predict
from incretinselect.web import main as web_main, render_page

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def test_bundled_artifact_is_portable_and_label_free_by_reference(self) -> None:
        self.assertEqual(self.model.artifact_id, "incretinselect_aligned_ridge_v1")
        self.assertEqual(self.model.artifact_version, "1.0.0")
        self.assertEqual(len(self.model.references), 125)
        self.assertEqual(self.model.provenance["upstream_data_license"], "CC BY 4.0")
        info = model_info(self.model)
        self.assertEqual(info["artifact_sha256"], self.model.sha256)
        artifact_path = PROJECT_ROOT / "src/incretinselect/assets/incretin_ridge_v1.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        receipt = json.loads(
            (PROJECT_ROOT / "reports/product_model_receipt.json").read_text(
                encoding="utf-8"
            )
        )
        observed_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        self.assertEqual(observed_sha256, receipt["artifact_sha256"])
        self.assertEqual(observed_sha256, self.model.sha256)
        self.assertEqual(receipt["artifact_id"], self.model.artifact_id)
        self.assertEqual(receipt["artifact_version"], self.model.artifact_version)
        self.assertTrue(receipt["portable_without_raw_workbooks"])
        self.assertFalse(artifact["applicability_reference"]["labels_included"])
        for row in artifact["applicability_reference"]["sequences"]:
            self.assertEqual(
                set(row), {"peptide_id", "component_id", "aligned_sequence"}
            )

    def test_p1_golden_prediction_matches_pre_score_lock(self) -> None:
        result = predict(EXAMPLE_SEQUENCE, self.model)
        self.assertAlmostEqual(
            result["predictions"]["gcgr"]["log10_ec50_pm"],
            0.9868330997153905,
            places=12,
        )
        self.assertAlmostEqual(
            result["predictions"]["glp1r"]["log10_ec50_pm"],
            1.012508198632634,
            places=12,
        )
        self.assertEqual(result["applicability"]["tier"], "close_analogue")
        self.assertEqual(result["applicability"]["nearest_reference_ids"], ["seq_pep93"])

    def test_all_locked_external_predictions_are_reproduced(self) -> None:
        with (PROJECT_ROOT / "data/derived/external_predictions_locked.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 15)
        for row in rows:
            with self.subTest(peptide=row["peptide_id"]):
                result = predict(row["aligned_sequence"], self.model)
                self.assertAlmostEqual(
                    result["predictions"]["gcgr"]["log10_ec50_pm"],
                    float(row["ridge_gcgr_log10_ec50_pm"]),
                    places=12,
                )
                self.assertAlmostEqual(
                    result["predictions"]["glp1r"]["log10_ec50_pm"],
                    float(row["ridge_glp1r_log10_ec50_pm"]),
                    places=12,
                )
                self.assertAlmostEqual(
                    result["predictions"]["selectivity"]["log10_ec50_ratio"],
                    float(row["ridge_selectivity_log10_ratio"]),
                    places=12,
                )

    def test_input_normalization_is_strict_and_does_not_guess_alignment(self) -> None:
        normalized = predict(" hsqgtftsdysk yldsraasefvqwl i s h- ", self.model)
        self.assertEqual(normalized["input"]["aligned_sequence"], EXAMPLE_SEQUENCE)
        for invalid in (
            EXAMPLE_SEQUENCE.rstrip("-"),
            EXAMPLE_SEQUENCE + "A",
            EXAMPLE_SEQUENCE.replace("S", "X", 1),
            ">query\n" + EXAMPLE_SEQUENCE,
        ):
            with self.subTest(sequence=invalid), self.assertRaises(ProductError):
                predict(invalid, self.model)

    def test_text_json_csv_and_web_outputs_keep_endpoint_boundary_visible(self) -> None:
        result = predict(EXAMPLE_SEQUENCE, self.model)
        text = format_text(result)
        self.assertIn("cell-based cAMP EC50", text)
        self.assertIn("not binding affinity", text)
        self.assertIn("Artifact SHA-256", text)

        csv_rows = list(csv.DictReader(io.StringIO(format_csv(result))))
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(csv_rows[0]["aligned_sequence"], EXAMPLE_SEQUENCE)
        self.assertIn("not affinity", csv_rows[0]["endpoint_warning"])

        page = render_page(sequence=EXAMPLE_SEQUENCE, result=result)
        self.assertIn("Sequence-only functional-potency estimate", page)
        self.assertIn("does not mean tighter binding", page)
        self.assertIn(self.model.sha256, page)

    def test_web_marks_non_rankable_predictions_with_prominent_stop_box(self) -> None:
        outside = predict("A" * 30, self.model)
        self.assertNotEqual(outside["applicability"]["tier"], "close_analogue")
        outside_page = render_page(result=outside)
        self.assertIn('class="tier tier-danger"', outside_page)
        self.assertIn('data-ranking-supported="false"', outside_page)
        self.assertIn("Do not use this output to rank experiments.", outside_page)

        short_close_sequence = "----TFTSDYSKYLDSRAASEFVQWLISE-"
        short_close = predict(short_close_sequence, self.model)
        self.assertEqual(short_close["applicability"]["tier"], "close_analogue")
        self.assertLess(short_close["input"]["standard_residue_count"], 26)
        short_page = render_page(result=short_close)
        self.assertIn('data-ranking-supported="false"', short_page)
        self.assertIn("fewer than 26 standard residues", short_page)

        supported_page = render_page(result=predict(EXAMPLE_SEQUENCE, self.model))
        self.assertNotIn('data-ranking-supported="false"', supported_page)

    def test_leading_gap_sequence_has_explicit_cli_path_and_safe_csv(self) -> None:
        sequence = next(
            row["aligned_sequence"]
            for row in self.model.references
            if row["aligned_sequence"].startswith("-")
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli_main([f"--sequence={sequence}", "--format", "json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["input"]["aligned_sequence"], sequence)

        csv_row = next(csv.DictReader(io.StringIO(format_csv(predict(sequence, self.model)))))
        self.assertEqual(csv_row["aligned_sequence"], "'" + sequence)

    def test_cli_output_is_guarded_and_filesystem_errors_are_concise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            output.write_text("keep\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli_main(["--example", "--format", "json", "--output", str(output)])
            self.assertEqual(exit_code, 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep\n")
            self.assertIn("Refusing to overwrite", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

            self.assertEqual(
                cli_main(
                    [
                        "--example",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                        "--overwrite",
                    ]
                ),
                0,
            )
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["schema_version"], 1)

            missing = root / "missing" / "result.json"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli_main(
                    ["--example", "--format", "json", "--output", str(missing)]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("Output directory does not exist", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_html_escapes_rejected_input(self) -> None:
        page = render_page(sequence="<script>alert(1)</script>", error="bad <input>")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("bad &lt;input&gt;", page)

    def test_web_occupied_port_returns_concise_actionable_error(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = web_main(["--port", str(port)])

        message = stderr.getvalue()
        self.assertEqual(exit_code, 2)
        self.assertIn(f"127.0.0.1:{port}", message)
        self.assertIn("already be in use", message)
        self.assertIn("try --port", message)
        self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
