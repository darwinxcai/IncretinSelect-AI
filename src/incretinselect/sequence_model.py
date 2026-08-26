"""Nested, component-held-out ridge modeling for aligned peptide sequences.

The implementation intentionally stays small and auditable.  It uses only the
frozen training alignment and sequence-component assignments; prospective
sequences and labels are not inputs to any function in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from numpy.typing import NDArray

from incretinselect.training import TrainingRecord

DEFAULT_ALPHABET = "-ACDEFGHIKLMNPQRSTVWY"


class SequenceModelError(ValueError):
    """Raised when a sequence-model fit would violate its data contract."""


FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class RidgeFit:
    """A weighted multi-output ridge fit with an unpenalized intercept."""

    feature_mean: FloatArray
    target_mean: FloatArray
    coefficients: FloatArray
    alpha: float

    def predict(self, features: FloatArray) -> FloatArray:
        matrix = _as_feature_matrix(features)
        if matrix.shape[1] != self.feature_mean.shape[0]:
            raise SequenceModelError("Prediction features do not match the fitted width")
        return (matrix - self.feature_mean) @ self.coefficients + self.target_mean


@dataclass(frozen=True)
class NestedRidgeResult:
    """Outer-fold predictions and training-only hyperparameter selections."""

    rows: tuple[dict[str, object], ...]
    selections: tuple[dict[str, object], ...]


def _as_feature_matrix(values: FloatArray) -> FloatArray:
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise SequenceModelError("Features must be a non-empty two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise SequenceModelError("Features must be finite")
    return matrix


def _as_target_matrix(values: FloatArray, expected_rows: int) -> FloatArray:
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix[:, None]
    if matrix.ndim != 2 or matrix.shape[0] != expected_rows or matrix.shape[1] == 0:
        raise SequenceModelError("Targets must match the feature rows")
    if not np.isfinite(matrix).all():
        raise SequenceModelError("Targets must be finite")
    return matrix


def encode_aligned_sequences(
    sequences: Iterable[str],
    *,
    alphabet: str = DEFAULT_ALPHABET,
    expected_length: int | None = None,
) -> FloatArray:
    """Return fixed position-specific one-hot features for aligned sequences."""

    sequence_list = [str(sequence).upper() for sequence in sequences]
    if not sequence_list:
        raise SequenceModelError("At least one aligned sequence is required")
    if not alphabet or len(set(alphabet)) != len(alphabet):
        raise SequenceModelError("The feature alphabet must contain unique symbols")
    lengths = {len(sequence) for sequence in sequence_list}
    if len(lengths) != 1:
        raise SequenceModelError("Aligned sequences must have one common length")
    aligned_length = lengths.pop()
    if aligned_length == 0:
        raise SequenceModelError("Aligned sequences cannot be empty")
    if expected_length is not None and aligned_length != expected_length:
        raise SequenceModelError(
            f"Expected aligned length {expected_length}; observed {aligned_length}"
        )
    invalid = sorted(set().union(*map(set, sequence_list)) - set(alphabet))
    if invalid:
        raise SequenceModelError(f"Aligned sequences contain unsupported symbols: {''.join(invalid)}")

    symbol_index = {symbol: index for index, symbol in enumerate(alphabet)}
    features = np.zeros((len(sequence_list), aligned_length * len(alphabet)), dtype=float)
    for row, sequence in enumerate(sequence_list):
        for position, symbol in enumerate(sequence):
            features[row, position * len(alphabet) + symbol_index[symbol]] = 1.0
    return features


def component_sample_weights(components: Sequence[str]) -> FloatArray:
    """Give every component equal total fit weight and normalize mean weight to one."""

    labels = np.asarray([str(component) for component in components], dtype=object)
    if labels.ndim != 1 or labels.size == 0 or any(not label for label in labels):
        raise SequenceModelError("Every training row needs a non-empty component ID")
    counts = {label: int(np.count_nonzero(labels == label)) for label in set(labels)}
    weights = np.asarray([1.0 / counts[label] for label in labels], dtype=float)
    return weights / float(np.mean(weights))


def fit_component_weighted_ridge(
    features: FloatArray,
    targets: FloatArray,
    components: Sequence[str],
    alpha: float,
) -> RidgeFit:
    """Fit ridge regression with training-component-balanced squared loss."""

    matrix = _as_feature_matrix(features)
    target_matrix = _as_target_matrix(targets, matrix.shape[0])
    if len(components) != matrix.shape[0]:
        raise SequenceModelError("Component IDs must match the feature rows")
    if not np.isfinite(alpha) or alpha <= 0:
        raise SequenceModelError("Ridge alpha must be positive and finite")

    weights = component_sample_weights(components)
    feature_mean = np.average(matrix, axis=0, weights=weights)
    target_mean = np.average(target_matrix, axis=0, weights=weights)
    square_root_weights = np.sqrt(weights)
    weighted_features = (matrix - feature_mean) * square_root_weights[:, None]
    weighted_targets = (target_matrix - target_mean) * square_root_weights[:, None]

    # The dual system is at most n_training by n_training (rather than 630 by
    # 630 for this alignment), making the complete nested analysis inexpensive.
    system = weighted_features @ weighted_features.T
    system.flat[:: system.shape[0] + 1] += float(alpha)
    dual_coefficients = np.linalg.solve(system, weighted_targets)
    coefficients = weighted_features.T @ dual_coefficients
    return RidgeFit(feature_mean, target_mean, coefficients, float(alpha))


def select_alpha_leave_one_component_out(
    features: FloatArray,
    targets: FloatArray,
    components: Sequence[str],
    alpha_grid: Iterable[float],
) -> tuple[float, list[dict[str, float]]]:
    """Select alpha using only training components and a component-macro loss."""

    matrix = _as_feature_matrix(features)
    target_matrix = _as_target_matrix(targets, matrix.shape[0])
    labels = np.asarray([str(component) for component in components], dtype=object)
    if labels.shape != (matrix.shape[0],):
        raise SequenceModelError("Component IDs must match the feature rows")
    unique_components = sorted(set(labels))
    if len(unique_components) < 2:
        raise SequenceModelError("Inner selection requires at least two sequence components")
    candidates = sorted(set(float(value) for value in alpha_grid))
    if not candidates or any(not np.isfinite(value) or value <= 0 for value in candidates):
        raise SequenceModelError("The alpha grid must contain positive finite values")

    scores: list[dict[str, float]] = []
    for alpha in candidates:
        component_losses: list[float] = []
        for held_component in unique_components:
            validation_mask = labels == held_component
            training_mask = ~validation_mask
            fit = fit_component_weighted_ridge(
                matrix[training_mask],
                target_matrix[training_mask],
                labels[training_mask].tolist(),
                alpha,
            )
            absolute_errors = np.abs(fit.predict(matrix[validation_mask]) - target_matrix[validation_mask])
            component_losses.append(float(np.mean(absolute_errors)))
        scores.append(
            {
                "alpha": alpha,
                "component_macro_two_receptor_mae": float(np.mean(component_losses)),
            }
        )
    selected = min(
        scores,
        key=lambda row: (row["component_macro_two_receptor_mae"], row["alpha"]),
    )
    return selected["alpha"], scores


def nested_component_ridge_predictions(
    records: Iterable[TrainingRecord],
    peptide_folds: dict[str, int],
    peptide_components: dict[str, str],
    alpha_grid: Iterable[float],
    *,
    alphabet: str = DEFAULT_ALPHABET,
    expected_length: int | None = None,
) -> NestedRidgeResult:
    """Generate one ridge prediction per record under frozen outer folds."""

    record_list = sorted(records, key=lambda record: record.peptide_id)
    record_ids = {record.peptide_id for record in record_list}
    if record_ids != set(peptide_folds) or record_ids != set(peptide_components):
        raise SequenceModelError("Fold and component assignments must exactly match record IDs")
    component_folds: dict[str, set[int]] = {}
    for peptide_id in sorted(record_ids):
        component = peptide_components[peptide_id]
        fold = peptide_folds[peptide_id]
        if not component:
            raise SequenceModelError(f"Missing component assignment for {peptide_id}")
        component_folds.setdefault(component, set()).add(fold)
    leaking = sorted(component for component, folds in component_folds.items() if len(folds) != 1)
    if leaking:
        raise SequenceModelError(f"Sequence components cross outer folds: {', '.join(leaking)}")

    features = encode_aligned_sequences(
        [record.aligned_sequence for record in record_list],
        alphabet=alphabet,
        expected_length=expected_length,
    )
    targets = np.asarray(
        [
            [record.gcgr_log10_ec50_pm, record.glp1r_log10_ec50_pm]
            for record in record_list
        ],
        dtype=float,
    )
    folds = np.asarray([peptide_folds[record.peptide_id] for record in record_list], dtype=int)
    components = np.asarray(
        [peptide_components[record.peptide_id] for record in record_list], dtype=object
    )
    outer_folds = sorted(set(int(fold) for fold in folds))
    if len(outer_folds) < 2:
        raise SequenceModelError("Outer evaluation requires at least two folds")

    predictions = np.empty_like(targets)
    selected_by_row = np.empty(len(record_list), dtype=float)
    selections: list[dict[str, object]] = []
    for outer_fold in outer_folds:
        test_mask = folds == outer_fold
        training_mask = ~test_mask
        selected_alpha, scores = select_alpha_leave_one_component_out(
            features[training_mask],
            targets[training_mask],
            components[training_mask].tolist(),
            alpha_grid,
        )
        fit = fit_component_weighted_ridge(
            features[training_mask],
            targets[training_mask],
            components[training_mask].tolist(),
            selected_alpha,
        )
        predictions[test_mask] = fit.predict(features[test_mask])
        selected_by_row[test_mask] = selected_alpha
        selections.append(
            {
                "outer_fold": outer_fold,
                "outer_training_records": int(np.count_nonzero(training_mask)),
                "outer_test_records": int(np.count_nonzero(test_mask)),
                "outer_training_components": len(set(components[training_mask])),
                "selected_alpha": selected_alpha,
                "inner_scores": scores,
            }
        )

    rows: list[dict[str, object]] = []
    for index, record in enumerate(record_list):
        predicted_gcgr, predicted_glp1r = map(float, predictions[index])
        rows.append(
            {
                "peptide_id": record.peptide_id,
                "cluster_id": peptide_components[record.peptide_id],
                "outer_fold": peptide_folds[record.peptide_id],
                "selected_alpha": float(selected_by_row[index]),
                "actual_gcgr_log10_ec50_pm": record.gcgr_log10_ec50_pm,
                "actual_glp1r_log10_ec50_pm": record.glp1r_log10_ec50_pm,
                "actual_selectivity_log10_ratio": record.selectivity_log10_ratio,
                "ridge_gcgr_log10_ec50_pm": predicted_gcgr,
                "ridge_glp1r_log10_ec50_pm": predicted_glp1r,
                "ridge_selectivity_log10_ratio": predicted_gcgr - predicted_glp1r,
            }
        )
    return NestedRidgeResult(tuple(rows), tuple(selections))


def component_macro_mae(
    actual: Sequence[float], predicted: Sequence[float], components: Sequence[str]
) -> float:
    """Average component-specific MAEs with one vote per sequence component."""

    actual_array = np.asarray(actual, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    labels = np.asarray([str(component) for component in components], dtype=object)
    if (
        actual_array.ndim != 1
        or predicted_array.shape != actual_array.shape
        or labels.shape != actual_array.shape
        or actual_array.size == 0
    ):
        raise SequenceModelError("Macro MAE inputs must be non-empty, equally sized vectors")
    return float(
        np.mean(
            [
                np.mean(np.abs(predicted_array[labels == component] - actual_array[labels == component]))
                for component in sorted(set(labels))
            ]
        )
    )


def paired_component_bootstrap_mae_delta(
    actual: Sequence[float],
    challenger: Sequence[float],
    baseline: Sequence[float],
    components: Sequence[str],
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, float | int]:
    """Cluster-bootstrap the paired pooled-MAE delta (challenger minus baseline)."""

    actual_array = np.asarray(actual, dtype=float)
    challenger_array = np.asarray(challenger, dtype=float)
    baseline_array = np.asarray(baseline, dtype=float)
    labels = np.asarray([str(component) for component in components], dtype=object)
    if (
        actual_array.ndim != 1
        or challenger_array.shape != actual_array.shape
        or baseline_array.shape != actual_array.shape
        or labels.shape != actual_array.shape
        or actual_array.size == 0
    ):
        raise SequenceModelError("Bootstrap inputs must be non-empty, equally sized vectors")
    if resamples < 1 or not 0 < confidence_level < 1:
        raise SequenceModelError("Bootstrap settings are invalid")
    error_delta = np.abs(challenger_array - actual_array) - np.abs(baseline_array - actual_array)
    unique_components = sorted(set(labels))
    component_sums = np.asarray(
        [float(np.sum(error_delta[labels == component])) for component in unique_components]
    )
    component_sizes = np.asarray(
        [int(np.count_nonzero(labels == component)) for component in unique_components]
    )
    generator = np.random.default_rng(seed)
    samples = generator.integers(
        0,
        len(unique_components),
        size=(resamples, len(unique_components)),
    )
    sampled_deltas = component_sums[samples].sum(axis=1) / component_sizes[samples].sum(axis=1)
    tail = (1.0 - confidence_level) / 2.0
    return {
        "mae_delta_log10_pm": float(np.mean(error_delta)),
        "confidence_level": confidence_level,
        "ci_lower": float(np.quantile(sampled_deltas, tail)),
        "ci_upper": float(np.quantile(sampled_deltas, 1.0 - tail)),
        "resamples": resamples,
        "seed": seed,
        "components": len(unique_components),
    }
