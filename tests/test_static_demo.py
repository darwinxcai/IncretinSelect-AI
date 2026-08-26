from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import threading
import unittest
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from incretinselect.product import load_model, predict
from incretinselect.screen import screen_records

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class StaticDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def test_demo_model_is_byte_identical_and_manifested(self) -> None:
        source = PROJECT_ROOT / "src/incretinselect/assets/incretin_ridge_v1.json"
        demo = DOCS / "assets/incretin_ridge_v1.json"
        self.assertEqual(source.read_bytes(), demo.read_bytes())
        digest = hashlib.sha256(demo.read_bytes()).hexdigest()
        manifest = json.loads((DOCS / "demo_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(digest, manifest["artifact_sha256"])
        self.assertEqual(digest, self.model.sha256)
        self.assertFalse(manifest["labels_included"])
        self.assertTrue(manifest["local_file_import"])
        self.assertFalse(manifest["outbound_sequence_transmission"])
        self.assertFalse(manifest["structure_inference"])

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser/Python parity")
    def test_browser_math_matches_python_on_label_free_references(self) -> None:
        references = self.model.references
        indices = (0, 11, 22, 33, 44, 55, 66, 77, 88, 99, 110, 124)
        sequences = [references[index]["aligned_sequence"] for index in indices]
        request = {
            "model_path": str(DOCS / "assets/incretin_ridge_v1.json"),
            "sequences": sequences,
        }
        completed = subprocess.run(
            ["node", str(PROJECT_ROOT / "tests/static_demo_runner.mjs")],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        browser_results = json.loads(completed.stdout)
        maximum_delta = 0.0
        for sequence, browser in zip(sequences, browser_results, strict=True):
            python = predict(sequence, self.model)
            for endpoint in ("gcgr", "glp1r"):
                delta = abs(
                    browser["predictions"][endpoint]["log10Ec50Pm"]
                    - python["predictions"][endpoint]["log10_ec50_pm"]
                )
                maximum_delta = max(maximum_delta, delta)
            self.assertEqual(
                browser["applicability"]["tier"],
                python["applicability"]["tier"],
            )
            self.assertEqual(
                browser["applicability"]["nearestReferenceIds"],
                python["applicability"]["nearest_reference_ids"],
            )
        self.assertLessEqual(maximum_delta, 1e-12)

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser validation")
    def test_browser_input_contract_and_scope_warning(self) -> None:
        for script, marker in (
            ("static_demo_unit.mjs", "static demo unit checks passed"),
            ("static_demo_io_unit.mjs", "static demo I/O unit checks passed"),
        ):
            completed = subprocess.run(
                ["node", str(PROJECT_ROOT / f"tests/{script}")],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(marker, completed.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node is required for batch parity")
    def test_browser_batch_policy_matches_python(self) -> None:
        records = [
            {
                "candidateId": "eligible_a",
                "alignedSequence": "HSQGTFTSDYSKYLDSRAASEFVQWLISE-",
            },
            {
                "candidateId": "eligible_b",
                "alignedSequence": "HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG",
            },
            {
                "candidateId": "short_close",
                "alignedSequence": "----TFTSDYSKYLDSRAASEFVQWLISE-",
            },
            {"candidateId": "outside", "alignedSequence": "A" * 30},
            {"candidateId": "invalid", "alignedSequence": "TOO-SHORT"},
        ]
        request = {
            "model_path": str(DOCS / "assets/incretin_ridge_v1.json"),
            "artifact_sha256": self.model.sha256,
            "objective": "dual",
            "records": records,
        }
        completed = subprocess.run(
            ["node", str(PROJECT_ROOT / "tests/static_demo_screen_runner.mjs")],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        browser = json.loads(completed.stdout)
        python_records = [
            {
                "candidate_id": record["candidateId"],
                "aligned_sequence": record["alignedSequence"],
            }
            for record in records
        ]
        python_rows, python_counts = screen_records(
            python_records,
            "dual",
            model=self.model,
        )
        self.assertEqual(browser["counts"], python_counts)
        browser_by_input = {row["input_row"]: row for row in browser["rows"]}
        python_by_input = {row["input_row"]: row for row in python_rows}
        self.assertEqual(browser_by_input.keys(), python_by_input.keys())
        exact_fields = (
            "candidate_id",
            "status",
            "error_code",
            "ranking_eligible",
            "ranking_exclusion_reason",
            "rank",
            "applicability_tier",
            "nearest_reference_ids",
            "standard_residue_count",
            "duplicate_sequence_count",
            "artifact_id",
            "artifact_version",
            "artifact_sha256",
        )
        numeric_fields = (
            "ranking_score",
            "glp1r_log10_ec50_pm",
            "glp1r_ec50_pm",
            "gcgr_log10_ec50_pm",
            "gcgr_ec50_pm",
            "selectivity_log10_gcgr_over_glp1r",
            "nearest_aligned_identity",
        )
        for input_row in browser_by_input:
            browser_row = browser_by_input[input_row]
            python_row = python_by_input[input_row]
            for field in exact_fields:
                self.assertEqual(
                    browser_row[field],
                    python_row[field],
                    f"batch parity field={field} input_row={input_row}",
                )
            for field in numeric_fields:
                if not browser_row[field] and not python_row[field]:
                    continue
                browser_value = float(browser_row[field])
                python_value = float(python_row[field])
                self.assertTrue(
                    math.isclose(
                        browser_value,
                        python_value,
                        rel_tol=1e-12,
                        abs_tol=1e-12,
                    ),
                    f"batch parity field={field} input_row={input_row}: "
                    f"browser={browser_value}, python={python_value}",
                )

        short_row = browser_by_input["3"]
        self.assertEqual(short_row["applicability_tier"], "close_analogue")
        self.assertEqual(short_row["ranking_eligible"], "false")
        self.assertEqual(short_row["status"], "not_ranked_out_of_scope")
        self.assertIn("below 26", short_row["ranking_exclusion_reason"])

    def test_static_page_has_no_remote_runtime_dependency(self) -> None:
        combined = "\n".join(
            (DOCS / name).read_text(encoding="utf-8")
            for name in ("index.html", "styles.css", "app.mjs", "model.mjs", "io.mjs")
        )
        self.assertNotIn("https://", combined)
        self.assertNotIn("http://", combined)
        single_spaced = " ".join(combined.split())
        self.assertIn("no backend, account, analytics service", single_spaced)
        self.assertIn("network transmission of sequences", single_spaced)
        self.assertIn("not an affinity or drug-success predictor", single_spaced)
        self.assertIn("Why there is no structure upload", single_spaced)
        self.assertIn("candidate_id,aligned_sequence", single_spaced)
        self.assertIn("Download JSON", single_spaced)
        self.assertIn("Download screened CSV", single_spaced)

    def test_docs_directory_serves_complete_demo(self) -> None:
        handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
            *args,
            directory=str(DOCS),
            **kwargs,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            for path, marker in (
                ("/", b"IncretinSelect-AI"),
                ("/app.mjs", b"predictFromModel"),
                ("/model.mjs", b"predictFromModel"),
                ("/io.mjs", b"buildBatchArtifacts"),
                ("/demo_manifest.json", self.model.sha256.encode()),
                ("/assets/incretin_ridge_v1.json", b"incretinselect_aligned_ridge_v1"),
            ):
                with urllib.request.urlopen(base + path, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(marker, response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
