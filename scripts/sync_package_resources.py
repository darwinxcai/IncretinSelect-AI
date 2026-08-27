#!/usr/bin/env python3
"""Synchronize repository provenance files into the installed package."""

from __future__ import annotations

import argparse
from pathlib import Path

MIRRORS = {
    "data/manifests/sources.json": "src/incretinselect/resources/sources.json",
    "configs/activity_schema.json": "src/incretinselect/resources/activity_schema.json",
    "configs/structure_targets.csv": "src/incretinselect/resources/structure_targets.csv",
    "CITATION.cff": "src/incretinselect/notices/CITATION.cff",
    "DATA_LICENSE.md": "src/incretinselect/notices/DATA_LICENSE.md",
    "LICENSE": "src/incretinselect/notices/LICENSE",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when a packaged resource is stale",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    stale: list[str] = []
    for source_name, target_name in MIRRORS.items():
        source = root / source_name
        target = root / target_name
        expected = source.read_bytes()
        if target.is_file() and target.read_bytes() == expected:
            continue
        if args.check:
            stale.append(target_name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(expected)
    if stale:
        raise SystemExit(
            "packaged resources are stale; run scripts/sync_package_resources.py: "
            + ", ".join(stale)
        )
    print(
        "packaged resources match the source manifest, validation schemas, "
        "citation, and licenses"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
