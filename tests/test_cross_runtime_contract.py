from __future__ import annotations

import csv
import io
import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

from incretinselect.cli import EXAMPLE_SEQUENCE, format_csv
from incretinselect.product import load_model, predict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_MODEL = PROJECT_ROOT / "docs" / "assets" / "incretin_ridge_v1.json"


class CrossRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def _run_node(self, runner: str, request: dict[str, Any]) -> Any:
        completed = subprocess.run(
            ["node", str(PROJECT_ROOT / "tests" / runner)],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def _assert_close(self, browser: float, python: float, context: str) -> None:
        self.assertTrue(
            math.isclose(browser, python, rel_tol=1e-12, abs_tol=1e-12),
            f"{context}: browser={browser!r}, python={python!r}",
        )

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser/Python parity")
    def test_all_single_position_variants_preserve_prediction_and_evidence_parity(self) -> None:
        base = self.model.references[0]["aligned_sequence"]
        sequences = [base]
        for position in range(self.model.aligned_length):
            for symbol in self.model.alphabet:
                if symbol == base[position]:
                    continue
                sequences.append(base[:position] + symbol + base[position + 1 :])
        self.assertEqual(len(sequences), 601)

        browser_results = self._run_node(
            "static_demo_runner.mjs",
            {"model_path": str(DOCS_MODEL), "sequences": sequences},
        )
        self.assertEqual(len(browser_results), len(sequences))
        evidence_states: set[str] = set()
        tied_reference_cases = 0

        for index, (sequence, browser) in enumerate(
            zip(sequences, browser_results, strict=True)
        ):
            python = predict(sequence, self.model)
            evidence_states.add(python["applicability"]["evidence_state"])
            if python["nearest_reference_comparison"]["nearest_reference_tie_count"] > 1:
                tied_reference_cases += 1
            with self.subTest(index=index, sequence=sequence):
                browser_scope = browser["applicability"]
                python_scope = python["applicability"]
                self.assertEqual(browser_scope["tier"], python_scope["tier"])
                self.assertEqual(
                    browser_scope["evidenceState"], python_scope["evidence_state"]
                )
                self.assertEqual(
                    browser_scope["exactReferenceMatch"],
                    python_scope["exact_reference_match"],
                )
                self.assertEqual(
                    browser_scope["nearestReferenceIds"],
                    python_scope["nearest_reference_ids"],
                )
                self.assertEqual(
                    browser_scope["nearestComponentIds"],
                    python_scope["nearest_component_ids"],
                )

                for endpoint in ("gcgr", "glp1r"):
                    self._assert_close(
                        browser["predictions"][endpoint]["log10Ec50Pm"],
                        python["predictions"][endpoint]["log10_ec50_pm"],
                        f"case {index} {endpoint} prediction",
                    )
                self._assert_close(
                    browser["predictions"]["selectivity"]["log10Ec50Ratio"],
                    python["predictions"]["selectivity"]["log10_ec50_ratio"],
                    f"case {index} selectivity prediction",
                )

                browser_comparison = browser["nearestReferenceComparison"]
                python_comparison = python["nearest_reference_comparison"]
                self.assertEqual(
                    browser_comparison["referenceId"], python_comparison["reference_id"]
                )
                self.assertEqual(
                    browser_comparison["nearestReferenceTieCount"],
                    python_comparison["nearest_reference_tie_count"],
                )
                self.assertEqual(
                    browser_comparison["changedPositionCount"],
                    python_comparison["changed_position_count"],
                )
                for endpoint in ("gcgr", "glp1r"):
                    self._assert_close(
                        browser_comparison["queryMinusReference"][
                            f"{endpoint}DeltaLog10Ec50Pm"
                        ],
                        python_comparison["query_minus_reference"][
                            f"{endpoint}_delta_log10_ec50_pm"
                        ],
                        f"case {index} {endpoint} reference delta",
                    )

                browser_changes = browser_comparison["positionContributions"]
                python_changes = python_comparison["position_contributions"]
                self.assertEqual(len(browser_changes), len(python_changes))
                for browser_change, python_change in zip(
                    browser_changes, python_changes, strict=True
                ):
                    self.assertEqual(
                        (
                            browser_change["alignmentPosition"],
                            browser_change["referenceSymbol"],
                            browser_change["querySymbol"],
                        ),
                        (
                            python_change["alignment_position"],
                            python_change["reference_symbol"],
                            python_change["query_symbol"],
                        ),
                    )
                    for endpoint in ("gcgr", "glp1r"):
                        self._assert_close(
                            browser_change[f"{endpoint}DeltaLog10Ec50Pm"],
                            python_change[f"{endpoint}_delta_log10_ec50_pm"],
                            f"case {index} {endpoint} position contribution",
                        )
        self.assertEqual(
            evidence_states,
            {"training_reference_match", "local_analogue_mixed_evidence"},
        )
        self.assertGreater(tied_reference_cases, 0)

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser/Python parity")
    def test_single_csv_safety_and_provenance_contract_matches_across_runtimes(self) -> None:
        sequences = [
            EXAMPLE_SEQUENCE,
            "----TFTSDYSKYLDSRAASEFVQWLISE-",
        ]
        browser_csvs = self._run_node(
            "static_demo_export_runner.mjs",
            {
                "model_path": str(DOCS_MODEL),
                "artifact_sha256": self.model.sha256,
                "sequences": sequences,
            },
        )
        numeric_fields = {
            "glp1r_log10_ec50_pm",
            "glp1r_ec50_pm",
            "glp1r_ec50_nm",
            "gcgr_log10_ec50_pm",
            "gcgr_ec50_pm",
            "gcgr_ec50_nm",
            "selectivity_log10_gcgr_over_glp1r",
            "selectivity_ec50_fold_ratio",
            "nearest_aligned_identity",
            "glp1r_delta_log10_ec50_pm_vs_reference",
            "gcgr_delta_log10_ec50_pm_vs_reference",
            "glp1r_ec50_fold_ratio_vs_reference",
            "gcgr_ec50_fold_ratio_vs_reference",
        }
        safety_and_provenance_fields = {
            "standard_residue_count",
            "exploratory_ranking_enabled",
            "exploratory_ranking_exclusion_reason",
            "software_version",
            "artifact_id",
            "artifact_version",
            "artifact_sha256",
            "endpoint_warning",
            "validation_warning",
        }

        for index, (sequence, browser_csv) in enumerate(
            zip(sequences, browser_csvs, strict=True)
        ):
            python_csv = format_csv(predict(sequence, self.model))
            browser_reader = csv.DictReader(io.StringIO(browser_csv, newline=""))
            python_reader = csv.DictReader(io.StringIO(python_csv, newline=""))
            self.assertEqual(browser_reader.fieldnames, python_reader.fieldnames)
            browser_rows = list(browser_reader)
            python_rows = list(python_reader)
            self.assertEqual(len(browser_rows), 1)
            self.assertEqual(len(python_rows), 1)
            browser_row = browser_rows[0]
            python_row = python_rows[0]

            self.assertTrue(safety_and_provenance_fields <= browser_row.keys())
            for field in browser_row:
                with self.subTest(index=index, sequence=sequence, field=field):
                    if field in numeric_fields:
                        self._assert_close(
                            float(browser_row[field]),
                            float(python_row[field]),
                            f"case {index} CSV field {field}",
                        )
                    else:
                        self.assertEqual(
                            browser_row[field],
                            python_row[field],
                            f"case {index} CSV field {field}",
                        )
            with self.subTest(index=index, sequence=sequence, field="safety_markers"):
                self.assertIn(
                    browser_row["exploratory_ranking_enabled"], {"true", "false"}
                )
                self.assertIn("not binding affinity", browser_row["endpoint_warning"])
                self.assertIn("no overall superiority", browser_row["validation_warning"])
                self.assertEqual(browser_row["artifact_sha256"], self.model.sha256)

        short_row = next(
            csv.DictReader(io.StringIO(browser_csvs[1], newline=""))
        )
        self.assertEqual(short_row["exploratory_ranking_enabled"], "false")
        self.assertIn("26", short_row["exploratory_ranking_exclusion_reason"])


if __name__ == "__main__":
    unittest.main()
