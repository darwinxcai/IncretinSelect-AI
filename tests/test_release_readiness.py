from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

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

    def test_public_evidence_is_blocked_when_not_supplied(self) -> None:
        gates = audit_release_readiness.audit_public(None, None, None, False)
        self.assertEqual({item["status"] for item in gates}, {"blocked"})

    def test_source_archive_without_git_uses_release_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("release", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "ignored.xlsx").write_text("build", encoding="utf-8")
            self.assertEqual(audit_release_readiness.tracked_files(root), ["README.md"])

    def test_public_evidence_is_restricted_to_the_intended_repository(self) -> None:
        valid = audit_release_readiness.audit_public(
            "https://github.com/darwinxcai/IncretinSelect-AI",
            "https://darwinxcai.github.io/IncretinSelect-AI/",
            "https://github.com/darwinxcai/IncretinSelect-AI/actions/runs/123456",
            True,
        )
        self.assertEqual({item["status"] for item in valid}, {"pass"})

        wrong_owner = audit_release_readiness.audit_public(
            "https://github.com/not-darwin/IncretinSelect-AI",
            "https://not-darwin.github.io/IncretinSelect-AI/",
            "https://github.com/not-darwin/IncretinSelect-AI/actions/runs/123456",
            True,
        )
        self.assertEqual(wrong_owner[0]["status"], "blocked")
        self.assertEqual(wrong_owner[1]["status"], "blocked")
        self.assertEqual(wrong_owner[2]["status"], "blocked")

    def test_report_preserves_scientific_boundaries(self) -> None:
        report = audit_release_readiness.build_report(
            PROJECT_ROOT,
            as_of="2026-08-26",
            public_repository_url=None,
            public_demo_url=None,
            ci_run_url=None,
            fresh_clone_release_check=False,
        )
        self.assertEqual(report["decision"], "LOCAL_RELEASE_READY_PUBLICATION_BLOCKED")
        self.assertTrue(report["local_release_ready"])
        self.assertFalse(report["public_release_verified"])
        self.assertFalse(report["scientific_scope"]["affinity_claim"])
        self.assertFalse(report["scientific_scope"]["p1_p15_reused_for_tuning"])


if __name__ == "__main__":
    unittest.main()
