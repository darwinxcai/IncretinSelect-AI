#!/usr/bin/env python3
"""Audit whether IncretinSelect-AI is locally ready and publicly verifiable."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REQUIRED_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/pages.yml",
    "CHANGELOG.md",
    "CITATION.cff",
    "LICENSE",
    "PUBLISHING.md",
    "README.md",
    "RELEASE_READINESS.md",
    "docs/app.mjs",
    "docs/assets/incretin_ridge_v1.json",
    "docs/index.html",
    "examples/candidate_screening/README.md",
    "examples/candidate_screening/candidates.csv",
    "examples/candidate_screening/screened_dual.csv",
    "examples/candidate_screening/screening_receipt.json",
    "reports/EXTERNAL_EVALUATION.md",
    "reports/distribution_verification.json",
    "reports/release_readiness.json",
    "reports/static_demo_verification.json",
    "scripts/audit_release_readiness.py",
    "scripts/verify_static_demo.py",
)
FORBIDDEN_TRACKED_PATTERNS = (
    re.compile(r"^data/raw/(?!README\.md$)"),
    re.compile(r"^data/derived/prospective_holdout\.json$"),
    re.compile(r"\.(xlsx|xls|pkl|pickle)$", re.IGNORECASE),
)
PUBLIC_URL_PATTERN = re.compile(
    r"^https://github\.com/darwinxcai/IncretinSelect-AI/?$", re.IGNORECASE
)
CI_URL_PATTERN = re.compile(
    r"^https://github\.com/darwinxcai/IncretinSelect-AI/actions/runs/\d+/?$",
    re.IGNORECASE,
)
DEMO_URL_PATTERN = re.compile(
    r"^https://darwinxcai\.github\.io/IncretinSelect-AI/?$", re.IGNORECASE
)
MINIMUM_RELEASE_TESTS = 82


class ReadinessError(RuntimeError):
    """Raised when the repository cannot be audited safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check local release evidence and, only when supplied, explicit public "
            "repository/CI/fresh-clone evidence."
        )
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--as-of", help="Optional YYYY-MM-DD evidence date")
    parser.add_argument("--public-repository-url")
    parser.add_argument("--public-demo-url")
    parser.add_argument("--ci-run-url")
    parser.add_argument(
        "--fresh-clone-release-check",
        action="store_true",
        help="Assert that make release-check passed in a separately cloned public checkout.",
    )
    parser.add_argument(
        "--require-public",
        action="store_true",
        help="Return nonzero unless all three public-verification gates are evidenced.",
    )
    return parser.parse_args()


def read_project_version(project_root: Path) -> str:
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if match is None:
        raise ReadinessError("pyproject.toml has no project version")
    return match.group(1)


def read_citation_version(project_root: Path) -> str:
    text = (project_root / "CITATION.cff").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*([^\s]+)", text, flags=re.MULTILINE)
    if match is None:
        raise ReadinessError("CITATION.cff has no version")
    return match.group(1)


def tracked_files(project_root: Path) -> list[str]:
    if not (project_root / ".git").exists():
        return [
            path.relative_to(project_root).as_posix()
            for path in project_root.rglob("*")
            if path.is_file()
            and not any(
                part in {".venv", "__pycache__", "build", "dist"}
                for part in path.relative_to(project_root).parts
            )
        ]
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ReadinessError("git ls-files failed")
    return [line for line in completed.stdout.splitlines() if line]


def gate(name: str, status: str, evidence: str) -> dict[str, str]:
    return {"name": name, "status": status, "evidence": evidence}


def audit_local(project_root: Path) -> list[dict[str, str]]:
    missing = [name for name in REQUIRED_FILES if not (project_root / name).is_file()]
    required_status = "pass" if not missing else "fail"
    required_evidence = (
        "all required release files present" if not missing else f"missing: {missing}"
    )

    project_version = read_project_version(project_root)
    citation_version = read_citation_version(project_root)
    changelog = (project_root / "CHANGELOG.md").read_text(encoding="utf-8")
    version_aligned = project_version == citation_version and f"[{project_version}]" in changelog

    tracked = tracked_files(project_root)
    forbidden = [
        name
        for name in tracked
        if any(pattern.search(name) for pattern in FORBIDDEN_TRACKED_PATTERNS)
    ]

    receipt_path = project_root / "reports/distribution_verification.json"
    receipt: dict[str, Any] = {}
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    installed_product = receipt.get("installed_product", {})
    example_screening_path = (
        project_root / "examples" / "candidate_screening" / "screened_dual.csv"
    )
    example_screening_sha256 = (
        hashlib.sha256(example_screening_path.read_bytes()).hexdigest()
        if example_screening_path.is_file()
        else None
    )
    expected_wheel = f"incretinselect_ai-{project_version}-py3-none-any.whl"
    distribution_pass = (
        receipt.get("status") == "passed"
        and receipt.get("wheel", {}).get("filename") == expected_wheel
        and installed_product.get("software_version") == project_version
        and installed_product.get("screening_objective") == "dual"
        and installed_product.get("screening_rows") == 4
        and installed_product.get("screening_ranked_rows") == 3
        and installed_product.get("screening_out_of_scope_rows") == 1
        and installed_product.get("screening_output_sha256") == example_screening_sha256
    )
    receipt_boundaries = receipt.get("scientific_boundaries", {})
    safe_receipt = (
        receipt_boundaries.get("holdout_labels_accessed") is False
        and receipt_boundaries.get("p1_p15_outcomes_accessed") is False
        and receipt_boundaries.get("structure_inference_run") is False
    )

    static_receipt_path = project_root / "reports/static_demo_verification.json"
    static_receipt: dict[str, Any] = {}
    if static_receipt_path.is_file():
        static_receipt = json.loads(static_receipt_path.read_text(encoding="utf-8"))
    static_boundaries = static_receipt.get("scientific_boundaries", {})
    static_privacy = static_receipt.get("privacy", {})
    static_demo_pass = (
        static_receipt.get("status") == "passed"
        and static_receipt.get("artifact", {}).get("source_and_demo_bytes_identical") is True
        and static_receipt.get("browser_python_parity", {}).get("applicability_exact") is True
        and static_privacy.get("external_api") is False
        and static_privacy.get("local_file_import") is True
        and static_privacy.get("outbound_sequence_transmission") is False
        and static_boundaries.get("holdout_labels_accessed") is False
        and static_boundaries.get("structure_inference_run") is False
    )

    readme = (project_root / "README.md").read_text(encoding="utf-8").lower()
    publishing = (project_root / "PUBLISHING.md").read_text(encoding="utf-8").lower()
    boundaries = all(
        phrase in readme + "\n" + publishing
        for phrase in (
            "ec50",
            "not binding affinity",
            "mixed",
            "p1–p15",
        )
    )

    workflow = (project_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci_contract = all(
        token in workflow
        for token in (
            'python-version: ["3.10", "3.12"]',
            "make test",
            "make product-smoke",
            "make static-demo",
            "make release-check",
        )
    )

    return [
        gate("required_release_files", required_status, required_evidence),
        gate(
            "version_alignment",
            "pass" if version_aligned else "fail",
            (
                f"pyproject={project_version}; citation={citation_version}; "
                f"changelog entry={f'[{project_version}]' in changelog}"
            ),
        ),
        gate(
            "public_bundle_hygiene",
            "pass" if not forbidden else "fail",
            "no raw workbook or reserved holdout-label mirror tracked"
            if not forbidden
            else f"forbidden tracked files: {forbidden}",
        ),
        gate(
            "built_distribution",
            "pass" if distribution_pass and safe_receipt else "fail",
            (
                "checked-in wheel receipt passed prediction, guarded screening, "
                "and browser checks; no holdout outcomes or structure inference accessed"
            )
            if distribution_pass and safe_receipt
            else "distribution receipt is missing, failed, or violates the access boundary",
        ),
        gate(
            "zero_install_browser_demo",
            "pass" if static_demo_pass else "fail",
            (
                "static model bytes match; browser/Python parity and local-only privacy pass"
                if static_demo_pass
                else "static-demo receipt is missing, failed, stale, or violates boundaries"
            ),
        ),
        gate(
            "scientific_claim_boundaries",
            "pass" if boundaries else "fail",
            "reader docs retain EC50-not-affinity, mixed-result, and P1–P15 boundaries",
        ),
        gate(
            "ci_contract",
            "pass" if ci_contract else "fail",
            (
                "Python 3.10/3.12 CI runs tests, product smoke, static-demo parity, "
                "and built-distribution verification"
            ),
        ),
    ]


def audit_public(
    public_repository_url: str | None,
    public_demo_url: str | None,
    ci_run_url: str | None,
    fresh_clone_release_check: bool,
) -> list[dict[str, str]]:
    repo_ok = bool(public_repository_url and PUBLIC_URL_PATTERN.fullmatch(public_repository_url))
    demo_ok = bool(public_demo_url and DEMO_URL_PATTERN.fullmatch(public_demo_url))
    ci_ok = bool(ci_run_url and CI_URL_PATTERN.fullmatch(ci_run_url))
    return [
        gate(
            "public_repository",
            "pass" if repo_ok else "blocked",
            public_repository_url
            if repo_ok
            else "no verified public darwinxcai/IncretinSelect-AI URL supplied",
        ),
        gate(
            "public_browser_demo",
            "pass" if demo_ok else "blocked",
            public_demo_url
            if demo_ok
            else "no verified darwinxcai.github.io/IncretinSelect-AI demo URL supplied",
        ),
        gate(
            "remote_ci",
            "pass" if ci_ok else "blocked",
            ci_run_url if ci_ok else "no verified GitHub Actions run URL supplied",
        ),
        gate(
            "fresh_public_clone",
            "pass" if fresh_clone_release_check else "blocked",
            "make release-check passed in a separately cloned public checkout"
            if fresh_clone_release_check
            else "fresh public-clone release check not yet attested",
        ),
    ]


def audit_publication_receipt(project_root: Path) -> list[dict[str, str]]:
    """Audit checked-in public-release evidence without making network calls."""

    receipt_path = project_root / "reports" / "publication_receipt.json"
    if not receipt_path.is_file():
        return [
            gate("public_repository", "blocked", "publication receipt is missing"),
            gate("public_browser_demo", "blocked", "publication receipt is missing"),
            gate("remote_ci", "blocked", "publication receipt is missing"),
            gate("fresh_public_clone", "blocked", "publication receipt is missing"),
        ]

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    public = receipt.get("public_release", {})
    expected_tests = receipt.get("local_release", {}).get("tests_passed")
    receipt_version_ok = receipt.get("version") == read_project_version(project_root)
    test_evidence_current = bool(
        isinstance(expected_tests, int) and expected_tests >= MINIMUM_RELEASE_TESTS
    )

    repository_url = public.get("repository_url")
    repository_ok = bool(
        isinstance(repository_url, str)
        and PUBLIC_URL_PATTERN.fullmatch(repository_url)
        and public.get("source_tree_match") is True
        and receipt_version_ok
    )

    demo = public.get("demo", {})
    demo_url = demo.get("expected_url")
    demo_status = demo.get("status")
    demo_ok = bool(
        isinstance(demo_url, str)
        and DEMO_URL_PATTERN.fullmatch(demo_url)
        and demo_status in {"deployed", "passed"}
        and receipt_version_ok
    )

    ci = public.get("ci", {})
    ci_url = ci.get("run_url")
    ci_conclusion = ci.get("run_api_conclusion")
    matrix_ok = all(
        ci.get(key, {}).get("status") == "passed"
        and ci.get(key, {}).get("tests_passed") == expected_tests
        for key in ("python_3_10", "python_3_12")
    ) and test_evidence_current
    ci_ok = bool(
        isinstance(ci_url, str)
        and CI_URL_PATTERN.fullmatch(ci_url)
        and matrix_ok
        and ci.get("overall") in {"passed", "success"}
        and ci_conclusion == "success"
        and receipt_version_ok
    )

    clone = public.get("fresh_public_clone", {})
    clone_checks = clone.get("checks", {})
    clone_ok = bool(
        clone.get("status") == "passed"
        and clone_checks.get("worktree_clean_after_checks") is True
        and clone_checks.get("tests_passed") == expected_tests
        and test_evidence_current
        and clone_checks.get("ruff") == "passed"
        and clone_checks.get("product_smoke") == "passed"
        and clone_checks.get("built_distribution") == "passed"
        and clone_checks.get("static_demo_parity_cases") == 12
        and receipt_version_ok
    )

    if ci_ok:
        ci_evidence = str(ci_url)
    elif matrix_ok and ci_url:
        ci_evidence = (
            f"both Python matrix jobs passed, but the workflow conclusion is "
            f"{ci_conclusion!r}; clean top-level CI is still required: {ci_url}"
        )
    else:
        ci_evidence = "publication receipt has no successful two-version CI run"

    return [
        gate(
            "public_repository",
            "pass" if repository_ok else "blocked",
            str(repository_url)
            if repository_ok
            else "publication receipt does not verify the intended public source tree",
        ),
        gate(
            "public_browser_demo",
            "pass" if demo_ok else "blocked",
            str(demo_url)
            if demo_ok
            else f"browser demo status is {demo_status!r}; a deployed demo is required",
        ),
        gate("remote_ci", "pass" if ci_ok else "blocked", ci_evidence),
        gate(
            "fresh_public_clone",
            "pass" if clone_ok else "blocked",
            f"{expected_tests} tests, Ruff, product smoke, distribution, and 12 browser parity cases passed in a clean public clone"
            if clone_ok
            else "publication receipt does not attest the complete clean-clone check",
        ),
    ]


def build_report(
    project_root: Path,
    *,
    as_of: str | None,
    public_repository_url: str | None,
    public_demo_url: str | None,
    ci_run_url: str | None,
    fresh_clone_release_check: bool,
) -> dict[str, Any]:
    local_gates = audit_local(project_root)
    explicit_public_gates = audit_public(
        public_repository_url, public_demo_url, ci_run_url, fresh_clone_release_check
    )
    receipt_public_gates = audit_publication_receipt(project_root)
    explicit_inputs = (
        public_repository_url,
        public_demo_url,
        ci_run_url,
        fresh_clone_release_check,
    )
    public_gates = [
        explicit if supplied else receipt
        for explicit, receipt, supplied in zip(
            explicit_public_gates,
            receipt_public_gates,
            explicit_inputs,
            strict=True,
        )
    ]
    local_ready = all(item["status"] == "pass" for item in local_gates)
    public_verified = all(item["status"] == "pass" for item in public_gates)
    if not local_ready:
        decision = "LOCAL_RELEASE_BLOCKED"
    elif not public_verified:
        decision = "LOCAL_RELEASE_READY_PUBLICATION_BLOCKED"
    else:
        decision = "PUBLIC_RELEASE_VERIFIED"
    return {
        "schema_version": 1,
        "as_of": as_of,
        "project": "IncretinSelect-AI",
        "version": read_project_version(project_root),
        "decision": decision,
        "local_release_ready": local_ready,
        "public_release_verified": public_verified,
        "local_gates": local_gates,
        "public_gates": public_gates,
        "scientific_scope": {
            "endpoint": "cell-based cAMP EC50 functional potency",
            "affinity_claim": False,
            "overall_external_superiority_claim": False,
            "structure_inference_claim": False,
            "p1_p15_reused_for_tuning": False,
        },
    }


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    report = build_report(
        project_root,
        as_of=args.as_of,
        public_repository_url=args.public_repository_url,
        public_demo_url=args.public_demo_url,
        ci_run_url=args.ci_run_url,
        fresh_clone_release_check=args.fresh_clone_release_check,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_output:
        output = args.json_output
        if not output.is_absolute():
            output = project_root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if not report["local_release_ready"]:
        return 2
    if args.require_public and not report["public_release_verified"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
