#!/usr/bin/env python3
"""Safely create and push the public GitHub repository with GitHub CLI."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPOSITORY = "darwinxcai/IncretinSelect-AI"
DEFAULT_DESCRIPTION = (
    "Leakage-resistant benchmark and local app for incretin peptide "
    "functional-potency estimation"
)
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]+$")


class PublicationError(RuntimeError):
    """Raised when publication cannot proceed without risking the wrong repository."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight a public GitHub publication. The default is a non-mutating "
            "dry run; pass --execute to create and push the repository."
        )
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Create the public repository and push main after all checks pass.",
    )
    return parser.parse_args()


def validate_repository_name(repository: str) -> str:
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise PublicationError("Repository must be an explicit owner/name without a URL")
    return repository


def create_command(repository: str, description: str) -> list[str]:
    return [
        "gh",
        "repo",
        "create",
        repository,
        "--public",
        "--source=.",
        "--remote=origin",
        "--push",
        "--description",
        description,
    ]


def pages_create_command(repository: str) -> list[str]:
    return [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repository}/pages",
        "-f",
        "build_type=workflow",
    ]


def pages_workflow_command(repository: str) -> list[str]:
    return ["gh", "workflow", "run", "pages.yml", "--repo", repository]


def run(command: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise PublicationError(
            f"Command failed ({completed.returncode}): {shlex.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def git_output(repository_root: Path, *arguments: str) -> str:
    return run(["git", *arguments], cwd=repository_root).stdout.strip()


def inspect_local_repository(repository_root: Path) -> str:
    if git_output(repository_root, "rev-parse", "--show-toplevel") != str(repository_root):
        raise PublicationError("Run this command from its original Git repository")
    if git_output(repository_root, "branch", "--show-current") != "main":
        raise PublicationError("Publication is allowed only from the main branch")
    if git_output(repository_root, "status", "--porcelain"):
        raise PublicationError("Working tree must be clean before publication")
    remotes = git_output(repository_root, "remote").splitlines()
    if "origin" in remotes:
        raise PublicationError(
            "An origin remote already exists; verify it manually instead of creating a repository"
        )
    return git_output(repository_root, "rev-parse", "HEAD")


def verify_release(repository_root: Path) -> None:
    receipt = repository_root / "reports" / "distribution_verification.json"
    run(
        [
            sys.executable,
            str(repository_root / "scripts" / "verify_distribution.py"),
            "--json-output",
            str(receipt),
        ],
        cwd=repository_root,
    )
    if git_output(repository_root, "status", "--porcelain"):
        raise PublicationError(
            "Release verification changed tracked files; commit the regenerated receipt first"
        )


def verify_remote(repository_root: Path, repository: str) -> str:
    remote = git_output(repository_root, "remote", "get-url", "origin")
    normalized = remote.removesuffix(".git").rstrip("/").lower()
    if not normalized.endswith(repository.lower()):
        raise PublicationError(f"origin does not resolve to the requested repository: {remote}")
    view = run(
        ["gh", "repo", "view", repository, "--json", "nameWithOwner,url,visibility"],
        cwd=repository_root,
    )
    try:
        metadata = json.loads(view.stdout)
    except json.JSONDecodeError as error:
        raise PublicationError("GitHub returned invalid repository metadata") from error
    if metadata.get("nameWithOwner", "").lower() != repository.lower():
        raise PublicationError("GitHub resolved a different repository than requested")
    if metadata.get("visibility") != "PUBLIC":
        raise PublicationError("Created repository is not public")
    url = metadata.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PublicationError("GitHub did not return a valid public repository URL")
    return url


def enable_pages(repository_root: Path, repository: str) -> str:
    run(pages_create_command(repository), cwd=repository_root)
    metadata = run(
        ["gh", "api", f"repos/{repository}/pages"],
        cwd=repository_root,
    )
    try:
        page = json.loads(metadata.stdout)
    except json.JSONDecodeError as error:
        raise PublicationError("GitHub returned invalid Pages metadata") from error
    if page.get("build_type") != "workflow":
        raise PublicationError("GitHub Pages was not configured for Actions deployment")
    url = page.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PublicationError("GitHub did not return a valid Pages URL")
    run(pages_workflow_command(repository), cwd=repository_root)
    return url


def main() -> int:
    args = parse_args()
    repository = validate_repository_name(args.repository)
    repository_root = Path(__file__).resolve().parents[1]
    commit = inspect_local_repository(repository_root)
    command = create_command(repository, args.description)

    print(f"Publication target: {repository}")
    print(f"Exact main commit: {commit}")
    print(f"Planned create/push command: {shlex.join(command)}")
    print(
        "Planned Pages enablement: "
        f"{shlex.join(pages_create_command(repository))}"
    )
    if not args.execute:
        print("dry run passed; no GitHub repository or remote was created")
        return 0

    if shutil.which("gh") is None:
        raise PublicationError("GitHub CLI (gh) is required for --execute")
    verify_release(repository_root)
    run(["gh", "auth", "status"], cwd=repository_root)
    run(command, cwd=repository_root)
    url = verify_remote(repository_root, repository)
    print(f"public repository created and exact commit pushed: {url}")
    try:
        pages_url = enable_pages(repository_root, repository)
    except PublicationError as error:
        print(
            f"repository publication succeeded, but browser-demo activation failed: {error}",
            file=sys.stderr,
        )
        print("The public repository is usable; follow PUBLISHING.md to enable Pages.")
        return 3
    print(f"browser-demo deployment requested: {pages_url}")
    print("Verify both CI matrix jobs and the Pages deployment before citing either URL.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicationError as error:
        print(f"publication blocked: {error}", file=sys.stderr)
        raise SystemExit(2) from error
