from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from incretinselect.product import (
    EXPECTED_ALIGNMENT_POLICY_SHA256,
    EXPECTED_DEFAULT_ARTIFACT_SHA256,
    ProductError,
    load_model,
    predict,
    predict_raw,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "docs/assets/incretin_ridge_v1.json"
ADAPTER_PATH = PROJECT_ROOT / "docs/assets/raw_alignment_adapter.json"


class RawAlignmentAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def test_all_label_free_references_round_trip_from_raw_sequence(self) -> None:
        for reference in self.model.references:
            raw = reference["aligned_sequence"].replace("-", "")
            with self.subTest(reference=reference["peptide_id"]):
                result = predict_raw(raw, self.model)
                self.assertEqual(
                    result["input"]["aligned_sequence"],
                    reference["aligned_sequence"],
                )
                self.assertEqual(
                    result["input"]["alignment_adapter_sha256"],
                    EXPECTED_ALIGNMENT_POLICY_SHA256,
                )

    def test_29_residue_example_maps_without_changing_prediction(self) -> None:
        raw = "HSQGTFTSDYSKYLDSRAASEFVQWLISH"
        aligned = f"{raw}-"
        adapted = predict_raw(raw, self.model)
        strict = predict(aligned, self.model)
        self.assertEqual(adapted["input"]["aligned_sequence"], aligned)
        self.assertEqual(adapted["input"]["alignment_status"], "mapped_unambiguously")
        self.assertEqual(adapted["predictions"], strict["predictions"])

    def test_ambiguous_projection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProductError, "ambiguous"):
            predict_raw("HSQGTFTSDYSKYLDSRAQDFVQWLEEGE", self.model)

    def test_adapter_rejects_unsupported_lengths_symbols_and_trimming(self) -> None:
        cases = (
            "A" * 25,
            "A" * 31,
            "HSQGTFTSDYSKYLDSRAASEFVQWLISX",
            "HSQGTFTSDYSKYLDSRAASEFVQWLIS-",
        )
        for sequence in cases:
            with self.subTest(sequence=sequence), self.assertRaises(ProductError):
                predict_raw(sequence, self.model)

    def test_unicode_case_expansion_cannot_create_canonical_residues(self) -> None:
        raw = "HSQGTFTSDYSKYLDSRAASEFVQWLISH"
        for symbol in ("ſ", "ß", "ﬀ"):
            sequence = f"{symbol}{raw[1:]}"
            with self.subTest(symbol=symbol):
                with self.assertRaisesRegex(ProductError, "ASCII"):
                    predict_raw(sequence, self.model)
                with self.assertRaisesRegex(ProductError, "ASCII"):
                    predict(f"{sequence}-", self.model)

    def test_model_and_adapter_have_separate_frozen_checksums(self) -> None:
        self.assertEqual(
            hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
            EXPECTED_DEFAULT_ARTIFACT_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(ADAPTER_PATH.read_bytes()).hexdigest(),
            EXPECTED_ALIGNMENT_POLICY_SHA256,
        )
        policy = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
        self.assertFalse(policy["labels_accessed"])
        self.assertFalse(policy["model_coefficients_changed"])
        self.assertFalse(policy["acceptance_policy"]["terminal_trimming"])

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser parity")
    def test_python_and_browser_acceptance_decisions_match(self) -> None:
        sequences = [
            "HSQGTFTSDYSKYLDSRAASEFVQWLISH",
            "HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG",
            "HSQGTFTSDYSKYLDSRAQDFVQWLEEGE",
            "HAEGTFADVSSYLEGQAAKEFIAWLVKGR",
            "A" * 30,
            "HSQGTFTSDYSKYLDSRAASEFVQWLISH-",
            "A" * 25,
            "A" * 31,
            "ſSQGTFTSDYSKYLDSRAASEFVQWLISH",
            "ßSQGTFTSDYSKYLDSRAASEFVQWLISH",
            "ﬀSQGTFTSDYSKYLDSRAASEFVQWLISH",
        ]
        completed = subprocess.run(
            ["node", str(PROJECT_ROOT / "tests/static_demo_alignment_runner.mjs")],
            input=json.dumps(
                {
                    "model_path": str(MODEL_PATH),
                    "adapter_path": str(ADAPTER_PATH),
                    "adapter_sha256": EXPECTED_ALIGNMENT_POLICY_SHA256,
                    "sequences": sequences,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        browser = json.loads(completed.stdout)
        python: list[dict[str, object]] = []
        for sequence in sequences:
            try:
                python.append({"ok": True, "prediction": predict_raw(sequence, self.model)})
            except ProductError as exc:
                python.append({"ok": False, "error": str(exc)})
        self.assertEqual(
            [row["ok"] for row in browser],
            [row["ok"] for row in python],
        )
        self.assertEqual(
            [row["ok"] for row in browser],
            [True, True, False, False, False, False, False, False, False, False, False],
        )
        for sequence, browser_row, python_row in zip(
            sequences, browser, python, strict=True
        ):
            if not browser_row["ok"]:
                continue
            with self.subTest(sequence=sequence):
                browser_input = browser_row["prediction"]["input"]
                python_input = python_row["prediction"]["input"]
                self.assertEqual(
                    browser_input["alignedSequence"],
                    python_input["aligned_sequence"],
                )
                self.assertEqual(
                    browser_input["alignmentReferenceIds"],
                    python_input["alignment_reference_ids"],
                )
                self.assertEqual(
                    browser_input["alignmentScore"],
                    python_input["alignment_score"],
                )
                self.assertEqual(
                    browser_input["alignmentAdapterSha256"],
                    python_input["alignment_adapter_sha256"],
                )
                for endpoint in ("glp1r", "gcgr"):
                    self.assertAlmostEqual(
                        browser_row["prediction"]["predictions"][endpoint][
                            "log10Ec50Pm"
                        ],
                        python_row["prediction"]["predictions"][endpoint][
                            "log10_ec50_pm"
                        ],
                        places=12,
                    )


if __name__ == "__main__":
    unittest.main()
