#!/usr/bin/env python3
"""Build a checksum-verified P1--P15 prospective holdout from official supplements."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from incretinselect.holdout import (
    build_holdout,
    load_design_sequences,
    load_receptor_replicates,
    load_training_alignment,
)
from incretinselect.sources import load_source_manifest, sha256_file


def manifest_file(manifest: dict, source_id: str, role: str) -> dict:
    source = next(item for item in manifest["sources"] if item["id"] == source_id)
    return next(item for item in source["files"] if item["role"] == role)


def require_checksum(path: Path, expected: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"Checksum mismatch for {path}: expected {expected}, observed {observed}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/manifests/sources.json")
    parser.add_argument("--training", default="data/raw/training_data.xlsx")
    parser.add_argument("--sequences", default="data/raw/source_data_fig5.xlsx")
    parser.add_argument("--glp1r", default="data/raw/glp1r_prospective_ec50.xlsx")
    parser.add_argument("--gcgr", default="data/raw/gcgr_prospective_ec50.xlsx")
    parser.add_argument("--output", default="data/derived/prospective_holdout.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_source_manifest(args.manifest)
    source_id = "puszkarska_2024_prospective_holdout"
    paths = {
        "training": Path(args.training),
        "design_sequences": Path(args.sequences),
        "glp1r_replicates": Path(args.glp1r),
        "gcgr_replicates": Path(args.gcgr),
    }
    for role, path in paths.items():
        manifest_source = "puszkarska_2024_training" if role == "training" else source_id
        require_checksum(path, manifest_file(manifest, manifest_source, role)["sha256"])

    payload = build_holdout(
        load_design_sequences(paths["design_sequences"]),
        load_receptor_replicates(paths["gcgr_replicates"], "GCGR"),
        load_receptor_replicates(paths["glp1r_replicates"], "GLP-1R"),
        load_training_alignment(paths["training"]),
    )
    payload["frozen_on"] = date.today().isoformat()
    payload["source_checksums"] = {role: sha256_file(path) for role, path in paths.items()}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    distances = [record["nearest_training_hamming_distance"] for record in payload["records"]]
    censored = {
        receptor: sum(
            replicate["status"] == "right_censored"
            for record in payload["records"]
            for replicate in record[f"{receptor}_ec50_replicates"]
        )
        for receptor in ("gcgr", "glp1r")
    }
    print(
        json.dumps(
            {
                "output": str(output),
                "holdout_records": payload["holdout_records"],
                "exact_sequence_overlaps": payload["exact_sequence_overlaps"],
                "nearest_training_hamming_distance_min": min(distances),
                "nearest_training_hamming_distance_max": max(distances),
                "right_censored_replicates": censored,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
