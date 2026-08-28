import contextlib
import csv
import hashlib
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from incretinselect.cli import (
    EXAMPLE_RAW_SEQUENCE,
    EXAMPLE_SEQUENCE,
    format_csv,
    format_markdown,
    format_text,
)
from incretinselect.cli import main as cli_main
from incretinselect.product import ProductError, load_model, model_info, predict
from incretinselect.web import WEB_ASSETS, render_page, verify_web_assets
from incretinselect.web import main as web_main

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

    def test_malformed_custom_artifacts_fail_with_product_errors(self) -> None:
        source = PROJECT_ROOT / "src/incretinselect/assets/incretin_ridge_v1.json"
        original = json.loads(source.read_text(encoding="utf-8"))
        mutations = (
            lambda value: value["input_contract"].update(aligned_length="not-an-integer"),
            lambda value: value["model"].update(feature_mean=["not-a-number"]),
            lambda value: value["applicability_reference"].update(labels_included=True),
            lambda value: value["applicability_reference"].update(sequences=[None]),
        )
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "model.json"
            for index, mutate in enumerate(mutations):
                with self.subTest(case=index):
                    payload = json.loads(json.dumps(original))
                    mutate(payload)
                    artifact.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ProductError):
                        load_model(artifact)

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

    def test_nearest_reference_comparison_exactly_decomposes_linear_model(self) -> None:
        result = predict(EXAMPLE_SEQUENCE, self.model)
        comparison = result["nearest_reference_comparison"]
        self.assertEqual(comparison["reference_id"], "seq_pep93")
        self.assertEqual(comparison["changed_position_count"], 1)
        self.assertLess(comparison["decomposition_max_abs_residual_log10"], 1e-12)

        reference_result = predict(comparison["reference_aligned_sequence"], self.model)
        delta = comparison["query_minus_reference"]
        for endpoint in ("gcgr", "glp1r"):
            observed = (
                result["predictions"][endpoint]["log10_ec50_pm"]
                - reference_result["predictions"][endpoint]["log10_ec50_pm"]
            )
            self.assertAlmostEqual(
                observed,
                delta[f"{endpoint}_delta_log10_ec50_pm"],
                places=12,
            )
            contribution_sum = sum(
                row[f"{endpoint}_delta_log10_ec50_pm"]
                for row in comparison["position_contributions"]
            )
            self.assertAlmostEqual(observed, contribution_sum, places=12)

        identical = reference_result["nearest_reference_comparison"]
        self.assertEqual(identical["changed_position_count"], 0)
        self.assertEqual(identical["position_contributions"], [])
        self.assertAlmostEqual(
            identical["query_minus_reference"]["gcgr_delta_log10_ec50_pm"],
            0.0,
            places=12,
        )

        report = format_markdown(result)
        self.assertIn("Comparison with the closest development sequence", report)
        self.assertIn("not a causal substitution effect", report)

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
        self.assertIn("do not measure binding affinity", text)
        self.assertIn("Artifact SHA-256", text)

        csv_rows = list(csv.DictReader(io.StringIO(format_csv(result))))
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(csv_rows[0]["aligned_sequence"], EXAMPLE_SEQUENCE)
        self.assertIn("not binding affinity", csv_rows[0]["endpoint_warning"])

        page = render_page()
        self.assertIn("cell-based cAMP EC50", page)
        self.assertIn("Outputs do not measure binding affinity", page)
        self.assertEqual(verify_web_assets()["artifact_sha256"], self.model.sha256)

    def test_human_and_csv_exports_preserve_ranking_guardrails(self) -> None:
        outside = predict("A" * 30, self.model)
        outside_csv = next(csv.DictReader(io.StringIO(format_csv(outside))))
        self.assertEqual(outside_csv["exploratory_ranking_enabled"], "false")
        self.assertIn("should not be used to rank", outside_csv["exploratory_ranking_exclusion_reason"])
        self.assertEqual(outside_csv["software_version"], "0.8.0")
        self.assertIn("no overall superiority", outside_csv["validation_warning"])
        outside_report = format_markdown(outside)
        self.assertIn("Do not use this output to rank experiments", outside_report)
        self.assertIn(outside["applicability"]["summary"], outside_report)

        short = predict("----TFTSDYSKYLDSRAASEFVQWLISE-", self.model)
        self.assertEqual(short["applicability"]["tier"], "close_analogue")
        self.assertFalse(short["exploratory_ranking"]["enabled"])
        short_report = format_markdown(short)
        self.assertIn("requires at least 26", short_report)

    def test_installed_web_app_matches_the_public_browser_interface(self) -> None:
        page = render_page()
        self.assertEqual(page, (PROJECT_ROOT / "docs/index.html").read_text(encoding="utf-8"))
        self.assertIn("Candidate screen", page)
        self.assertIn("Download screened CSV", page)
        self.assertIn("Comparison with the closest development sequence", page)
        self.assertEqual(
            set(WEB_ASSETS),
            {
                "/",
                "/index.html",
                "/styles.css",
                "/app.mjs",
                "/model.mjs",
                "/io.mjs",
                "/demo_manifest.json",
                "/assets/incretin_ridge_v1.json",
                "/assets/raw_alignment_adapter.json",
            },
        )

    def test_leading_gap_sequence_has_explicit_cli_path_and_safe_csv(self) -> None:
        sequence = next(
            row["aligned_sequence"]
            for row in self.model.references
            if row["aligned_sequence"].startswith("-")
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli_main(
                [f"--sequence={sequence}", "--aligned", "--format", "json"]
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["input"]["aligned_sequence"], sequence)

        csv_row = next(csv.DictReader(io.StringIO(format_csv(predict(sequence, self.model)))))
        self.assertEqual(csv_row["aligned_sequence"], "'" + sequence)

    def test_cli_requires_explicit_opt_in_for_a_gapped_alignment(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = cli_main([EXAMPLE_SEQUENCE, "--format", "json"])
        self.assertEqual(exit_code, 2)
        self.assertIn("Raw-sequence mode does not accept '-' gaps", stderr.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli_main(
                [EXAMPLE_SEQUENCE, "--aligned", "--format", "json"]
            )
        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["input"]["alignment_status"], "provided")

    def test_cli_reads_one_fasta_file_or_standard_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fasta = Path(directory) / "candidate.fasta"
            fasta.write_text(
                f">candidate\n{EXAMPLE_RAW_SEQUENCE[:15]}\n"
                f"{EXAMPLE_RAW_SEQUENCE[15:]}\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli_main(
                    ["--sequence-file", str(fasta), "--format", "json"]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                json.loads(stdout.getvalue())["input"]["aligned_sequence"],
                EXAMPLE_SEQUENCE,
            )

        fake_stdin = mock.Mock()
        fake_stdin.buffer = io.BytesIO((EXAMPLE_RAW_SEQUENCE + "\n").encode())
        stdout = io.StringIO()
        with mock.patch("sys.stdin", fake_stdin), contextlib.redirect_stdout(stdout):
            exit_code = cli_main(["--sequence-file", "-", "--format", "json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue())["input"]["aligned_sequence"],
            EXAMPLE_SEQUENCE,
        )

    def test_sequence_file_is_bounded_and_cannot_be_its_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "candidate.fasta"
            original = f">candidate\n{EXAMPLE_SEQUENCE}\n"
            fasta.write_text(original, encoding="utf-8")

            for output in (fasta, root / "candidate-hardlink.fasta"):
                if output != fasta:
                    try:
                        os.link(fasta, output)
                    except OSError:
                        continue
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    exit_code = cli_main(
                        [
                            "--sequence-file",
                            str(fasta),
                            "--format",
                            "json",
                            "--output",
                            str(output),
                            "--overwrite",
                        ]
                    )
                self.assertEqual(exit_code, 2)
                self.assertIn("must refer to different files", stderr.getvalue())
                self.assertEqual(fasta.read_text(encoding="utf-8"), original)

            oversized = root / "oversized.txt"
            oversized.write_bytes(b"A" * 65_537)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli_main(["--sequence-file", str(oversized)])
            self.assertEqual(exit_code, 2)
            self.assertIn("65536-byte safety limit", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli_main(["--sequence-file", str(root)])
            self.assertEqual(exit_code, 2)
            self.assertNotIn("Traceback", stderr.getvalue())

            if hasattr(os, "mkfifo"):
                fifo = root / "sequence.fifo"
                os.mkfifo(fifo)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    exit_code = cli_main(["--sequence-file", str(fifo)])
                self.assertEqual(exit_code, 2)
                self.assertIn("regular file", stderr.getvalue())

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
            example_result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(example_result["schema_version"], 1)
            self.assertEqual(example_result["input"]["original_sequence"], EXAMPLE_RAW_SEQUENCE)
            self.assertEqual(example_result["input"]["aligned_sequence"], EXAMPLE_SEQUENCE)
            self.assertEqual(
                example_result["input"]["alignment_status"],
                "mapped_unambiguously",
            )

            aligned_stdout = io.StringIO()
            with contextlib.redirect_stdout(aligned_stdout):
                self.assertEqual(
                    cli_main(["--example", "--aligned", "--format", "json"]),
                    0,
                )
            aligned_example = json.loads(aligned_stdout.getvalue())
            self.assertEqual(
                aligned_example["input"]["alignment_method"],
                "provided_30_column_alignment",
            )
            self.assertEqual(aligned_example["input"]["aligned_sequence"], EXAMPLE_SEQUENCE)

            missing = root / "missing" / "result.json"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli_main(
                    ["--example", "--format", "json", "--output", str(missing)]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("Output directory does not exist", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

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
