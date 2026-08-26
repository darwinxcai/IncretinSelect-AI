from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import unittest
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from incretinselect.product import load_model, predict

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
        self.assertFalse(manifest["sequence_upload"])

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
        completed = subprocess.run(
            ["node", str(PROJECT_ROOT / "tests/static_demo_unit.mjs")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("unit checks passed", completed.stdout)

    def test_static_page_has_no_remote_runtime_dependency(self) -> None:
        combined = "\n".join(
            (DOCS / name).read_text(encoding="utf-8")
            for name in ("index.html", "styles.css", "app.mjs")
        )
        self.assertNotIn("https://", combined)
        self.assertNotIn("http://", combined)
        self.assertIn("No API, account, analytics, or sequence upload", combined)
        self.assertIn("not an affinity or drug-success predictor", combined)

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
