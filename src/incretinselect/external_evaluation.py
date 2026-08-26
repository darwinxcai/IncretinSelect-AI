"""Locked final-model prediction and censor-aware external evaluation helpers."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from incretinselect.baseline import point_metrics
from incretinselect.clustering import aligned_identity
from incretinselect.holdout import DESIGN_IDS, design_group
from incretinselect.sequence_model import (
    component_sample_weights,
    encode_aligned_sequences,
    fit_component_weighted_ridge,
    select_alpha_leave_one_component_out,
)
from incretinselect.training import TrainingRecord

MODEL_IDS = ("ridge", "nn", "median", "component_mean")
RECEPTORS = ("gcgr", "glp1r")
PREDICTION_FIELDS = (
    "peptide_id",
    "design_group",
    "parent_cluster_id",
    "external_sequence_component_id",
    "nearest_development_component_ids",
    "linked_component_id",
    "linked_development_component_ids",
    "aligned_sequence",
    "nearest_identity",
    "nearest_tie_count",
    "nearest_donor_ids",
    "selected_alpha",
    "ridge_gcgr_log10_ec50_pm",
    "ridge_glp1r_log10_ec50_pm",
    "ridge_selectivity_log10_ratio",
    "nn_gcgr_log10_ec50_pm",
    "nn_glp1r_log10_ec50_pm",
    "nn_selectivity_log10_ratio",
    "median_gcgr_log10_ec50_pm",
    "median_glp1r_log10_ec50_pm",
    "median_selectivity_log10_ratio",
    "component_mean_gcgr_log10_ec50_pm",
    "component_mean_glp1r_log10_ec50_pm",
    "component_mean_selectivity_log10_ratio",
)
PARENT_CLUSTER_FIELDS = (
    "peptide_id",
    "parent_cluster_id",
    "parent_cluster_members",
    "parent_donor_ids",
    "external_sequence_component_id",
    "nearest_development_component_ids",
    "linked_component_id",
    "linked_development_component_ids",
)


class ExternalEvaluationError(ValueError):
    """Raised when a locked prediction or scoring contract is violated."""


def sha256_path(path: str | Path) -> str:
    """Hash one file in binary mode for prediction/evaluation receipt checks."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_prediction_lock(
    receipt_path: str | Path,
    prediction_path: str | Path,
    protocol_path: str | Path,
) -> dict[str, Any]:
    """Reject scoring if the label-free prediction receipt or files changed."""

    with Path(receipt_path).open(encoding="utf-8") as handle:
        receipt = json.load(handle)
    if receipt.get("receipt_type") != "label_free_external_prediction_lock":
        raise ExternalEvaluationError("Not a label-free external prediction receipt")
    if receipt.get("holdout_outcomes_accessed") is not False:
        raise ExternalEvaluationError("Prediction receipt does not prove outcome isolation")
    if sha256_path(prediction_path) != receipt.get("prediction_sha256"):
        raise ExternalEvaluationError("Locked prediction file checksum mismatch")
    protocol_hash = receipt.get("verified_input_sha256", {}).get(
        "external_evaluation_protocol"
    )
    if sha256_path(protocol_path) != protocol_hash:
        raise ExternalEvaluationError("Locked evaluation protocol checksum mismatch")
    return receipt


@dataclass(frozen=True)
class AggregateObservation:
    """One peptide-level endpoint point or one-sided lower bound in log10(pM)."""

    status: str
    value_log10_pm: float
    observed_replicates: int
    right_censored_replicates: int


def _targets(records: Sequence[TrainingRecord]) -> np.ndarray:
    return np.asarray(
        [
            [record.gcgr_log10_ec50_pm, record.glp1r_log10_ec50_pm]
            for record in records
        ],
        dtype=float,
    )


def build_locked_predictions(
    records: Iterable[TrainingRecord],
    components_by_id: dict[str, str],
    external_sequences: dict[str, str],
    alpha_grid: Iterable[float],
    *,
    alphabet: str,
    expected_length: int,
    external_identity_threshold: float,
) -> tuple[list[dict[str, object]], float, list[dict[str, float]]]:
    """Fit on all development records and predict P1--P15 without outcome access."""

    development = sorted(records, key=lambda record: record.peptide_id)
    if not development or {record.peptide_id for record in development} != set(components_by_id):
        raise ExternalEvaluationError(
            "Frozen components must exactly match the development record IDs"
        )
    if set(external_sequences) != set(DESIGN_IDS):
        raise ExternalEvaluationError("External sequences must be exactly P1--P15")

    development_features = encode_aligned_sequences(
        [record.aligned_sequence for record in development],
        alphabet=alphabet,
        expected_length=expected_length,
    )
    external_order = list(DESIGN_IDS)
    external_features = encode_aligned_sequences(
        [external_sequences[peptide_id] for peptide_id in external_order],
        alphabet=alphabet,
        expected_length=expected_length,
    )
    target_matrix = _targets(development)
    components = [components_by_id[record.peptide_id] for record in development]
    selected_alpha, inner_scores = select_alpha_leave_one_component_out(
        development_features,
        target_matrix,
        components,
        alpha_grid,
    )
    ridge = fit_component_weighted_ridge(
        development_features,
        target_matrix,
        components,
        selected_alpha,
    )
    ridge_predictions = ridge.predict(external_features)

    all_row_median = np.median(target_matrix, axis=0)
    weights = component_sample_weights(components)
    component_mean = np.average(target_matrix, axis=0, weights=weights)

    rows: list[dict[str, object]] = []
    for row_index, peptide_id in enumerate(external_order):
        query_sequence = external_sequences[peptide_id]
        identities = {
            record.peptide_id: aligned_identity(query_sequence, record.aligned_sequence)
            for record in development
        }
        maximum_identity = max(identities.values())
        nearest = [
            record
            for record in development
            if abs(identities[record.peptide_id] - maximum_identity) <= 1e-12
        ]
        nearest.sort(key=lambda record: record.peptide_id)
        nearest_targets = _targets(nearest)
        nn_prediction = nearest_targets.mean(axis=0)
        ridge_prediction = ridge_predictions[row_index]

        row: dict[str, object] = {
            "peptide_id": peptide_id,
            "design_group": design_group(peptide_id),
            "aligned_sequence": query_sequence,
            "nearest_identity": maximum_identity,
            "nearest_tie_count": len(nearest),
            "nearest_donor_ids": ";".join(record.peptide_id for record in nearest),
            "nearest_development_component_ids": ";".join(
                sorted({components_by_id[record.peptide_id] for record in nearest})
            ),
            "selected_alpha": selected_alpha,
        }
        for model, values in (
            ("ridge", ridge_prediction),
            ("nn", nn_prediction),
            ("median", all_row_median),
            ("component_mean", component_mean),
        ):
            gcgr, glp1r = map(float, values)
            row[f"{model}_gcgr_log10_ec50_pm"] = gcgr
            row[f"{model}_glp1r_log10_ec50_pm"] = glp1r
            row[f"{model}_selectivity_log10_ratio"] = gcgr - glp1r
        rows.append(row)
    parent_clusters = derive_parent_clusters(rows)
    cluster_by_peptide = {
        str(row["peptide_id"]): str(row["parent_cluster_id"])
        for row in parent_clusters
    }
    for row in rows:
        row["parent_cluster_id"] = cluster_by_peptide[str(row["peptide_id"])]
    external_components = derive_external_sequence_components(
        rows, identity_threshold=external_identity_threshold
    )
    external_component_by_peptide = {
        peptide_id: component_id
        for component_id, members in external_components.items()
        for peptide_id in members
    }
    for row in rows:
        row["external_sequence_component_id"] = external_component_by_peptide[
            str(row["peptide_id"])
        ]
    linked_components = derive_combined_linked_components(
        development,
        components_by_id,
        rows,
        identity_threshold=external_identity_threshold,
    )
    linked_by_peptide = {
        peptide_id: (linked_id, linked_development_components)
        for linked_id, payload in linked_components.items()
        for peptide_id in payload["members"]
        for linked_development_components in [payload["development_components"]]
    }
    for row in rows:
        linked_id, linked_development_components = linked_by_peptide[str(row["peptide_id"])]
        row["linked_component_id"] = linked_id
        row["linked_development_component_ids"] = ";".join(
            linked_development_components
        )
    return rows, selected_alpha, inner_scores


def derive_external_sequence_components(
    prediction_rows: Sequence[dict[str, object]], identity_threshold: float
) -> dict[str, list[str]]:
    """Derive connected components among external sequences at a fixed identity."""

    if not 0 < identity_threshold <= 1:
        raise ExternalEvaluationError("External identity threshold must be in (0, 1]")
    rows_by_id = {str(row["peptide_id"]): row for row in prediction_rows}
    if len(rows_by_id) != 15 or set(rows_by_id) != set(DESIGN_IDS):
        raise ExternalEvaluationError("External components require one row for P1--P15")
    parents = {peptide_id: peptide_id for peptide_id in DESIGN_IDS}

    def find(peptide_id: str) -> str:
        while parents[peptide_id] != peptide_id:
            parents[peptide_id] = parents[parents[peptide_id]]
            peptide_id = parents[peptide_id]
        return peptide_id

    def union(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            earlier, later = sorted(
                (first_root, second_root), key=lambda value: int(value[1:])
            )
            parents[later] = earlier

    for index, first in enumerate(DESIGN_IDS):
        for second in DESIGN_IDS[index + 1 :]:
            first_sequence = str(rows_by_id[first]["aligned_sequence"])
            second_sequence = str(rows_by_id[second]["aligned_sequence"])
            if aligned_identity(first_sequence, second_sequence) + 1e-12 >= identity_threshold:
                union(first, second)

    components: dict[str, list[str]] = defaultdict(list)
    for peptide_id in DESIGN_IDS:
        components[find(peptide_id)].append(peptide_id)
    ordered = sorted(
        components.values(), key=lambda members: min(int(item[1:]) for item in members)
    )
    return {
        f"EC{index:03d}": sorted(members, key=lambda value: int(value[1:]))
        for index, members in enumerate(ordered, start=1)
    }


def derive_combined_linked_components(
    development_records: Sequence[TrainingRecord],
    components_by_id: dict[str, str],
    prediction_rows: Sequence[dict[str, object]],
    identity_threshold: float,
) -> dict[str, dict[str, list[str]]]:
    """Link external designs through the frozen 0.85 development graph."""

    if {record.peptide_id for record in development_records} != set(components_by_id):
        raise ExternalEvaluationError("Development component IDs do not match records")
    rows_by_id = {str(row["peptide_id"]): row for row in prediction_rows}
    if len(rows_by_id) != 15 or set(rows_by_id) != set(DESIGN_IDS):
        raise ExternalEvaluationError("Combined components require one row for P1--P15")
    external_components = derive_external_sequence_components(
        prediction_rows, identity_threshold
    )
    external_component_by_id = {
        peptide_id: component_id
        for component_id, members in external_components.items()
        for peptide_id in members
    }
    development_hits: dict[str, set[str]] = {}
    for peptide_id in DESIGN_IDS:
        query = str(rows_by_id[peptide_id]["aligned_sequence"])
        hits = {
            components_by_id[record.peptide_id]
            for record in development_records
            if aligned_identity(query, record.aligned_sequence) + 1e-12
            >= identity_threshold
        }
        if not hits:
            raise ExternalEvaluationError(
                f"{peptide_id} has no development component at identity {identity_threshold}"
            )
        development_hits[peptide_id] = hits

    parents = {peptide_id: peptide_id for peptide_id in DESIGN_IDS}

    def find(peptide_id: str) -> str:
        while parents[peptide_id] != peptide_id:
            parents[peptide_id] = parents[parents[peptide_id]]
            peptide_id = parents[peptide_id]
        return peptide_id

    def union(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            earlier, later = sorted(
                (first_root, second_root), key=lambda value: int(value[1:])
            )
            parents[later] = earlier

    for index, first in enumerate(DESIGN_IDS):
        for second in DESIGN_IDS[index + 1 :]:
            same_external_component = (
                external_component_by_id[first] == external_component_by_id[second]
            )
            if same_external_component or development_hits[first] & development_hits[second]:
                union(first, second)

    grouped: dict[str, list[str]] = defaultdict(list)
    for peptide_id in DESIGN_IDS:
        grouped[find(peptide_id)].append(peptide_id)
    ordered = sorted(
        grouped.values(), key=lambda members: min(int(item[1:]) for item in members)
    )
    return {
        f"LC{index:03d}": {
            "members": sorted(members, key=lambda value: int(value[1:])),
            "development_components": sorted(
                set().union(*(development_hits[member] for member in members))
            ),
        }
        for index, members in enumerate(ordered, start=1)
    }


def derive_parent_clusters(
    prediction_rows: Sequence[dict[str, object]],
) -> list[dict[str, str]]:
    """Connect designs that share a tied nearest development donor.

    The rule is label-free and transitive: designs are nodes, their tied nearest
    development peptides are parent nodes, and connected design components form
    the resampling clusters used for external uncertainty.
    """

    rows_by_id = {str(row["peptide_id"]): row for row in prediction_rows}
    if len(rows_by_id) != 15 or set(rows_by_id) != set(DESIGN_IDS):
        raise ExternalEvaluationError("Parent clustering requires one row for P1--P15")
    donors: dict[str, set[str]] = {}
    for peptide_id, row in rows_by_id.items():
        donor_ids = {item for item in str(row.get("nearest_donor_ids", "")).split(";") if item}
        if not donor_ids:
            raise ExternalEvaluationError(f"{peptide_id} has no tied nearest donor")
        donors[peptide_id] = donor_ids

    parents = {peptide_id: peptide_id for peptide_id in DESIGN_IDS}

    def find(peptide_id: str) -> str:
        while parents[peptide_id] != peptide_id:
            parents[peptide_id] = parents[parents[peptide_id]]
            peptide_id = parents[peptide_id]
        return peptide_id

    def union(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            earlier, later = sorted(
                (first_root, second_root), key=lambda value: int(value[1:])
            )
            parents[later] = earlier

    for index, first in enumerate(DESIGN_IDS):
        for second in DESIGN_IDS[index + 1 :]:
            if donors[first] & donors[second]:
                union(first, second)

    components: dict[str, list[str]] = defaultdict(list)
    for peptide_id in DESIGN_IDS:
        components[find(peptide_id)].append(peptide_id)
    ordered_components = sorted(
        components.values(), key=lambda members: min(int(item[1:]) for item in members)
    )
    result: list[dict[str, str]] = []
    for cluster_index, members in enumerate(ordered_components, start=1):
        ordered_members = sorted(members, key=lambda value: int(value[1:]))
        cluster_id = f"PC{cluster_index:03d}"
        parent_donors = sorted(set().union(*(donors[member] for member in ordered_members)))
        for peptide_id in ordered_members:
            result.append(
                {
                    "peptide_id": peptide_id,
                    "parent_cluster_id": cluster_id,
                    "parent_cluster_members": ";".join(ordered_members),
                    "parent_donor_ids": ";".join(parent_donors),
                    "external_sequence_component_id": str(
                        rows_by_id[peptide_id].get("external_sequence_component_id", "")
                    ),
                    "nearest_development_component_ids": str(
                        rows_by_id[peptide_id].get("nearest_development_component_ids", "")
                    ),
                    "linked_component_id": str(
                        rows_by_id[peptide_id].get("linked_component_id", "")
                    ),
                    "linked_development_component_ids": str(
                        rows_by_id[peptide_id].get(
                            "linked_development_component_ids", ""
                        )
                    ),
                }
            )
    return sorted(result, key=lambda row: int(row["peptide_id"][1:]))


def aggregate_replicates(replicates: Sequence[dict[str, Any]]) -> AggregateObservation:
    """Aggregate three assay replicates without converting censoring to a point."""

    if len(replicates) != 3:
        raise ExternalEvaluationError("Every external peptide-receptor pair needs 3 replicates")
    statuses = [str(item.get("status", "")) for item in replicates]
    if any(status not in {"observed", "right_censored"} for status in statuses):
        raise ExternalEvaluationError("Primary scoring does not permit missing replicates")
    lower_values_pm = [
        float(item["value_pm"])
        if item["status"] == "observed"
        else float(item["threshold_pm"])
        for item in replicates
    ]
    if any(not math.isfinite(value) or value <= 0 for value in lower_values_pm):
        raise ExternalEvaluationError("Replicate values and bounds must be positive and finite")
    right_censored = statuses.count("right_censored")
    return AggregateObservation(
        status="exact" if right_censored == 0 else "lower_bound",
        value_log10_pm=math.log10(statistics.fmean(lower_values_pm)),
        observed_replicates=statuses.count("observed"),
        right_censored_replicates=right_censored,
    )


def constraint_absolute_error(prediction: float, status: str, value: float) -> float | None:
    """Return point/interval constraint loss, or ``None`` if uninformative."""

    if status == "exact":
        return abs(prediction - value)
    if status == "lower_bound":
        return max(0.0, value - prediction)
    if status == "upper_bound":
        return max(0.0, prediction - value)
    if status == "uninformative":
        return None
    raise ExternalEvaluationError(f"Unsupported aggregate status: {status!r}")


def endpoint_evaluation_rows(
    prediction_rows: Sequence[dict[str, object]],
    gcgr_replicates: dict[str, list[dict[str, Any]]],
    glp1r_replicates: dict[str, list[dict[str, Any]]],
) -> list[dict[str, object]]:
    """Build peptide-level receptor rows plus selectivity interval rows."""

    predictions_by_id = {str(row["peptide_id"]): row for row in prediction_rows}
    expected = set(DESIGN_IDS)
    if (
        set(predictions_by_id) != expected
        or set(gcgr_replicates) != expected
        or set(glp1r_replicates) != expected
    ):
        raise ExternalEvaluationError("Predictions and both outcome tables must be P1--P15")

    rows: list[dict[str, object]] = []
    receptor_observations: dict[tuple[str, str], AggregateObservation] = {}
    replicate_tables = {"gcgr": gcgr_replicates, "glp1r": glp1r_replicates}
    for peptide_id in DESIGN_IDS:
        prediction = predictions_by_id[peptide_id]
        for receptor in RECEPTORS:
            observation = aggregate_replicates(replicate_tables[receptor][peptide_id])
            receptor_observations[(peptide_id, receptor)] = observation
            row: dict[str, object] = {
                "peptide_id": peptide_id,
                "design_group": prediction["design_group"],
                "parent_cluster_id": prediction["parent_cluster_id"],
                "external_sequence_component_id": prediction[
                    "external_sequence_component_id"
                ],
                "linked_component_id": prediction["linked_component_id"],
                "endpoint": receptor,
                "observation_status": observation.status,
                "observation_log10_pm_or_bound": observation.value_log10_pm,
                "observed_replicates": observation.observed_replicates,
                "right_censored_replicates": observation.right_censored_replicates,
            }
            for model in MODEL_IDS:
                predicted = float(prediction[f"{model}_{receptor}_log10_ec50_pm"])
                row[f"{model}_prediction"] = predicted
                row[f"{model}_constraint_absolute_error"] = constraint_absolute_error(
                    predicted,
                    observation.status,
                    observation.value_log10_pm,
                )
            rows.append(row)

        gcgr_observation = receptor_observations[(peptide_id, "gcgr")]
        glp1r_observation = receptor_observations[(peptide_id, "glp1r")]
        if gcgr_observation.status == "exact" and glp1r_observation.status == "exact":
            selectivity_status = "exact"
            selectivity_value = (
                gcgr_observation.value_log10_pm - glp1r_observation.value_log10_pm
            )
        elif (
            gcgr_observation.status == "lower_bound"
            and glp1r_observation.status == "exact"
        ):
            selectivity_status = "lower_bound"
            selectivity_value = (
                gcgr_observation.value_log10_pm - glp1r_observation.value_log10_pm
            )
        elif (
            gcgr_observation.status == "exact"
            and glp1r_observation.status == "lower_bound"
        ):
            selectivity_status = "upper_bound"
            selectivity_value = (
                gcgr_observation.value_log10_pm - glp1r_observation.value_log10_pm
            )
        else:
            selectivity_status = "uninformative"
            selectivity_value = 0.0

        selectivity_row: dict[str, object] = {
            "peptide_id": peptide_id,
            "design_group": prediction["design_group"],
            "parent_cluster_id": prediction["parent_cluster_id"],
            "external_sequence_component_id": prediction["external_sequence_component_id"],
            "linked_component_id": prediction["linked_component_id"],
            "endpoint": "selectivity",
            "observation_status": selectivity_status,
            "observation_log10_pm_or_bound": (
                selectivity_value if selectivity_status != "uninformative" else None
            ),
            "observed_replicates": (
                gcgr_observation.observed_replicates
                + glp1r_observation.observed_replicates
            ),
            "right_censored_replicates": (
                gcgr_observation.right_censored_replicates
                + glp1r_observation.right_censored_replicates
            ),
        }
        for model in MODEL_IDS:
            predicted = float(prediction[f"{model}_selectivity_log10_ratio"])
            selectivity_row[f"{model}_prediction"] = predicted
            selectivity_row[f"{model}_constraint_absolute_error"] = (
                constraint_absolute_error(predicted, selectivity_status, selectivity_value)
            )
        rows.append(selectivity_row)
    return rows


def replicate_sensitivity_rows(
    prediction_rows: Sequence[dict[str, object]],
    gcgr_replicates: dict[str, list[dict[str, Any]]],
    glp1r_replicates: dict[str, list[dict[str, Any]]],
) -> list[dict[str, object]]:
    """Retain all receptor replicate cells as a non-independent sensitivity table."""

    predictions_by_id = {str(row["peptide_id"]): row for row in prediction_rows}
    rows: list[dict[str, object]] = []
    for peptide_id in DESIGN_IDS:
        prediction = predictions_by_id[peptide_id]
        for receptor, table in (("gcgr", gcgr_replicates), ("glp1r", glp1r_replicates)):
            for replicate_index, replicate in enumerate(table[peptide_id], start=1):
                status = str(replicate["status"])
                if status == "observed":
                    value = math.log10(float(replicate["value_pm"]))
                    aggregate_status = "exact"
                elif status == "right_censored":
                    value = math.log10(float(replicate["threshold_pm"]))
                    aggregate_status = "lower_bound"
                else:
                    raise ExternalEvaluationError(
                        "Replicate sensitivity does not permit missing observations"
                    )
                row: dict[str, object] = {
                    "peptide_id": peptide_id,
                    "design_group": prediction["design_group"],
                    "parent_cluster_id": prediction["parent_cluster_id"],
                    "external_sequence_component_id": prediction[
                        "external_sequence_component_id"
                    ],
                    "linked_component_id": prediction["linked_component_id"],
                    "receptor": receptor,
                    "replicate": replicate_index,
                    "observation_status": status,
                    "observation_log10_pm_or_bound": value,
                }
                for model in MODEL_IDS:
                    predicted = float(prediction[f"{model}_{receptor}_log10_ec50_pm"])
                    row[f"{model}_prediction"] = predicted
                    row[f"{model}_constraint_absolute_error"] = constraint_absolute_error(
                        predicted,
                        aggregate_status,
                        value,
                    )
                rows.append(row)
    return rows


def stratified_paired_bootstrap_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    challenger: str = "ridge",
    baseline: str = "nn",
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, float | int | str]:
    """Naively bootstrap peptides within design groups as a sensitivity only."""

    endpoint_rows = [row for row in rows if row["endpoint"] == endpoint]
    if len(endpoint_rows) != 15:
        raise ExternalEvaluationError("Primary receptor comparison requires all 15 peptides")
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in endpoint_rows:
        challenger_loss = row[f"{challenger}_constraint_absolute_error"]
        baseline_loss = row[f"{baseline}_constraint_absolute_error"]
        if challenger_loss is None or baseline_loss is None:
            raise ExternalEvaluationError("Primary receptor loss cannot be uninformative")
        grouped[str(row["design_group"])].append(
            float(challenger_loss) - float(baseline_loss)
        )
    if sorted(map(len, grouped.values())) != [5, 5, 5]:
        raise ExternalEvaluationError("Bootstrap strata must contain five peptides each")
    if resamples < 1 or not 0 < confidence_level < 1:
        raise ExternalEvaluationError("Invalid bootstrap settings")

    generator = np.random.default_rng(seed)
    sample_means = np.empty(resamples, dtype=float)
    arrays = [np.asarray(grouped[group], dtype=float) for group in sorted(grouped)]
    for index in range(resamples):
        sampled = [array[generator.integers(0, len(array), len(array))] for array in arrays]
        sample_means[index] = float(np.mean(np.concatenate(sampled)))
    tail = (1.0 - confidence_level) / 2.0
    all_deltas = np.concatenate(arrays)
    return {
        "endpoint": endpoint,
        "challenger": challenger,
        "baseline": baseline,
        "n_peptides": len(all_deltas),
        "mae_delta_log10_pm": float(np.mean(all_deltas)),
        "ci_lower": float(np.quantile(sample_means, tail)),
        "ci_upper": float(np.quantile(sample_means, 1.0 - tail)),
        "confidence_level": confidence_level,
        "resamples": resamples,
        "seed": seed,
        "bootstrap_unit": "peptide_stratified_by_design_group",
        "uncertainty_role": "naive_sensitivity_only",
    }


def parent_cluster_paired_bootstrap_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    challenger: str = "ridge",
    baseline: str = "nn",
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, float | int | str]:
    """Resample nearest-donor parent proxies as a dependence sensitivity."""

    return _whole_group_paired_bootstrap_delta(
        rows,
        endpoint,
        group_field="parent_cluster_id",
        expected_group_count=5,
        expected_sizes=[1, 1, 4, 4, 5],
        challenger=challenger,
        baseline=baseline,
        resamples=resamples,
        seed=seed,
        confidence_level=confidence_level,
        bootstrap_unit="whole_nearest_donor_parent_proxy",
        uncertainty_role="dependence_sensitivity_only",
    )


def external_component_paired_bootstrap_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    challenger: str = "ridge",
    baseline: str = "nn",
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, float | int | str]:
    """Headline descriptive resampling over four frozen external components."""

    return _whole_group_paired_bootstrap_delta(
        rows,
        endpoint,
        group_field="external_sequence_component_id",
        expected_group_count=4,
        expected_sizes=[1, 4, 5, 5],
        challenger=challenger,
        baseline=baseline,
        resamples=resamples,
        seed=seed,
        confidence_level=confidence_level,
        bootstrap_unit="whole_frozen_0_85_external_sequence_component",
        uncertainty_role="headline_descriptive_resampling_interval",
    )


def _whole_group_paired_bootstrap_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    group_field: str,
    expected_group_count: int,
    expected_sizes: list[int],
    challenger: str,
    baseline: str,
    resamples: int,
    seed: int,
    confidence_level: float,
    bootstrap_unit: str,
    uncertainty_role: str,
) -> dict[str, float | int | str]:
    endpoint_rows = [row for row in rows if row["endpoint"] == endpoint]
    if len(endpoint_rows) != 15:
        raise ExternalEvaluationError("Whole-group comparison requires all 15 peptides")
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in endpoint_rows:
        challenger_loss = row[f"{challenger}_constraint_absolute_error"]
        baseline_loss = row[f"{baseline}_constraint_absolute_error"]
        if challenger_loss is None or baseline_loss is None:
            raise ExternalEvaluationError("Primary receptor loss cannot be uninformative")
        grouped[str(row[group_field])].append(float(challenger_loss) - float(baseline_loss))
    if len(grouped) != expected_group_count or sorted(map(len, grouped.values())) != expected_sizes:
        raise ExternalEvaluationError(
            f"Unexpected {group_field} count or sizes: "
            f"{len(grouped)}, {sorted(map(len, grouped.values()))}"
        )
    if resamples < 1 or not 0 < confidence_level < 1:
        raise ExternalEvaluationError("Invalid bootstrap settings")

    arrays = [np.asarray(grouped[group], dtype=float) for group in sorted(grouped)]
    generator = np.random.default_rng(seed)
    samples = generator.integers(0, len(arrays), size=(resamples, len(arrays)))
    sample_means = np.empty(resamples, dtype=float)
    for index, group_indexes in enumerate(samples):
        sample_means[index] = float(
            np.mean(np.concatenate([arrays[item] for item in group_indexes]))
        )
    all_deltas = np.concatenate(arrays)
    tail = (1.0 - confidence_level) / 2.0
    return {
        "endpoint": endpoint,
        "challenger": challenger,
        "baseline": baseline,
        "n_peptides": len(all_deltas),
        "n_dependency_groups": len(arrays),
        "mae_delta_log10_pm": float(np.mean(all_deltas)),
        "interval_lower": float(np.quantile(sample_means, tail)),
        "interval_upper": float(np.quantile(sample_means, 1.0 - tail)),
        "interval_mass": confidence_level,
        "resamples": resamples,
        "seed": seed,
        "bootstrap_unit": bootstrap_unit,
        "uncertainty_role": uncertainty_role,
    }


def leave_one_parent_cluster_out_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    challenger: str = "ridge",
    baseline: str = "nn",
) -> dict[str, object]:
    """Leave one nearest-parent proxy out at a time."""

    return leave_one_dependency_group_out_delta(
        rows,
        endpoint,
        group_field="parent_cluster_id",
        expected_group_count=5,
        challenger=challenger,
        baseline=baseline,
    )


def leave_one_dependency_group_out_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    group_field: str,
    expected_group_count: int,
    challenger: str = "ridge",
    baseline: str = "nn",
) -> dict[str, object]:
    """Report every leave-one-dependence-group-out pooled delta and range."""

    endpoint_rows = [row for row in rows if row["endpoint"] == endpoint]
    groups = sorted({str(row[group_field]) for row in endpoint_rows})
    if len(endpoint_rows) != 15 or len(groups) != expected_group_count:
        raise ExternalEvaluationError(
            f"Leave-group-out requires 15 rows in {expected_group_count} {group_field} groups"
        )
    estimates: list[dict[str, object]] = []
    for omitted in groups:
        retained = [row for row in endpoint_rows if row[group_field] != omitted]
        deltas = [
            float(row[f"{challenger}_constraint_absolute_error"])
            - float(row[f"{baseline}_constraint_absolute_error"])
            for row in retained
        ]
        estimates.append(
            {
                "omitted_group": omitted,
                "retained_peptides": len(retained),
                "mae_delta_log10_pm": statistics.fmean(deltas),
            }
        )
    values = [float(row["mae_delta_log10_pm"]) for row in estimates]
    return {
        "endpoint": endpoint,
        "challenger": challenger,
        "baseline": baseline,
        "group_field": group_field,
        "n_dependency_groups": len(groups),
        "minimum_leave_one_group_out_delta": min(values),
        "maximum_leave_one_group_out_delta": max(values),
        "estimates": estimates,
    }


def dependency_group_macro_delta(
    rows: Sequence[dict[str, object]],
    endpoint: str,
    *,
    group_field: str,
    expected_group_count: int,
    challenger: str = "ridge",
    baseline: str = "nn",
) -> dict[str, object]:
    """Give each dependence group one vote in a paired model-loss contrast."""

    endpoint_rows = [row for row in rows if row["endpoint"] == endpoint]
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in endpoint_rows:
        grouped[str(row[group_field])].append(
            float(row[f"{challenger}_constraint_absolute_error"])
            - float(row[f"{baseline}_constraint_absolute_error"])
        )
    if len(endpoint_rows) != 15 or len(grouped) != expected_group_count:
        raise ExternalEvaluationError("Dependency-group macro delta has unexpected groups")
    group_estimates = {
        group: statistics.fmean(values) for group, values in sorted(grouped.items())
    }
    return {
        "endpoint": endpoint,
        "challenger": challenger,
        "baseline": baseline,
        "group_field": group_field,
        "n_dependency_groups": len(grouped),
        "macro_mae_delta_log10_pm": statistics.fmean(group_estimates.values()),
        "group_mean_deltas": group_estimates,
    }


def summarize_endpoint_losses(
    rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Summarize constraint-aware peptide-level losses for every retained model."""

    summaries: list[dict[str, object]] = []
    for endpoint in ("gcgr", "glp1r", "selectivity"):
        endpoint_rows = [row for row in rows if row["endpoint"] == endpoint]
        for model in MODEL_IDS:
            losses = [
                float(row[f"{model}_constraint_absolute_error"])
                for row in endpoint_rows
                if row[f"{model}_constraint_absolute_error"] is not None
            ]
            summaries.append(
                {
                    "model": model,
                    "endpoint": endpoint,
                    "metric": "peptide_constraint_mae_lower_bound",
                    "n": len(losses),
                    "value": statistics.fmean(losses),
                }
            )
    return summaries


def complete_case_metrics(
    rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Return descriptive point metrics only for exact aggregate observations."""

    summaries: list[dict[str, object]] = []
    for endpoint in ("gcgr", "glp1r", "selectivity"):
        exact_rows = [
            row
            for row in rows
            if row["endpoint"] == endpoint and row["observation_status"] == "exact"
        ]
        if not exact_rows:
            continue
        actual = [float(row["observation_log10_pm_or_bound"]) for row in exact_rows]
        for model in MODEL_IDS:
            predicted = [float(row[f"{model}_prediction"]) for row in exact_rows]
            summaries.append(
                {
                    "model": model,
                    "endpoint": endpoint,
                    "subset": "three_exact_replicates"
                    if endpoint != "selectivity"
                    else "both_receptors_three_exact_replicates",
                    **point_metrics(actual, predicted),
                }
            )
    return summaries


def group_loss_summaries(
    rows: Sequence[dict[str, object]], model: str = "ridge"
) -> list[dict[str, object]]:
    """Retain intended-group results without treating design intent as truth."""

    summaries: list[dict[str, object]] = []
    for endpoint in ("gcgr", "glp1r", "selectivity"):
        for group in ("dual", "gcgr_selective", "glp1r_selective"):
            group_rows = [
                row
                for row in rows
                if row["endpoint"] == endpoint and row["design_group"] == group
            ]
            losses = [
                float(row[f"{model}_constraint_absolute_error"])
                for row in group_rows
                if row[f"{model}_constraint_absolute_error"] is not None
            ]
            summaries.append(
                {
                    "model": model,
                    "endpoint": endpoint,
                    "design_group": group,
                    "n_informative": len(losses),
                    "constraint_mae_lower_bound": (
                        statistics.fmean(losses) if losses else None
                    ),
                }
            )
    return summaries
