from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "audit_release_readiness.py"
SPEC = importlib.util.spec_from_file_location("audit_release_readiness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit_release_readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_release_readiness)


class ReleaseReadinessTests(unittest.TestCase):
    def test_current_tree_passes_every_local_gate(self) -> None:
        gates = audit_release_readiness.audit_local(PROJECT_ROOT)
        self.assertTrue(gates)
        self.assertEqual({item["status"] for item in gates}, {"pass"})

    def test_pages_deployment_requires_current_successful_ci(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/pages.yml").read_text(
            encoding="utf-8"
        )
        for token in (
            "workflow_run:",
            "workflows: [CI]",
            "types: [completed]",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_repository.full_name == github.repository",
            "github.event.workflow_run.head_sha == github.sha",
            "ref: ${{ github.event_name == 'workflow_run' && "
            "github.event.workflow_run.head_sha || github.sha }}",
            "Require validated SHA to remain current",
            "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}",
            "VALIDATED_SHA: ${{ github.event_name == 'workflow_run' && "
            "github.event.workflow_run.head_sha || github.sha }}",
            "git fetch --no-tags origin",
            'checked_out_sha="$(git rev-parse HEAD)"',
            'current_default_sha="$(git rev-parse '
            '"refs/remotes/origin/${DEFAULT_BRANCH}")"',
            'if [ "${checked_out_sha}" != "${VALIDATED_SHA}" ]; then',
            'if [ "${current_default_sha}" != "${VALIDATED_SHA}" ]; then',
            "needs.manual_ci.result == 'success'",
            'python-version: ["3.10", "3.12"]',
            "python -m ruff check .",
            "make test",
            "make product-smoke",
            "make static-demo",
            "make release-check",
            "make release-readiness",
        ):
            self.assertIn(token, workflow)
        self.assertNotIn("\n  push:", workflow)
        workflow_permissions = workflow.split("jobs:", maxsplit=1)[0]
        self.assertNotIn("pages: write", workflow_permissions)
        self.assertNotIn("id-token: write", workflow_permissions)
        verify_job = workflow.split("\n  verify:", maxsplit=1)[1].split(
            "\n  deploy:", maxsplit=1
        )[0]
        deploy_job = workflow.split("\n  deploy:", maxsplit=1)[1]
        self.assertNotIn("actions/configure-pages@", verify_job)
        self.assertIn("actions/configure-pages@", deploy_job)
        self.assertIn("if: always() && needs.verify.result == 'success'", deploy_job)
        self.assertIn("permissions:\n      pages: write\n      id-token: write", deploy_job)

    def test_release_workflows_pin_official_actions_to_commit_shas(self) -> None:
        checked, violations = audit_release_readiness.audit_official_action_pins(
            PROJECT_ROOT
        )
        self.assertGreater(checked, 0)
        self.assertEqual(violations, [])

    def test_mutable_official_action_tag_fails_the_release_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in audit_release_readiness.RELEASE_WORKFLOW_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                workflow = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                target.write_text(workflow, encoding="utf-8")

            ci_path = root / ".github/workflows/ci.yml"
            ci_workflow = ci_path.read_text(encoding="utf-8")
            mutable_workflow, replacements = re.subn(
                r"actions/checkout@[0-9a-fA-F]{40}",
                "actions/checkout@v4",
                ci_workflow,
                count=1,
            )
            self.assertEqual(replacements, 1)
            ci_path.write_text(
                mutable_workflow,
                encoding="utf-8",
            )
            checked, violations = (
                audit_release_readiness.audit_official_action_pins(root)
            )

        self.assertGreater(checked, 0)
        self.assertEqual(len(violations), 1)
        self.assertIn("actions/checkout@v4", violations[0])
        self.assertIn("40-hex commit SHA", violations[0])

        with mock.patch.object(
            audit_release_readiness,
            "audit_official_action_pins",
            return_value=(checked, violations),
        ):
            gates = audit_release_readiness.audit_local(PROJECT_ROOT)
        by_name = {item["name"]: item for item in gates}
        self.assertEqual(by_name["workflow_action_pinning"]["status"], "fail")
        self.assertIn(
            "actions/checkout@v4",
            by_name["workflow_action_pinning"]["evidence"],
        )

    def test_public_evidence_is_blocked_when_not_supplied(self) -> None:
        gates = audit_release_readiness.audit_public(None, None, None, False)
        self.assertEqual({item["status"] for item in gates}, {"blocked"})

    def test_stale_publication_receipt_cannot_verify_a_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports").mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\nname = "incretinselect-ai"\nversion = "9.9.9"\n',
                encoding="utf-8",
            )
            receipt = json.loads(
                (PROJECT_ROOT / "reports/publication_receipt.json").read_text(
                    encoding="utf-8"
                )
            )
            receipt["version"] = "0.5.0"
            (root / "reports/publication_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            gates = audit_release_readiness.audit_publication_receipt(root)
        by_name = {item["name"]: item for item in gates}
        self.assertEqual(by_name["public_repository"]["status"], "blocked")
        self.assertEqual(by_name["remote_ci"]["status"], "blocked")
        self.assertEqual(by_name["fresh_public_clone"]["status"], "blocked")

    def test_release_payload_hash_detects_tracked_drift_but_excludes_attestations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "reports").mkdir()
            (root / "src/model.py").write_text("value = 1\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "example"\nversion = "1.0.0"\n',
                encoding="utf-8",
            )
            for excluded in audit_release_readiness.RELEASE_PAYLOAD_EXCLUDED_PATHS:
                path = root / excluded
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("evidence one\n", encoding="utf-8")

            first = audit_release_readiness.release_payload_evidence(root)
            second = audit_release_readiness.release_payload_evidence(root)
            self.assertEqual(first, second)

            for excluded in audit_release_readiness.RELEASE_PAYLOAD_EXCLUDED_PATHS:
                (root / excluded).write_text("evidence two\n", encoding="utf-8")
            self.assertEqual(
                audit_release_readiness.release_payload_evidence(root),
                first,
            )

            (root / "src/model.py").write_text("value = 2\n", encoding="utf-8")
            content_drift = audit_release_readiness.release_payload_evidence(root)
            self.assertNotEqual(content_drift["sha256"], first["sha256"])
            self.assertEqual(content_drift["file_count"], first["file_count"])

            (root / "src/model.py").rename(root / "src/predictor.py")
            renamed = audit_release_readiness.release_payload_evidence(root)
            self.assertNotEqual(renamed["sha256"], content_drift["sha256"])
            self.assertEqual(renamed["file_count"], content_drift["file_count"])

    def test_same_version_source_drift_blocks_every_public_receipt_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports").mkdir()
            (root / "src").mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\nname = "incretinselect-ai"\nversion = "9.9.9"\n',
                encoding="utf-8",
            )
            source = root / "src/inference.py"
            source.write_text("MODEL = 'released'\n", encoding="utf-8")
            receipt = json.loads(
                (PROJECT_ROOT / "reports/publication_receipt.json").read_text(
                    encoding="utf-8"
                )
            )
            receipt["version"] = "9.9.9"
            expected_tests = audit_release_readiness.MINIMUM_RELEASE_TESTS
            receipt["local_release"]["tests_passed"] = expected_tests
            for key in ("python_3_10", "python_3_12"):
                receipt["public_release"]["ci"][key]["tests_passed"] = expected_tests
            receipt["public_release"]["fresh_public_clone"]["checks"][
                "tests_passed"
            ] = expected_tests
            receipt["local_release"]["release_payload"] = (
                audit_release_readiness.release_payload_evidence(root)
            )
            (root / "reports/publication_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )

            before = audit_release_readiness.audit_publication_receipt(root)
            self.assertEqual({item["status"] for item in before}, {"pass"})

            source.write_text("MODEL = 'drifted'\n", encoding="utf-8")
            after = audit_release_readiness.audit_publication_receipt(root)

        self.assertEqual({item["status"] for item in after}, {"blocked"})
        self.assertTrue(
            all("current source payload" in item["evidence"] for item in after)
        )

    def test_source_archive_without_git_uses_release_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("release", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "ignored.xlsx").write_text("build", encoding="utf-8")
            self.assertEqual(audit_release_readiness.tracked_files(root), ["README.md"])

    def test_public_evidence_is_restricted_to_the_intended_repository(self) -> None:
        payload_sha256 = "a" * 64
        valid = audit_release_readiness.audit_public(
            "https://github.com/darwinxcai/IncretinSelect-AI",
            "https://darwinxcai.github.io/IncretinSelect-AI/",
            "https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/123456",
            True,
            payload_sha256,
            payload_sha256,
        )
        self.assertEqual({item["status"] for item in valid}, {"pass"})

        wrong_owner = audit_release_readiness.audit_public(
            "https://github.com/not-darwin/IncretinSelect-AI",
            "https://not-darwin.github.io/IncretinSelect-AI/",
            "https://github.com/not-darwin/IncretinSelect-AI/actions/runs/123456",
            True,
            payload_sha256,
            payload_sha256,
        )
        self.assertEqual(wrong_owner[0]["status"], "blocked")
        self.assertEqual(wrong_owner[1]["status"], "blocked")
        self.assertEqual(wrong_owner[2]["status"], "blocked")

        stale_payload = audit_release_readiness.audit_public(
            "https://github.com/darwinxcai/IncretinSelect-AI",
            "https://darwinxcai.github.io/IncretinSelect-AI/",
            "https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/123456",
            True,
            payload_sha256,
            "b" * 64,
        )
        self.assertEqual({item["status"] for item in stale_payload}, {"blocked"})
        self.assertTrue(
            all(
                "not bound to the current release payload" in item["evidence"]
                for item in stale_payload
            )
        )

    def test_explicit_public_inputs_cannot_bypass_payload_binding(self) -> None:
        payload_sha256 = "a" * 64
        payload = {
            "schema_version": 1,
            "hash_contract": "canonical-path-content-manifest-sha256-v1",
            "sha256": payload_sha256,
            "file_count": 1,
            "excluded_paths": [],
        }
        local_gate = [{"name": "fixture", "status": "pass", "evidence": "fixture"}]
        receipt_gates = [
            {"name": name, "status": "blocked", "evidence": "fixture"}
            for name in (
                "public_repository",
                "public_browser_demo",
                "remote_ci",
                "fresh_public_clone",
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "incretinselect-ai"\nversion = "9.9.9"\n',
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    audit_release_readiness,
                    "release_payload_evidence",
                    return_value=payload,
                ),
                mock.patch.object(
                    audit_release_readiness,
                    "audit_local",
                    return_value=local_gate,
                ),
                mock.patch.object(
                    audit_release_readiness,
                    "audit_publication_receipt",
                    return_value=receipt_gates,
                ),
            ):
                report = audit_release_readiness.build_report(
                    root,
                    as_of="2026-08-27",
                    public_repository_url=(
                        "https://github.com/darwinxcai/IncretinSelect-AI"
                    ),
                    public_demo_url=(
                        "https://darwinxcai.github.io/IncretinSelect-AI/"
                    ),
                    ci_run_url=(
                        "https://github.com/darwinxcai/IncretinSelect-AI/"
                        "actions/runs/123456"
                    ),
                    fresh_clone_release_check=True,
                    verified_release_payload_sha256="b" * 64,
                )

        self.assertFalse(report["public_release_verified"])
        self.assertEqual(report["decision"], "LOCAL_RELEASE_READY_PUBLICATION_BLOCKED")
        self.assertEqual({gate["status"] for gate in report["public_gates"]}, {"blocked"})

    def test_report_preserves_scientific_boundaries(self) -> None:
        report = audit_release_readiness.build_report(
            PROJECT_ROOT,
            as_of="2026-08-27",
            public_repository_url=None,
            public_demo_url=None,
            ci_run_url=None,
            fresh_clone_release_check=False,
        )
        self.assertRegex(report["release_payload"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(report["release_payload"]["file_count"], 0)
        self.assertEqual(
            {item["name"] for item in report["public_gates"]},
            {"public_repository", "public_browser_demo", "remote_ci", "fresh_public_clone"},
        )
        self.assertFalse(report["scientific_scope"]["affinity_claim"])
        self.assertFalse(report["scientific_scope"]["p1_p15_reused_for_tuning"])


if __name__ == "__main__":
    unittest.main()
