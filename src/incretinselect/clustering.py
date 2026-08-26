"""Label-blind sequence clustering and deterministic outer-fold assignment."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from incretinselect.training import TrainingRecord


class SplitError(ValueError):
    """Raised when a leakage-resistant split cannot be created or verified."""


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    members: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.members)


def aligned_identity(first: str, second: str) -> float:
    """Identity over aligned columns, excluding columns that are gap in both."""

    if len(first) != len(second):
        raise SplitError("Aligned identity requires equal-length sequences")
    comparable = [(left, right) for left, right in zip(first, second, strict=True) if left != "-" or right != "-"]
    if not comparable:
        raise SplitError("Aligned identity is undefined for two all-gap sequences")
    return sum(left == right for left, right in comparable) / len(comparable)


def _connected_components(sequences: dict[str, str], threshold: float) -> tuple[list[tuple[str, ...]], int]:
    if not 0 < threshold <= 1:
        raise SplitError("Identity threshold must be in (0, 1]")
    ids = sorted(sequences)
    parents = {peptide_id: peptide_id for peptide_id in ids}

    def find(peptide_id: str) -> str:
        while parents[peptide_id] != peptide_id:
            parents[peptide_id] = parents[parents[peptide_id]]
            peptide_id = parents[peptide_id]
        return peptide_id

    def union(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            smaller, larger = sorted((first_root, second_root))
            parents[larger] = smaller

    edge_count = 0
    for position, first_id in enumerate(ids):
        for second_id in ids[position + 1 :]:
            if aligned_identity(sequences[first_id], sequences[second_id]) + 1e-12 >= threshold:
                union(first_id, second_id)
                edge_count += 1

    members: dict[str, list[str]] = {}
    for peptide_id in ids:
        members.setdefault(find(peptide_id), []).append(peptide_id)
    components = [tuple(sorted(group)) for group in members.values()]
    components.sort(key=lambda group: (-len(group), group))
    return components, edge_count


def build_clusters(sequences: dict[str, str], threshold: float) -> tuple[list[Cluster], int]:
    components, edge_count = _connected_components(sequences, threshold)
    return [
        Cluster(cluster_id=f"SC{index:03d}", members=members)
        for index, members in enumerate(components, start=1)
    ], edge_count


def assign_clusters_to_folds(clusters: Iterable[Cluster], fold_count: int) -> dict[str, int]:
    """Greedily balance whole clusters; labels and endpoint values are never read."""

    if fold_count < 2:
        raise SplitError("At least two outer folds are required")
    ordered = sorted(clusters, key=lambda cluster: (-cluster.size, cluster.cluster_id))
    if len(ordered) < fold_count:
        raise SplitError("Fewer sequence clusters than requested folds")
    fold_sizes = [0] * fold_count
    assignment: dict[str, int] = {}
    for cluster in ordered:
        fold_index = min(range(fold_count), key=lambda index: (fold_sizes[index], index))
        fold = fold_index + 1
        assignment[cluster.cluster_id] = fold
        fold_sizes[fold_index] += cluster.size
    return assignment


def _fold_sizes(clusters: Iterable[Cluster], assignment: dict[str, int], fold_count: int) -> list[int]:
    sizes = [0] * fold_count
    for cluster in clusters:
        sizes[assignment[cluster.cluster_id] - 1] += cluster.size
    return sizes


def audit_thresholds(
    sequences: dict[str, str],
    thresholds: Iterable[float],
    fold_count: int,
    maximum_fold_size_ratio: float,
    minimum_components: int,
) -> tuple[list[dict[str, Any]], float, list[Cluster], dict[str, int]]:
    """Select the lowest predeclared threshold yielding usable label-blind folds."""

    rows: list[dict[str, Any]] = []
    selected: tuple[float, list[Cluster], dict[str, int]] | None = None
    for threshold in sorted(set(float(value) for value in thresholds)):
        clusters, edge_count = build_clusters(sequences, threshold)
        assignment = assign_clusters_to_folds(clusters, fold_count)
        fold_sizes = _fold_sizes(clusters, assignment, fold_count)
        fold_size_ratio = max(fold_sizes) / min(fold_sizes)
        eligible = len(clusters) >= minimum_components and fold_size_ratio <= maximum_fold_size_ratio
        row = {
            "identity_threshold": threshold,
            "pair_edges_at_or_above_threshold": edge_count,
            "components": len(clusters),
            "singletons": sum(cluster.size == 1 for cluster in clusters),
            "largest_component": max(cluster.size for cluster in clusters),
            "largest_component_fraction": max(cluster.size for cluster in clusters) / len(sequences),
            "fold_sizes": fold_sizes,
            "fold_size_ratio": fold_size_ratio,
            "eligible": eligible,
        }
        rows.append(row)
        if selected is None and eligible:
            selected = (threshold, clusters, assignment)
    if selected is None:
        raise SplitError("No candidate threshold satisfies the predeclared sequence-only rule")
    return rows, selected[0], selected[1], selected[2]


def max_cross_fold_identity(
    sequences: dict[str, str],
    peptide_folds: dict[str, int],
) -> tuple[float, tuple[str, str]]:
    best = (-1.0, ("", ""))
    ids = sorted(sequences)
    for position, first_id in enumerate(ids):
        for second_id in ids[position + 1 :]:
            if peptide_folds[first_id] == peptide_folds[second_id]:
                continue
            candidate = (aligned_identity(sequences[first_id], sequences[second_id]), (first_id, second_id))
            if candidate > best:
                best = candidate
    if best[0] < 0:
        raise SplitError("No cross-fold sequence pairs exist")
    return best


def peptide_split_rows(
    records: Iterable[TrainingRecord],
    clusters: Iterable[Cluster],
    assignment: dict[str, int],
) -> list[dict[str, Any]]:
    record_by_id = {record.peptide_id: record for record in records}
    rows = []
    for cluster in sorted(clusters, key=lambda item: item.cluster_id):
        for peptide_id in cluster.members:
            sequence = record_by_id[peptide_id].aligned_sequence
            rows.append(
                {
                    "peptide_id": peptide_id,
                    "cluster_id": cluster.cluster_id,
                    "cluster_size": cluster.size,
                    "outer_fold": assignment[cluster.cluster_id],
                    "aligned_sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                }
            )
    return sorted(rows, key=lambda row: row["peptide_id"])


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_split_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("schema_version") != 1:
        raise SplitError("Only sequence split config schema version 1 is supported")
    return config


def load_peptide_folds(path: str | Path) -> dict[str, int]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    folds: dict[str, int] = {}
    for row in rows:
        peptide_id = row["peptide_id"]
        if peptide_id in folds:
            raise SplitError(f"Duplicate peptide in fold file: {peptide_id}")
        folds[peptide_id] = int(row["outer_fold"])
    return folds
