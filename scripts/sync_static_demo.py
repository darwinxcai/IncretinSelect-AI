#!/usr/bin/env python3
"""Synchronize the browser demo with the authoritative frozen model artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the frozen model into docs and write a deterministic demo manifest."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the checked-in demo assets are stale.",
    )
    return parser.parse_args()


def expected_assets(root: Path) -> tuple[bytes, bytes]:
    source = root / "src" / "incretinselect" / "assets" / "incretin_ridge_v1.json"
    artifact = source.read_bytes()
    digest = hashlib.sha256(artifact).hexdigest()
    manifest = {
        "artifact_id": "incretinselect_aligned_ridge_v1",
        "artifact_path": "assets/incretin_ridge_v1.json",
        "artifact_sha256": digest,
        "artifact_version": "1.0.0",
        "labels_included": False,
        "schema_version": 1,
        "sequence_upload": False,
        "structure_inference": False,
    }
    rendered_manifest = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    return artifact, rendered_manifest


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    expected_model, expected_manifest = expected_assets(root)
    model_path = root / "docs" / "assets" / "incretin_ridge_v1.json"
    manifest_path = root / "docs" / "demo_manifest.json"
    if args.check:
        if not model_path.is_file() or model_path.read_bytes() != expected_model:
            raise SystemExit("browser demo model is stale; run scripts/sync_static_demo.py")
        if not manifest_path.is_file() or manifest_path.read_bytes() != expected_manifest:
            raise SystemExit("browser demo manifest is stale; run scripts/sync_static_demo.py")
        print("static demo assets match the authoritative frozen model")
        return 0
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(expected_model)
    manifest_path.write_bytes(expected_manifest)
    print("static demo assets synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
