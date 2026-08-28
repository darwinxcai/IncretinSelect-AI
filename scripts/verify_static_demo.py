#!/usr/bin/env python3
"""Verify browser-demo assets and numerical parity with Python inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from incretinselect.product import (
    EXPECTED_ALIGNMENT_POLICY_SHA256,
    ProductError,
    load_alignment_policy,
    load_model,
    predict,
    predict_raw,
)
from incretinselect.screen import screen_records

PARITY_REFERENCE_INDICES = (0, 11, 22, 33, 44, 55, 66, 77, 88, 99, 110, 124)
SHORT_CLOSE_ANALOGUE = "----TFTSDYSKYLDSRAASEFVQWLISE-"
BATCH_PARITY_RECORDS = (
    ("eligible_a", "HSQGTFTSDYSKYLDSRAASEFVQWLISE-"),
    ("eligible_b", "HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG"),
    ("short_close", SHORT_CLOSE_ANALOGUE),
    ("outside", "A" * 30),
    ("invalid", "TOO-SHORT"),
)
RAW_ADAPTER_CASES = (
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
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check static assets, privacy boundaries, and browser/Python parity."
    )
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs"
    source_model = root / "src/incretinselect/assets/incretin_ridge_v1.json"
    demo_model = docs / "assets/incretin_ridge_v1.json"
    if source_model.read_bytes() != demo_model.read_bytes():
        raise RuntimeError("Static demo model differs from the authoritative artifact")
    model = load_model(source_model)
    source_adapter = root / "configs/raw_alignment_adapter.json"
    demo_adapter = docs / "assets/raw_alignment_adapter.json"
    if source_adapter.read_bytes() != demo_adapter.read_bytes():
        raise RuntimeError("Static demo raw adapter differs from the frozen policy")
    adapter = load_alignment_policy()
    if sha256(demo_adapter) != EXPECTED_ALIGNMENT_POLICY_SHA256:
        raise RuntimeError("Static demo raw adapter has the wrong checksum")
    manifest = json.loads((docs / "demo_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != model.sha256:
        raise RuntimeError("Static demo manifest has the wrong artifact checksum")
    if (
        manifest.get("alignment_adapter_id") != adapter["adapter_id"]
        or manifest.get("alignment_adapter_version") != adapter["adapter_version"]
        or manifest.get("alignment_adapter_sha256") != adapter["sha256"]
    ):
        raise RuntimeError("Static demo manifest has the wrong raw-adapter identity")
    if manifest.get("labels_included") is not False:
        raise RuntimeError(
            "Static demo manifest does not preserve the activity-outcome omission boundary"
        )
    if manifest.get("local_file_import") is not True:
        raise RuntimeError("Static demo manifest does not declare local file import")
    if manifest.get("outbound_sequence_transmission") is not False:
        raise RuntimeError("Static demo manifest permits outbound sequence transmission")
    if manifest.get("structure_inference") is not False:
        raise RuntimeError("Static demo manifest incorrectly claims structure inference")

    index_source = (docs / "index.html").read_text(encoding="utf-8")
    style_source = (docs / "styles.css").read_text(encoding="utf-8")
    script_source = "\n".join(
        (docs / name).read_text(encoding="utf-8")
        for name in ("app.mjs", "model.mjs", "io.mjs")
    )
    remote_dependencies = (
        re.search(r'<script[^>]+src=["\']https?://', index_source),
        re.search(r'<link[^>]+href=["\']https?://', index_source),
        re.search(r"url\([^)]*https?://", style_source),
        re.search(r"\bfetch\s*\(\s*[\"']https?://", script_source),
    )
    if any(remote_dependencies):
        raise RuntimeError("Static demo runtime contains a remote dependency")
    if shutil.which("node") is None:
        raise RuntimeError("Node is required to verify browser/Python numerical parity")

    for script, label in (
        ("static_demo_unit.mjs", "input-contract"),
        ("static_demo_io_unit.mjs", "file-I/O and download"),
    ):
        unit = subprocess.run(
            ["node", str(root / f"tests/{script}")],
            text=True,
            capture_output=True,
            check=False,
        )
        if unit.returncode != 0:
            raise RuntimeError(f"Browser {label} checks failed: {unit.stderr}")

    sequences = [
        model.references[index]["aligned_sequence"]
        for index in PARITY_REFERENCE_INDICES
    ]
    request = {
        "model_path": str(demo_model),
        "sequences": sequences,
    }
    completed = subprocess.run(
        ["node", str(root / "tests/static_demo_runner.mjs")],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Browser parity runner failed: {completed.stderr}")
    browser_results = json.loads(completed.stdout)
    maximum_delta = 0.0
    for sequence, browser in zip(sequences, browser_results, strict=True):
        python = predict(sequence, model)
        for endpoint in ("gcgr", "glp1r"):
            delta = abs(
                browser["predictions"][endpoint]["log10Ec50Pm"]
                - python["predictions"][endpoint]["log10_ec50_pm"]
            )
            maximum_delta = max(maximum_delta, delta)
        if browser["applicability"]["tier"] != python["applicability"]["tier"]:
            raise RuntimeError("Browser applicability tier differs from Python")
        if (
            browser["applicability"]["nearestReferenceIds"]
            != python["applicability"]["nearest_reference_ids"]
        ):
            raise RuntimeError("Browser nearest references differ from Python")
        browser_comparison = browser["nearestReferenceComparison"]
        python_comparison = python["nearest_reference_comparison"]
        if (
            browser_comparison["referenceId"] != python_comparison["reference_id"]
            or browser_comparison["changedPositionCount"]
            != python_comparison["changed_position_count"]
        ):
            raise RuntimeError("Browser nearest-reference comparison differs from Python")
        for endpoint in ("gcgr", "glp1r"):
            browser_delta = browser_comparison["queryMinusReference"][
                f"{endpoint}DeltaLog10Ec50Pm"
            ]
            python_delta = python_comparison["query_minus_reference"][
                f"{endpoint}_delta_log10_ec50_pm"
            ]
            if not math.isclose(browser_delta, python_delta, rel_tol=1e-12, abs_tol=1e-12):
                raise RuntimeError("Browser model-attribution delta differs from Python")
    if maximum_delta > 1e-12:
        raise RuntimeError(f"Browser/Python maximum prediction delta is {maximum_delta}")

    raw_request = {
        "model_path": str(demo_model),
        "adapter_path": str(demo_adapter),
        "adapter_sha256": adapter["sha256"],
        "sequences": list(RAW_ADAPTER_CASES),
    }
    raw_completed = subprocess.run(
        ["node", str(root / "tests/static_demo_alignment_runner.mjs")],
        input=json.dumps(raw_request),
        text=True,
        capture_output=True,
        check=False,
    )
    if raw_completed.returncode != 0:
        raise RuntimeError(f"Browser raw-adapter runner failed: {raw_completed.stderr}")
    browser_raw = json.loads(raw_completed.stdout)
    raw_accepted = 0
    raw_rejected = 0
    for sequence, browser_row in zip(RAW_ADAPTER_CASES, browser_raw, strict=True):
        try:
            python_result = predict_raw(sequence, model)
        except ProductError:
            python_result = None
        browser_ok = bool(browser_row.get("ok"))
        if browser_ok != (python_result is not None):
            raise RuntimeError(
                f"Browser/Python raw-adapter decision differs for {sequence}"
            )
        if python_result is None:
            raw_rejected += 1
            continue
        raw_accepted += 1
        browser_prediction = browser_row["prediction"]
        browser_input = browser_prediction["input"]
        python_input = python_result["input"]
        if (
            browser_input["alignedSequence"] != python_input["aligned_sequence"]
            or browser_input["alignmentReferenceIds"]
            != python_input["alignment_reference_ids"]
            or browser_input["alignmentScore"] != python_input["alignment_score"]
            or browser_input["alignmentAdapterSha256"]
            != python_input["alignment_adapter_sha256"]
        ):
            raise RuntimeError("Browser/Python raw-adapter provenance differs")
        for endpoint in ("glp1r", "gcgr"):
            browser_value = browser_prediction["predictions"][endpoint]["log10Ec50Pm"]
            python_value = python_result["predictions"][endpoint]["log10_ec50_pm"]
            if not math.isclose(browser_value, python_value, rel_tol=1e-12, abs_tol=1e-12):
                raise RuntimeError("Browser/Python raw-adapter prediction differs")

    batch_records = [
        {"candidateId": candidate_id, "alignedSequence": sequence}
        for candidate_id, sequence in BATCH_PARITY_RECORDS
    ]
    batch_request = {
        "model_path": str(demo_model),
        "artifact_sha256": model.sha256,
        "objective": "dual",
        "records": batch_records,
    }
    batch_completed = subprocess.run(
        ["node", str(root / "tests/static_demo_screen_runner.mjs")],
        input=json.dumps(batch_request),
        text=True,
        capture_output=True,
        check=False,
    )
    if batch_completed.returncode != 0:
        raise RuntimeError(f"Browser batch parity runner failed: {batch_completed.stderr}")
    browser_screen = json.loads(batch_completed.stdout)
    python_rows, python_counts = screen_records(
        [
            {"candidate_id": candidate_id, "aligned_sequence": sequence}
            for candidate_id, sequence in BATCH_PARITY_RECORDS
        ],
        "dual",
        model=model,
    )
    if browser_screen["counts"] != python_counts:
        raise RuntimeError("Browser batch count summary differs from Python")
    browser_by_input = {row["input_row"]: row for row in browser_screen["rows"]}
    python_by_input = {row["input_row"]: row for row in python_rows}
    if browser_by_input.keys() != python_by_input.keys():
        raise RuntimeError("Browser batch rows differ from Python")
    exact_batch_fields = (
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
        "software_version",
        "artifact_id",
        "artifact_version",
        "artifact_sha256",
        "validation_warning",
    )
    numeric_batch_fields = (
        "ranking_score",
        "glp1r_log10_ec50_pm",
        "glp1r_ec50_pm",
        "gcgr_log10_ec50_pm",
        "gcgr_ec50_pm",
        "selectivity_log10_gcgr_over_glp1r",
        "nearest_aligned_identity",
    )
    batch_maximum_absolute_delta = 0.0
    batch_maximum_relative_delta = 0.0
    for input_row, browser_row in browser_by_input.items():
        python_row = python_by_input[input_row]
        for field in exact_batch_fields:
            if browser_row[field] != python_row[field]:
                raise RuntimeError(
                    f"Browser/Python batch field mismatch: input_row={input_row}, "
                    f"field={field}"
                )
        for field in numeric_batch_fields:
            if not browser_row[field] and not python_row[field]:
                continue
            browser_value = float(browser_row[field])
            python_value = float(python_row[field])
            delta = abs(browser_value - python_value)
            scale = max(abs(browser_value), abs(python_value))
            relative_delta = delta / scale if scale else 0.0
            batch_maximum_absolute_delta = max(batch_maximum_absolute_delta, delta)
            batch_maximum_relative_delta = max(batch_maximum_relative_delta, relative_delta)
            if not math.isclose(
                browser_value,
                python_value,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise RuntimeError(
                    f"Browser/Python batch numeric mismatch: input_row={input_row}, "
                    f"field={field}, delta={delta}"
                )
    short_row = browser_by_input["3"]
    if not (
        short_row["applicability_tier"] == "close_analogue"
        and short_row["ranking_eligible"] == "false"
        and short_row["status"] == "not_ranked_out_of_scope"
        and "below 26" in short_row["ranking_exclusion_reason"]
    ):
        raise RuntimeError("Short close analogue was not excluded from browser ranking")

    receipt = {
        "artifact": {
            "id": model.artifact_id,
            "sha256": model.sha256,
            "source_and_demo_bytes_identical": True,
            "version": model.artifact_version,
        },
        "alignment_adapter": {
            "id": adapter["adapter_id"],
            "version": adapter["adapter_version"],
            "sha256": adapter["sha256"],
            "source_and_demo_bytes_identical": True,
            "labels_accessed": adapter["labels_accessed"],
            "model_coefficients_changed": adapter["model_coefficients_changed"],
        },
        "browser_python_parity": {
            "applicability_exact": True,
            "batch_policy_cases": len(BATCH_PARITY_RECORDS),
            "batch_policy_exact": True,
            "raw_adapter_cases": len(RAW_ADAPTER_CASES),
            "raw_adapter_accepted": raw_accepted,
            "raw_adapter_rejected": raw_rejected,
            "raw_adapter_decisions_and_provenance_exact": True,
            "batch_maximum_absolute_numeric_delta": batch_maximum_absolute_delta,
            "batch_maximum_relative_numeric_delta": batch_maximum_relative_delta,
            "cases": len(sequences),
            "maximum_absolute_log10_delta": maximum_delta,
            "reference_source": "model applicability references stored without outcomes",
            "tolerance": 1e-12,
        },
        "browser_validation": {
            "all_gap_rejected": True,
            "batch_csv_import": True,
            "batch_download_audit_receipt": True,
            "fasta_local_import": True,
            "fasta_paste_rejected": True,
            "noncanonical_symbols_rejected": True,
            "outside_neighborhood_do_not_rank_warning": True,
            "short_close_analogue_do_not_rank_warning": True,
            "single_result_csv_download": True,
            "single_result_json_download": True,
            "single_result_markdown_download": True,
            "nearest_reference_model_attribution": True,
            "wrong_length_rejected": True,
        },
        "privacy": {
            "analytics": False,
            "external_api": False,
            "local_file_import": True,
            "outbound_runtime_urls": 0,
            "outbound_sequence_transmission": False,
        },
        "scientific_boundaries": {
            "endpoint": "cell-based cAMP EC50 functional potency, not binding affinity",
            "holdout_labels_accessed": False,
            "overall_external_superiority_claim": False,
            "structure_inference_run": False,
        },
        "status": "passed",
        "verification_scope": (
            "static model identity, local-file privacy, single-prediction parity, "
            "batch-screening parity, and downloadable artifact contracts"
        ),
    }
    if args.json_output:
        output = args.json_output
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        "static demo verification passed: model checksum, local-file privacy, "
        f"{len(sequences)} single-prediction parity cases, and "
        f"{len(BATCH_PARITY_RECORDS)} batch-policy cases"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
