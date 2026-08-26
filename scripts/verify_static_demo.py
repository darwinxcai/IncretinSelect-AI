#!/usr/bin/env python3
"""Verify browser-demo assets and numerical parity with Python inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from incretinselect.product import load_model, predict

PARITY_REFERENCE_INDICES = (0, 11, 22, 33, 44, 55, 66, 77, 88, 99, 110, 124)


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
    manifest = json.loads((docs / "demo_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != model.sha256:
        raise RuntimeError("Static demo manifest has the wrong artifact checksum")
    if manifest.get("labels_included") is not False:
        raise RuntimeError("Static demo manifest does not preserve the label-free boundary")

    combined_runtime = "\n".join(
        (docs / name).read_text(encoding="utf-8")
        for name in ("index.html", "styles.css", "app.mjs")
    )
    if "https://" in combined_runtime or "http://" in combined_runtime:
        raise RuntimeError("Static demo runtime contains an outbound URL")
    if shutil.which("node") is None:
        raise RuntimeError("Node is required to verify browser/Python numerical parity")

    unit = subprocess.run(
        ["node", str(root / "tests/static_demo_unit.mjs")],
        text=True,
        capture_output=True,
        check=False,
    )
    if unit.returncode != 0:
        raise RuntimeError(f"Browser input-contract checks failed: {unit.stderr}")

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
    if maximum_delta > 1e-12:
        raise RuntimeError(f"Browser/Python maximum prediction delta is {maximum_delta}")

    receipt = {
        "artifact": {
            "id": model.artifact_id,
            "sha256": model.sha256,
            "source_and_demo_bytes_identical": True,
            "version": model.artifact_version,
        },
        "browser_python_parity": {
            "applicability_exact": True,
            "cases": len(sequences),
            "maximum_absolute_log10_delta": maximum_delta,
            "reference_source": "label-free model applicability references",
            "tolerance": 1e-12,
        },
        "browser_validation": {
            "all_gap_rejected": True,
            "fasta_rejected": True,
            "noncanonical_symbols_rejected": True,
            "outside_neighborhood_do_not_rank_warning": True,
            "wrong_length_rejected": True,
        },
        "privacy": {
            "analytics": False,
            "external_api": False,
            "outbound_runtime_urls": 0,
            "sequence_upload": False,
        },
        "scientific_boundaries": {
            "endpoint": "cell-based cAMP EC50 functional potency, not binding affinity",
            "holdout_labels_accessed": False,
            "overall_external_superiority_claim": False,
            "structure_inference_run": False,
        },
        "status": "passed",
        "verification_scope": "static model identity, privacy, and browser/Python parity",
    }
    if args.json_output:
        output = args.json_output
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        "static demo verification passed: model checksum, privacy boundary, "
        f"and {len(sequences)} browser/Python parity cases"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
