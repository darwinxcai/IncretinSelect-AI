#!/usr/bin/env python3
"""Build and smoke-test the installable wheel outside the source tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REQUIRED_WHEEL_MEMBERS = (
    "incretinselect/__init__.py",
    "incretinselect/cli.py",
    "incretinselect/product.py",
    "incretinselect/screen.py",
    "incretinselect/web.py",
    "incretinselect/assets/incretin_ridge_v1.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a wheel, install it into a temporary environment, and test the "
            "public command-line and browser entry points from outside the repository."
        )
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path for a machine-readable verification receipt.",
    )
    return parser.parse_args()


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        rendered = " ".join(command)
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {rendered}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_wheel_members(wheel: Path) -> int:
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    missing = [member for member in REQUIRED_WHEEL_MEMBERS if member not in members]
    if missing:
        raise RuntimeError(f"Wheel is missing required runtime files: {missing}")
    metadata = [member for member in members if member.endswith(".dist-info/METADATA")]
    entry_points = [member for member in members if member.endswith(".dist-info/entry_points.txt")]
    if len(metadata) != 1 or len(entry_points) != 1:
        raise RuntimeError("Wheel must contain one METADATA file and one entry_points.txt")
    return len(members)


def executable(environment: Path, name: str) -> Path:
    directory = environment / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return directory / f"{name}{suffix}"


def main() -> int:
    args = parse_args()
    repository = Path(__file__).resolve().parents[1]
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env["PYTHONNOUSERSITE"] = "1"
    build_env = clean_env.copy()
    build_env["SOURCE_DATE_EPOCH"] = "946684800"

    with tempfile.TemporaryDirectory(prefix="incretinselect-release-") as temp_name:
        temp = Path(temp_name)
        wheelhouse = temp / "wheelhouse"
        wheelhouse.mkdir()
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "--no-index",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheelhouse),
            ],
            cwd=repository,
            env=build_env,
        )
        wheels = sorted(wheelhouse.glob("incretinselect_ai-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected exactly one project wheel, found {len(wheels)}")
        wheel = wheels[0]
        wheel_member_count = verify_wheel_members(wheel)

        environment = temp / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
        environment_python = executable(environment, "python")
        run(
            [
                str(environment_python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-index",
                str(wheel),
            ],
            cwd=temp,
            env=clean_env,
        )

        predict = executable(environment, "incretin-predict")
        screen = executable(environment, "incretin-screen")
        web = executable(environment, "incretin-web")
        for entry_point in (predict, screen, web):
            if not entry_point.is_file():
                raise RuntimeError(f"Installed entry point is missing: {entry_point.name}")

        prediction = json.loads(
            run(
                [str(predict), "--example", "--format", "json"],
                cwd=temp,
                env=clean_env,
            )
        )
        if prediction.get("schema_version") != 1:
            raise RuntimeError("Installed CLI returned an unexpected schema version")
        warnings = prediction.get("warnings", [])
        if not any("not binding affinity" in warning for warning in warnings):
            raise RuntimeError("Installed CLI lost the required EC50 endpoint warning")
        artifact_sha256 = prediction.get("model", {}).get("artifact_sha256", "")
        if len(artifact_sha256) != 64:
            raise RuntimeError("Installed model did not report a SHA-256 checksum")

        csv_path = temp / "example.csv"
        run(
            [str(predict), "--example", "--format", "csv", "--output", str(csv_path)],
            cwd=temp,
            env=clean_env,
        )
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 1 or not rows[0].get("aligned_sequence"):
            raise RuntimeError("Installed CLI did not create a complete one-row CSV")

        # Label-free development references plus an artificial out-of-scope row.
        # This verifies product behavior without reading P1-P15 outcomes.
        screening_input = temp / "screening_candidates.csv"
        screening_output = temp / "screening_output.csv"
        screening_receipt_path = temp / "screening_receipt.json"
        screening_input.write_text(
            "candidate_id,aligned_sequence\n"
            "demo_ref_93,HSQGTFTSDYSKYLDSRAASEFVQWLISE-\n"
            "demo_ref_11,HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG\n"
            "demo_ref_27,YSEGTFTSDYSKLLERQAIDEFVNWLLKGG\n"
            "out_of_scope_guardrail,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n",
            encoding="utf-8",
        )
        run(
            [
                str(screen),
                str(screening_input),
                "--objective",
                "dual",
                "--output",
                str(screening_output),
                "--receipt",
                str(screening_receipt_path),
            ],
            cwd=temp,
            env=clean_env,
        )
        with screening_output.open(newline="", encoding="utf-8") as handle:
            screening_rows = list(csv.DictReader(handle))
        screening_receipt = json.loads(screening_receipt_path.read_text(encoding="utf-8"))
        ranked_rows = [row for row in screening_rows if row["status"] == "ranked"]
        excluded_rows = [
            row for row in screening_rows if row["status"] == "not_ranked_out_of_scope"
        ]
        if len(screening_rows) != 4 or len(ranked_rows) != 3 or len(excluded_rows) != 1:
            raise RuntimeError("Installed screening CLI did not retain the expected row states")
        if screening_receipt.get("objective", {}).get("name") != "dual":
            raise RuntimeError("Installed screening receipt lost the explicit objective")
        if screening_receipt.get("output", {}).get("sha256") != sha256(screening_output):
            raise RuntimeError("Installed screening receipt does not bind the output checksum")
        screening_boundaries = screening_receipt.get("scientific_boundaries", {})
        if (
            screening_boundaries.get("p1_p15_outcomes_accessed") is not False
            or screening_boundaries.get("structure_inference_run") is not False
        ):
            raise RuntimeError("Installed screening receipt violated a scientific boundary")
        benchmark_context = screening_receipt.get("model", {}).get("benchmark_context", {})
        if "no overall superiority" not in benchmark_context.get("external_evaluation", ""):
            raise RuntimeError("Installed screening receipt lost the mixed validation result")
        if not all("not binding affinity" in row["endpoint_warning"] for row in screening_rows):
            raise RuntimeError("Installed screening CSV lost the EC50 endpoint warning")
        if not all("no overall superiority" in row["validation_warning"] for row in screening_rows):
            raise RuntimeError("Installed screening CSV lost the mixed validation warning")

        web_output = run([str(web), "--smoke-test"], cwd=temp, env=clean_env).strip()
        if not web_output.startswith("ok: rendered"):
            raise RuntimeError("Installed browser entry point did not pass its smoke test")

        receipt = {
            "status": "passed",
            "verification_scope": "built wheel installed and exercised outside source tree",
            "python": sys.version.split()[0],
            "wheel": {
                "filename": wheel.name,
                "sha256": sha256(wheel),
                "member_count": wheel_member_count,
                "required_runtime_files": list(REQUIRED_WHEEL_MEMBERS),
                "source_date_epoch": build_env["SOURCE_DATE_EPOCH"],
            },
            "installed_product": {
                "model_artifact_id": prediction["model"]["artifact_id"],
                "model_artifact_sha256": artifact_sha256,
                "prediction_schema_version": prediction["schema_version"],
                "software_version": screening_receipt["model"]["software_version"],
                "csv_rows": len(rows),
                "screening_objective": screening_receipt["objective"]["name"],
                "screening_rows": len(screening_rows),
                "screening_ranked_rows": len(ranked_rows),
                "screening_out_of_scope_rows": len(excluded_rows),
                "screening_output_sha256": sha256(screening_output),
                "web_smoke": web_output,
                "ec50_warning_present": True,
            },
            "scientific_boundaries": {
                "holdout_labels_accessed": False,
                "p1_p15_outcomes_accessed": False,
                "structure_inference_run": False,
                "endpoint": "cell-based cAMP EC50 functional potency, not binding affinity",
            },
        }

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        "distribution verification passed: wheel contents, isolated install, "
        "JSON/CSV prediction, guarded batch screening, and web smoke test"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
