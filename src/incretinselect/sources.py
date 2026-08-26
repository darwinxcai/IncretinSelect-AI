"""Load, verify, and fetch commit-pinned public source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.request import urlopen


class SourceManifestError(ValueError):
    """Raised when source provenance is incomplete or inconsistent."""


def load_source_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("manifest_version") != 1:
        raise SourceManifestError("Only source manifest version 1 is supported")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SourceManifestError("Manifest must contain a non-empty 'sources' list")
    ids = [source.get("id") for source in sources]
    if any(not source_id for source_id in ids) or len(ids) != len(set(ids)):
        raise SourceManifestError("Source IDs must be present and unique")
    return manifest


def get_source(manifest: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in manifest["sources"]:
        if source["id"] == source_id:
            return source
    raise SourceManifestError(f"Unknown source ID: {source_id}")


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: str | Path, expected_sha256: str) -> bool:
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise SourceManifestError(f"Invalid SHA-256 value: {expected_sha256!r}")
    return sha256_file(path) == expected


def _open_url(url: str) -> BinaryIO:
    return urlopen(url, timeout=60)  # noqa: S310 - URLs come from reviewed manifest


def fetch_source_files(
    manifest: dict[str, Any],
    source_id: str,
    output_dir: str | Path,
    roles: set[str] | None = None,
    opener: Callable[[str], BinaryIO] = _open_url,
) -> list[dict[str, str]]:
    """Download selected files atomically and verify their manifest checksums."""

    source = get_source(manifest, source_id)
    files = source.get("files")
    if not files:
        raise SourceManifestError(f"Source {source_id!r} has no downloadable files")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    selected = [item for item in files if roles is None or item.get("role") in roles]
    if not selected:
        raise SourceManifestError("No source files matched the requested role(s)")

    results: list[dict[str, str]] = []
    for item in selected:
        for required in ("path", "download_url", "sha256"):
            if not item.get(required):
                raise SourceManifestError(
                    f"File entry for {source_id!r} is missing {required!r}"
                )
        output_path = destination / Path(item["path"]).name
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with opener(item["download_url"]) as response:
                    shutil.copyfileobj(response, temporary)
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise

        if not verify_checksum(temporary_path, item["sha256"]):
            temporary_path.unlink(missing_ok=True)
            raise SourceManifestError(
                f"Checksum mismatch for {item['download_url']}; file was not installed"
            )
        temporary_path.replace(output_path)
        results.append(
            {
                "role": item["role"],
                "path": str(output_path),
                "sha256": item["sha256"],
                "status": "verified",
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="data/manifests/sources.json", help="Source manifest JSON"
    )
    parser.add_argument("--source", required=True, help="Source ID to download")
    parser.add_argument(
        "--role",
        action="append",
        dest="roles",
        help="Download only this file role; repeat for multiple roles",
    )
    parser.add_argument("--output-dir", required=True, help="Destination directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_source_manifest(args.manifest)
    results = fetch_source_files(
        manifest,
        source_id=args.source,
        output_dir=args.output_dir,
        roles=set(args.roles) if args.roles else None,
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

