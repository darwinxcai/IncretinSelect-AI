#!/usr/bin/env python3
"""Audit training-only sequence thresholds and freeze deterministic outer folds."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from incretinselect.clustering import (
    audit_thresholds,
    load_split_config,
    max_cross_fold_identity,
    peptide_split_rows,
    write_csv,
)
from incretinselect.sources import sha256_file
from incretinselect.training import load_training_records


def _write_audit_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    serializable = []
    for row in rows:
        output = dict(row)
        output["fold_sizes"] = ";".join(str(value) for value in row["fold_sizes"])
        serializable.append(output)
    write_csv(
        path,
        serializable,
        [
            "identity_threshold",
            "pair_edges_at_or_above_threshold",
            "components",
            "singletons",
            "largest_component",
            "largest_component_fraction",
            "fold_sizes",
            "fold_size_ratio",
            "eligible",
        ],
    )


def _markdown(payload: dict[str, Any]) -> str:
    audit_rows = []
    for row in payload["threshold_audit"]:
        selected = " **(selected)**" if row["identity_threshold"] == payload["selected_threshold"] else ""
        audit_rows.append(
            "| {:.2f}{} | {} | {} | {} | {} | {:.3f} | {} |".format(
                row["identity_threshold"],
                selected,
                row["components"],
                row["singletons"],
                row["largest_component"],
                " / ".join(str(value) for value in row["fold_sizes"]),
                row["fold_size_ratio"],
                row["eligible"],
            )
        )
    first, second = payload["maximum_cross_fold_pair"]
    return f"""# Training-only sequence split audit

**Frozen:** {payload['frozen_on']}
**Input:** 125 aligned training sequences; no potency values or P1–P15 labels were
used to select the threshold or assign folds.

## Predeclared rule

For each candidate threshold, sequences are nodes in a graph and an edge joins a
pair whose aligned identity meets the threshold. Connected components remain
intact. Components are placed, largest first, into the currently smallest of
three folds. The selected threshold is the **lowest** candidate that produces at
least nine components and a largest/smallest fold-size ratio no greater than
1.10. Lower thresholds are more conservative against analog leakage, so this
rule selects the most conservative candidate that remains evaluable.

Identity is exact character agreement over alignment columns where at least one
sequence is non-gap; double-gap columns are excluded. The rule is stored in
`configs/sequence_split.json`.

## Threshold audit

| Identity | Components | Singletons | Largest | Fold sizes | Size ratio | Eligible |
|---:|---:|---:|---:|:---:|---:|:---:|
{chr(10).join(audit_rows)}

## Frozen split

- Selected identity threshold: **{payload['selected_threshold']:.2f}**.
- Connected components: **{payload['selected_components']}**.
- Deterministic outer-fold sizes: **{' / '.join(str(value) for value in payload['fold_sizes'])}**.
- Maximum identity observed across two different folds:
  **{payload['maximum_cross_fold_identity']:.4f}** ({first} vs {second}), below
  the 0.85 clustering boundary.
- Frozen assignments: `data/derived/sequence_clusters.csv` and
  `data/derived/outer_folds.csv`.

The connected-component rule prevents any direct pair at or above 0.85 identity
from crossing folds. It does not make these 125 engineered peptides equivalent to
a broad natural-family benchmark; performance must be described as
cluster-held-out generalization within this same-assay design set.

## Reproduce

```bash
python scripts/freeze_sequence_splits.py
```

The command verifies the public training-workbook checksum and fails if the
machine-selected threshold differs from the predeclared frozen value.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", default="data/raw/training_data.xlsx")
    parser.add_argument("--config", default="configs/sequence_split.json")
    parser.add_argument("--manifest", default="data/manifests/sources.json")
    parser.add_argument("--derived-dir", default="data/derived")
    parser.add_argument("--report-json", default="reports/sequence_split_audit.json")
    parser.add_argument("--report-md", default="reports/SEQUENCE_SPLIT_AUDIT.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    training_path = Path(args.training)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    training_source = next(
        source for source in manifest["sources"] if source["id"] == "puszkarska_2024_training"
    )
    training_file = next(item for item in training_source["files"] if item["role"] == "training")
    observed_checksum = sha256_file(training_path)
    if observed_checksum != training_file["sha256"]:
        raise ValueError(
            f"Training checksum mismatch: expected {training_file['sha256']}, "
            f"observed {observed_checksum}"
        )

    config_path = Path(args.config)
    config = load_split_config(config_path)
    records = load_training_records(training_path, expected_records=125)
    sequences = {record.peptide_id: record.aligned_sequence for record in records}
    rule = config["selection_rule"]
    audit, selected, clusters, assignment = audit_thresholds(
        sequences,
        config["candidate_identity_thresholds"],
        config["outer_folds"],
        rule["maximum_fold_size_ratio"],
        rule["minimum_components"],
    )
    expected = float(config["expected_selected_threshold"])
    if abs(selected - expected) > 1e-12:
        raise ValueError(f"Selected threshold {selected} differs from frozen expectation {expected}")

    split_rows = peptide_split_rows(records, clusters, assignment)
    peptide_folds = {row["peptide_id"]: row["outer_fold"] for row in split_rows}
    cross_identity, cross_pair = max_cross_fold_identity(sequences, peptide_folds)
    if cross_identity + 1e-12 >= selected:
        raise ValueError("A cross-fold pair violates the selected identity threshold")

    derived = Path(args.derived_dir)
    clusters_path = derived / "sequence_clusters.csv"
    folds_path = derived / "outer_folds.csv"
    threshold_path = derived / "cluster_threshold_audit.csv"
    write_csv(
        clusters_path,
        [
            {
                "peptide_id": row["peptide_id"],
                "cluster_id": row["cluster_id"],
                "cluster_size": row["cluster_size"],
                "aligned_sequence_sha256": row["aligned_sequence_sha256"],
            }
            for row in split_rows
        ],
        ["peptide_id", "cluster_id", "cluster_size", "aligned_sequence_sha256"],
    )
    write_csv(
        folds_path,
        [
            {
                "peptide_id": row["peptide_id"],
                "cluster_id": row["cluster_id"],
                "outer_fold": row["outer_fold"],
            }
            for row in split_rows
        ],
        ["peptide_id", "cluster_id", "outer_fold"],
    )
    _write_audit_csv(threshold_path, audit)

    fold_sizes = [
        sum(row["outer_fold"] == fold for row in split_rows)
        for fold in range(1, int(config["outer_folds"]) + 1)
    ]
    payload = {
        "schema_version": 1,
        "frozen_on": config["frozen_on"],
        "label_blind": True,
        "holdout_labels_accessed": False,
        "training_records": len(records),
        "training_sha256": observed_checksum,
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "identity_definition": config["identity_definition"],
        "selection_rule": rule,
        "selected_threshold": selected,
        "selected_components": len(clusters),
        "fold_sizes": fold_sizes,
        "maximum_cross_fold_identity": cross_identity,
        "maximum_cross_fold_pair": list(cross_pair),
        "threshold_audit": audit,
    }
    report_json = Path(args.report_json)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    Path(args.report_md).write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
