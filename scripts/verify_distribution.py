#!/usr/bin/env python3
"""Build and verify the wheel and complete research source distribution."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path

REQUIRED_WHEEL_MEMBERS = (
    "incretinselect/__init__.py",
    "incretinselect/activity.py",
    "incretinselect/baseline.py",
    "incretinselect/cli.py",
    "incretinselect/clustering.py",
    "incretinselect/external_evaluation.py",
    "incretinselect/holdout.py",
    "incretinselect/product.py",
    "incretinselect/screen.py",
    "incretinselect/sequence_model.py",
    "incretinselect/sources.py",
    "incretinselect/structures.py",
    "incretinselect/training.py",
    "incretinselect/web.py",
    "incretinselect/assets/incretin_ridge_v1.json",
    "incretinselect/notices/CITATION.cff",
    "incretinselect/notices/DATA_LICENSE.md",
    "incretinselect/notices/LICENSE",
    "incretinselect/resources/activity_schema.json",
    "incretinselect/resources/raw_alignment_adapter.json",
    "incretinselect/resources/sources.json",
    "incretinselect/resources/structure_targets.csv",
    "incretinselect/web_assets/index.html",
    "incretinselect/web_assets/styles.css",
    "incretinselect/web_assets/app.mjs",
    "incretinselect/web_assets/model.mjs",
    "incretinselect/web_assets/io.mjs",
    "incretinselect/web_assets/demo_manifest.json",
)

REQUIRED_SDIST_PATHS = (
    ".github/workflows/ci.yml",
    ".github/workflows/pages.yml",
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "DATA_LICENSE.md",
    "LICENSE",
    "MANIFEST.in",
    "Makefile",
    "PUBLISHING.md",
    "README.md",
    "RELEASE_READINESS.md",
    "configs/activity_schema.json",
    "configs/cpu_sequence_model.json",
    "configs/raw_alignment_adapter.json",
    "configs/structure_targets.csv",
    "data/derived/sequence_model_oof_predictions.csv",
    "data/manifests/sources.json",
    "docs/index.html",
    "docs/assets/raw_alignment_adapter.json",
    "examples/candidate_screening/candidates.csv",
    "reports/CPU_SEQUENCE_MODEL.md",
    "scripts/verify_distribution.py",
    "src/incretinselect/__init__.py",
    "tests/test_product.py",
    "tests/test_alignment_adapter.py",
)

GENERATED_SDIST_PATHS = frozenset(
    {
        "PKG-INFO",
        "setup.cfg",
        "src/incretinselect_ai.egg-info/PKG-INFO",
        "src/incretinselect_ai.egg-info/SOURCES.txt",
        "src/incretinselect_ai.egg-info/dependency_links.txt",
        "src/incretinselect_ai.egg-info/entry_points.txt",
        "src/incretinselect_ai.egg-info/requires.txt",
        "src/incretinselect_ai.egg-info/top_level.txt",
    }
)

FORBIDDEN_SDIST_PATTERNS = (
    re.compile(r"^data/raw/(?!README\.md$)"),
    re.compile(r"^data/derived/prospective_holdout\.json$"),
    re.compile(r"\.(?:xlsx|xls|pkl|pickle)$", re.IGNORECASE),
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
    parser.add_argument(
        "--artifact-output-dir",
        type=Path,
        help=(
            "Optional empty directory that receives the exact wheel and source "
            "archive exercised by this verification run."
        ),
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


def canonicalize_sdist(path: Path, source_date_epoch: int) -> None:
    """Normalize tar and gzip metadata so repeated source builds are byte-identical."""

    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(path, "r:gz") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            extracted = archive.extractfile(member) if member.isfile() else None
            entries.append((member, extracted.read() if extracted is not None else None))
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            compresslevel=9,
            mtime=source_date_epoch,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as output:
                for member, payload in entries:
                    normalized = copy.copy(member)
                    normalized.mtime = source_date_epoch
                    normalized.uid = 0
                    normalized.gid = 0
                    normalized.uname = ""
                    normalized.gname = ""
                    normalized.pax_headers = {}
                    output.addfile(
                        normalized,
                        io.BytesIO(payload) if payload is not None else None,
                    )
    temporary.replace(path)


def manifest_allowlist(repository: Path) -> list[str]:
    entries = [
        line.removeprefix("include ")
        for line in (repository / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        if line.startswith("include ")
    ]
    if entries != sorted(set(entries)):
        raise RuntimeError("Source-distribution allowlist must be sorted and unique")
    for entry in entries:
        relative = Path(entry)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe source-distribution allowlist path: {entry}")
        if not (repository / relative).is_file():
            raise RuntimeError(f"Source-distribution allowlist path is missing: {entry}")
    return entries


def materialize_allowlisted_tree(
    repository: Path, destination: Path, allowlist: list[str]
) -> None:
    destination.mkdir()
    for entry in allowlist:
        source = repository / entry
        target = destination / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)


def verify_wheel_members(wheel: Path, repository: Path) -> int:
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        missing = [member for member in REQUIRED_WHEEL_MEMBERS if member not in members]
        if missing:
            raise RuntimeError(f"Wheel is missing required runtime files: {missing}")
        metadata = [member for member in members if member.endswith(".dist-info/METADATA")]
        entry_points = [
            member for member in members if member.endswith(".dist-info/entry_points.txt")
        ]
        if len(metadata) != 1 or len(entry_points) != 1:
            raise RuntimeError("Wheel must contain one METADATA file and one entry_points.txt")
        metadata_text = archive.read(metadata[0]).decode("utf-8")
        if "Requires-Dist: numpy" not in metadata_text:
            raise RuntimeError("Wheel metadata is missing the NumPy runtime dependency")
        if "License-Expression: MIT AND CC-BY-4.0" not in metadata_text:
            raise RuntimeError("Wheel metadata does not cover the code and model licenses")
        for label, url in (
            ("Homepage", "https://darwinxcai.github.io/IncretinSelect-AI/"),
            ("Repository", "https://github.com/darwinxcai/IncretinSelect-AI"),
        ):
            if f"Project-URL: {label}, {url}" not in metadata_text:
                raise RuntimeError(f"Wheel metadata is missing the {label} URL")
        license_members = {
            Path(member).name
            for member in members
            if ".dist-info/licenses/" in member
        }
        if not {"LICENSE", "DATA_LICENSE.md"}.issubset(license_members):
            raise RuntimeError("Wheel metadata is missing software or data-license notices")
        for notice in ("CITATION.cff", "DATA_LICENSE.md", "LICENSE"):
            packaged = f"incretinselect/notices/{notice}"
            if archive.read(packaged) != (repository / notice).read_bytes():
                raise RuntimeError(f"Packaged notice does not match {notice}")
    return len(members)


def build_and_verify_sdist(
    repository: Path,
    temp: Path,
    build_env: dict[str, str],
    clean_env: dict[str, str],
    wheel_sha256: str,
) -> tuple[dict[str, object], Path]:
    allowlist = manifest_allowlist(repository)
    manifest_entries = set(allowlist)
    sdist_input = temp / "sdist-input"
    materialize_allowlisted_tree(repository, sdist_input, allowlist)
    sdist_dir = temp / "sdist"
    sdist_dir.mkdir()
    run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from setuptools.build_meta import build_sdist; "
                "print(build_sdist(sys.argv[1]))"
            ),
            str(sdist_dir),
        ],
        cwd=sdist_input,
        env=build_env,
    )
    sdists = sorted(sdist_dir.glob("incretinselect_ai-*.tar.gz"))
    if len(sdists) != 1:
        raise RuntimeError(f"Expected exactly one source distribution, found {len(sdists)}")
    sdist = sdists[0]
    source_date_epoch = int(build_env["SOURCE_DATE_EPOCH"])
    canonicalize_sdist(sdist, source_date_epoch)
    repeated_sdist_dir = temp / "sdist-repeat"
    repeated_sdist_dir.mkdir()
    repeated_sdist_input = temp / "sdist-repeat-input"
    materialize_allowlisted_tree(repository, repeated_sdist_input, allowlist)
    run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from setuptools.build_meta import build_sdist; "
                "print(build_sdist(sys.argv[1]))"
            ),
            str(repeated_sdist_dir),
        ],
        cwd=repeated_sdist_input,
        env=build_env,
    )
    repeated_sdists = sorted(repeated_sdist_dir.glob("incretinselect_ai-*.tar.gz"))
    if len(repeated_sdists) != 1:
        raise RuntimeError("Repeated source build did not create exactly one archive")
    canonicalize_sdist(repeated_sdists[0], source_date_epoch)
    if sha256(repeated_sdists[0]) != sha256(sdist):
        raise RuntimeError("Repeated source-distribution builds are not byte-identical")
    extracted_root = temp / "sdist-extracted"
    extracted_root.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        roots = {name.split("/", 1)[0] for name in names if "/" in name}
        if len(roots) != 1:
            raise RuntimeError("Source distribution must contain exactly one root directory")
        prefix = next(iter(roots)) + "/"
        missing = [path for path in REQUIRED_SDIST_PATHS if prefix + path not in names]
        if missing:
            raise RuntimeError(f"Source distribution is missing reproducibility files: {missing}")
        archived_files = {
            member.name.removeprefix(prefix)
            for member in members
            if member.isfile() and member.name.startswith(prefix)
        }
        missing_tracked = sorted(manifest_entries - archived_files)
        unexpected = sorted(archived_files - manifest_entries - GENERATED_SDIST_PATHS)
        if missing_tracked:
            raise RuntimeError(
                f"Source distribution is missing tracked files: {missing_tracked}"
            )
        if unexpected:
            raise RuntimeError(
                f"Source distribution contains files outside the tracked allowlist: {unexpected}"
            )
        forbidden = sorted(
            path
            for path in archived_files
            if any(pattern.search(path) for pattern in FORBIDDEN_SDIST_PATTERNS)
        )
        if forbidden:
            raise RuntimeError(f"Source distribution contains forbidden research files: {forbidden}")
        for member in members:
            destination = (extracted_root / member.name).resolve()
            if extracted_root.resolve() not in destination.parents and destination != extracted_root:
                raise RuntimeError(f"Unsafe source-distribution path: {member.name}")
        try:
            archive.extractall(extracted_root, filter="data")
        except TypeError:  # Python versions without extraction filters
            archive.extractall(extracted_root)
    source_root = extracted_root / prefix.rstrip("/")
    run(["make", "test"], cwd=source_root, env=clean_env)
    run(["make", "product-smoke"], cwd=source_root, env=clean_env)
    run(
        [sys.executable, "scripts/sync_package_resources.py", "--check"],
        cwd=source_root,
        env=clean_env,
    )
    run(
        [sys.executable, "scripts/sync_static_demo.py", "--check"],
        cwd=source_root,
        env=clean_env,
    )
    rebuilt_wheelhouse = temp / "sdist-wheelhouse"
    rebuilt_wheelhouse.mkdir()
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
            str(rebuilt_wheelhouse),
        ],
        cwd=source_root,
        env=build_env,
    )
    rebuilt_wheels = sorted(rebuilt_wheelhouse.glob("incretinselect_ai-*.whl"))
    if len(rebuilt_wheels) != 1:
        raise RuntimeError("Source distribution did not rebuild exactly one wheel")
    rebuilt_wheel_sha256 = sha256(rebuilt_wheels[0])
    if rebuilt_wheel_sha256 != wheel_sha256:
        raise RuntimeError("Wheel rebuilt from the source distribution is not byte-identical")
    return (
        {
            "filename": sdist.name,
            "member_count": len(members),
            "tracked_file_count": len(manifest_entries),
            "build_input": "git-tracked allowlist only",
            "complete_research_tree": True,
            "untracked_files_included": False,
            "forbidden_research_files_included": False,
            "byte_deterministic": True,
            "source_date_epoch": str(source_date_epoch),
            "tests": "passed",
            "product_smoke": "passed",
            "resource_sync": "passed",
            "static_demo_sync": "passed",
            "rebuilt_wheel_sha256": rebuilt_wheel_sha256,
            "rebuilt_wheel_byte_identical": True,
        },
        sdist,
    )


def executable(environment: Path, name: str) -> Path:
    directory = environment / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return directory / f"{name}{suffix}"


def main() -> int:
    args = parse_args()
    repository = Path(__file__).resolve().parents[1]
    project_text = (repository / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(
        r'^version\s*=\s*"([^"]+)"', project_text, flags=re.MULTILINE
    )
    if version_match is None:
        raise RuntimeError("pyproject.toml does not declare a project version")
    project_version = version_match.group(1)
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env["PYTHONNOUSERSITE"] = "1"
    build_env = clean_env.copy()
    build_env["SOURCE_DATE_EPOCH"] = "946684800"

    run(
        [sys.executable, "scripts/sync_package_resources.py", "--check"],
        cwd=repository,
        env=clean_env,
    )
    run(
        [sys.executable, "scripts/sync_sdist_manifest.py", "--check"],
        cwd=repository,
        env=clean_env,
    )

    with tempfile.TemporaryDirectory(prefix="incretinselect-release-") as temp_name:
        temp = Path(temp_name)
        allowlist = manifest_allowlist(repository)
        wheel_input = temp / "wheel-input"
        materialize_allowlisted_tree(repository, wheel_input, allowlist)
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
            cwd=wheel_input,
            env=build_env,
        )
        wheels = sorted(wheelhouse.glob("incretinselect_ai-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected exactly one project wheel, found {len(wheels)}")
        wheel = wheels[0]
        wheel_member_count = verify_wheel_members(wheel, repository)
        wheel_sha256 = sha256(wheel)

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

        entry_points = {
            name: executable(environment, name)
            for name in (
                "incretin-validate",
                "incretin-structures",
                "incretin-fetch",
                "incretin-predict",
                "incretin-screen",
                "incretin-web",
            )
        }
        for entry_point in entry_points.values():
            if not entry_point.is_file():
                raise RuntimeError(f"Installed entry point is missing: {entry_point.name}")
        schema = json.loads(
            run([str(entry_points["incretin-validate"]), "--print-schema"], cwd=temp, env=clean_env)
        )
        if schema.get("expected_records") != 125 or schema.get("aligned_length") != 30:
            raise RuntimeError("Installed activity schema is incomplete")
        source_ids = run(
            [str(entry_points["incretin-fetch"]), "--list-sources"],
            cwd=temp,
            env=clean_env,
        ).splitlines()
        if "puszkarska_2024_training" not in source_ids or "rcsb_structure_panel" not in source_ids:
            raise RuntimeError("Installed source manifest is incomplete")
        structure_seeds = json.loads(
            run([str(entry_points["incretin-structures"]), "--list-seeds"], cwd=temp, env=clean_env)
        )
        if len(structure_seeds) != 10:
            raise RuntimeError("Installed structure seed panel is incomplete")

        predict = entry_points["incretin-predict"]
        screen = entry_points["incretin-screen"]
        web = entry_points["incretin-web"]
        if run([str(predict), "--version"], cwd=temp, env=clean_env).strip() != (
            f"incretin-predict {project_version}"
        ):
            raise RuntimeError("Installed prediction command reports the wrong version")
        if run([str(screen), "--version"], cwd=temp, env=clean_env).strip() != (
            f"incretin-screen {project_version}"
        ):
            raise RuntimeError("Installed screening command reports the wrong version")

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
        if not any("do not measure binding affinity" in warning for warning in warnings):
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

        # Development references stored without outcomes plus an artificial out-of-scope row.
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
        screening_adapter = screening_receipt.get("alignment_adapter", {})
        if (
            screening_adapter.get("adapter_id") != "raw_alignment_adapter_v1"
            or not re.fullmatch(r"[0-9a-f]{64}", str(screening_adapter.get("sha256", "")))
            or screening_adapter.get("labels_accessed") is not False
            or screening_adapter.get("model_coefficients_changed") is not False
        ):
            raise RuntimeError("Installed screening receipt lost raw-adapter provenance")
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
        if not web_output.startswith("ok: verified browser application"):
            raise RuntimeError("Installed browser entry point did not pass its smoke test")

        source_distribution, source_distribution_path = build_and_verify_sdist(
            repository,
            temp,
            build_env,
            clean_env,
            wheel_sha256,
        )

        receipt = {
            "status": "passed",
            "verification_scope": (
                "built wheel installed and exercised in a temporary environment outside "
                "the source tree; dependency metadata checked and runtime NumPy supplied "
                "by the verification environment"
            ),
            # Patch releases differ across otherwise equivalent CI runners. Record
            # the supported interpreter line so regenerating this checked-in receipt
            # cannot make a validated source tree dirty solely because 3.12.x moved.
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "wheel": {
                "filename": wheel.name,
                "sha256": wheel_sha256,
                "member_count": wheel_member_count,
                "required_runtime_files": list(REQUIRED_WHEEL_MEMBERS),
                "source_date_epoch": build_env["SOURCE_DATE_EPOCH"],
            },
            "source_distribution": source_distribution,
            "installed_product": {
                "model_artifact_id": prediction["model"]["artifact_id"],
                "model_artifact_sha256": artifact_sha256,
                "alignment_adapter_id": screening_adapter["adapter_id"],
                "alignment_adapter_sha256": screening_adapter["sha256"],
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
                "packaged_activity_schema": "passed",
                "packaged_source_manifest": "passed",
                "packaged_structure_seed_count": len(structure_seeds),
                "citation_and_license_notices": "passed",
            },
            "scientific_boundaries": {
                "holdout_labels_accessed": False,
                "p1_p15_outcomes_accessed": False,
                "structure_inference_run": False,
                "endpoint": "cell-based cAMP EC50 functional potency, not binding affinity",
            },
        }

        if args.artifact_output_dir:
            artifact_output_dir = args.artifact_output_dir
            if not artifact_output_dir.is_absolute():
                artifact_output_dir = repository / artifact_output_dir
            if artifact_output_dir.exists() and any(artifact_output_dir.iterdir()):
                raise RuntimeError(
                    "Artifact output directory must be empty: "
                    f"{artifact_output_dir}"
                )
            artifact_output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wheel, artifact_output_dir / wheel.name)
            shutil.copy2(
                source_distribution_path,
                artifact_output_dir / source_distribution_path.name,
            )

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        "distribution verification passed: wheel and complete source distribution, "
        "installed resources, JSON/CSV prediction, guarded screening, and web smoke test"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
