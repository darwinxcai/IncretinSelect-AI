"""Deterministic, leakage-resistant CPU baselines and censor-aware metrics."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable

from incretinselect.clustering import aligned_identity
from incretinselect.training import TrainingRecord


class BaselineError(ValueError):
    """Raised when a baseline would violate a frozen evaluation boundary."""


@dataclass(frozen=True)
class CensoredObservation:
    """One log10(pM) endpoint observation or one-sided assay bound."""

    status: str
    value: float


def censor_constraint_absolute_error(prediction: float, observation: CensoredObservation) -> float:
    """Lower-bound absolute error consistent with an exact or one-sided label.

    A zero error for a censored observation means only that the prediction does
    not violate the reported bound; it is not evidence of an exact match.
    """

    if observation.status == "observed":
        return abs(prediction - observation.value)
    if observation.status == "right_censored":
        return max(0.0, observation.value - prediction)
    if observation.status == "left_censored":
        return max(0.0, prediction - observation.value)
    raise BaselineError(f"Unsupported censoring status: {observation.status!r}")


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][1] == ordered[position][1]:
            end += 1
        average_rank = ((position + 1) + end) / 2
        for index in range(position, end):
            ranks[ordered[index][0]] = average_rank
        position = end
    return ranks


def _pearson(first: list[float], second: list[float]) -> float | None:
    if len(first) != len(second) or len(first) < 2:
        return None
    first_mean, second_mean = statistics.fmean(first), statistics.fmean(second)
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first, second, strict=True)
    )
    first_sum = sum((value - first_mean) ** 2 for value in first)
    second_sum = sum((value - second_mean) ** 2 for value in second)
    denominator = math.sqrt(first_sum * second_sum)
    return numerator / denominator if denominator else None


def point_metrics(actual: Iterable[float], predicted: Iterable[float]) -> dict[str, float | int | None]:
    actual_values, predicted_values = list(actual), list(predicted)
    if len(actual_values) != len(predicted_values) or not actual_values:
        raise BaselineError("Metrics require non-empty, equally sized vectors")
    errors = [
        prediction - target
        for target, prediction in zip(actual_values, predicted_values, strict=True)
    ]
    mean_actual = statistics.fmean(actual_values)
    total_sum_squares = sum((value - mean_actual) ** 2 for value in actual_values)
    residual_sum_squares = sum(error**2 for error in errors)
    mae = statistics.fmean(abs(error) for error in errors)
    return {
        "n": len(errors),
        "mae_log10_pm": mae,
        "rmse_log10_pm": math.sqrt(statistics.fmean(error**2 for error in errors)),
        "geometric_fold_error": 10**mae,
        "pearson_r": _pearson(actual_values, predicted_values),
        "spearman_rho": _pearson(
            _average_ranks(actual_values),
            _average_ranks(predicted_values),
        ),
        "r_squared": 1 - residual_sum_squares / total_sum_squares
        if total_sum_squares
        else None,
    }


def _record_targets(record: TrainingRecord) -> dict[str, float]:
    return {
        "gcgr": record.gcgr_log10_ec50_pm,
        "glp1r": record.glp1r_log10_ec50_pm,
    }


def out_of_fold_predictions(
    records: Iterable[TrainingRecord],
    peptide_folds: dict[str, int],
) -> list[dict[str, object]]:
    """Run tied 1-NN and fold-training median baselines without tuning."""

    record_list = sorted(records, key=lambda record: record.peptide_id)
    record_ids = {record.peptide_id for record in record_list}
    if record_ids != set(peptide_folds):
        raise BaselineError("Fold assignments must match the training record IDs exactly")
    rows: list[dict[str, object]] = []
    for query in record_list:
        query_fold = peptide_folds[query.peptide_id]
        donors = [record for record in record_list if peptide_folds[record.peptide_id] != query_fold]
        if not donors:
            raise BaselineError(f"No training donors remain for fold {query_fold}")
        identities = {
            donor.peptide_id: aligned_identity(query.aligned_sequence, donor.aligned_sequence)
            for donor in donors
        }
        maximum_identity = max(identities.values())
        nearest = [
            donor
            for donor in donors
            if abs(identities[donor.peptide_id] - maximum_identity) <= 1e-12
        ]
        nearest.sort(key=lambda donor: donor.peptide_id)
        actual = _record_targets(query)
        nearest_predictions = {
            receptor: statistics.fmean(_record_targets(donor)[receptor] for donor in nearest)
            for receptor in ("gcgr", "glp1r")
        }
        median_predictions = {
            receptor: statistics.median(_record_targets(donor)[receptor] for donor in donors)
            for receptor in ("gcgr", "glp1r")
        }
        rows.append(
            {
                "peptide_id": query.peptide_id,
                "outer_fold": query_fold,
                "nearest_identity": maximum_identity,
                "nearest_tie_count": len(nearest),
                "nearest_donor_ids": ";".join(donor.peptide_id for donor in nearest),
                "actual_gcgr_log10_ec50_pm": actual["gcgr"],
                "actual_glp1r_log10_ec50_pm": actual["glp1r"],
                "actual_selectivity_log10_ratio": actual["gcgr"] - actual["glp1r"],
                "nn_gcgr_log10_ec50_pm": nearest_predictions["gcgr"],
                "nn_glp1r_log10_ec50_pm": nearest_predictions["glp1r"],
                "nn_selectivity_log10_ratio": (
                    nearest_predictions["gcgr"] - nearest_predictions["glp1r"]
                ),
                "median_gcgr_log10_ec50_pm": median_predictions["gcgr"],
                "median_glp1r_log10_ec50_pm": median_predictions["glp1r"],
                "median_selectivity_log10_ratio": (
                    median_predictions["gcgr"] - median_predictions["glp1r"]
                ),
            }
        )
    return rows


def summarize_predictions(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    endpoints = {
        "GCGR log10 EC50 (pM)": "gcgr_log10_ec50_pm",
        "GLP-1R log10 EC50 (pM)": "glp1r_log10_ec50_pm",
        "selectivity log10 ratio": "selectivity_log10_ratio",
    }
    metrics: list[dict[str, object]] = []
    for model in ("median", "nn"):
        for endpoint, column in endpoints.items():
            result = point_metrics(
                [float(row[f"actual_{column}"]) for row in rows],
                [float(row[f"{model}_{column}"]) for row in rows],
            )
            metrics.append({"model": model, "endpoint": endpoint, **result})
    return metrics
