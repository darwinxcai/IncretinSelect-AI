from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_github.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_github", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bootstrap_github = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap_github)


class GitHubPublicationTests(unittest.TestCase):
    def test_default_target_is_the_intended_public_repository(self) -> None:
        command = bootstrap_github.create_command(
            bootstrap_github.DEFAULT_REPOSITORY,
            bootstrap_github.DEFAULT_DESCRIPTION,
        )
        self.assertEqual(command[:4], ["gh", "repo", "create", "darwinxcai/IncretinSelect-AI"])
        self.assertIn("--public", command)
        self.assertIn("--push", command)
        self.assertIn("--remote=origin", command)

    def test_repository_name_must_be_an_explicit_owner_and_name(self) -> None:
        valid = bootstrap_github.validate_repository_name("darwinxcai/IncretinSelect-AI")
        self.assertEqual(valid, "darwinxcai/IncretinSelect-AI")
        for invalid in (
            "IncretinSelect-AI",
            "https://github.com/darwinxcai/IncretinSelect-AI",
            "darwinxcai/repo;echo-danger",
            "darwinxcai/space name",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(bootstrap_github.PublicationError):
                    bootstrap_github.validate_repository_name(invalid)

    def test_pages_commands_are_restricted_to_the_intended_repository(self) -> None:
        repository = bootstrap_github.DEFAULT_REPOSITORY
        self.assertEqual(
            bootstrap_github.pages_create_command(repository),
            [
                "gh",
                "api",
                "--method",
                "POST",
                "repos/darwinxcai/IncretinSelect-AI/pages",
                "-f",
                "build_type=workflow",
            ],
        )
        self.assertEqual(
            bootstrap_github.pages_workflow_command(repository),
            [
                "gh",
                "workflow",
                "run",
                "pages.yml",
                "--repo",
                "darwinxcai/IncretinSelect-AI",
            ],
        )


if __name__ == "__main__":
    unittest.main()
