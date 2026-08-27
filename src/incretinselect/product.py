"""Portable, research-only inference for the frozen IncretinSelect model.

The product interface is deliberately narrower than a general peptide predictor.
It accepts the same 30-column aligned representation used to train the model and
refuses to guess an alignment, truncate a sequence, or encode noncanonical
chemistry.  That restriction keeps an apparently convenient interface from
silently changing the biological object being scored.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from incretinselect import __version__
from incretinselect.clustering import aligned_identity
from incretinselect.sequence_model import DEFAULT_ALPHABET, encode_aligned_sequences

DEFAULT_ARTIFACT_NAME = "incretin_ridge_v1.json"
EXPECTED_DEFAULT_ARTIFACT_SHA256 = (
    "eb7e99bbc3d83fdfb11ded4ba215fd7f6107a6e7d254f68e1b9610da6eb7e321"
)
MODEL_INPUT_LENGTH = 30
ALLOWED_SYMBOLS = frozenset(DEFAULT_ALPHABET)


class ProductError(ValueError):
    """Raised when the portable model or a requested prediction is invalid."""


@dataclass(frozen=True)
class PortableModel:
    """Validated frozen coefficients plus applicability references without outcomes."""

    artifact_id: str
    artifact_version: str
    sha256: str
    alphabet: str
    aligned_length: int
    selected_alpha: float
    feature_mean: np.ndarray
    target_mean: np.ndarray
    coefficients: np.ndarray
    references: tuple[dict[str, str], ...]
    benchmark: dict[str, Any]
    provenance: dict[str, Any]


def _artifact_bytes(path: str | Path | None = None) -> bytes:
    if path is not None:
        return Path(path).read_bytes()
    return (
        resources.files("incretinselect")
        .joinpath("assets", DEFAULT_ARTIFACT_NAME)
        .read_bytes()
    )


def load_model(path: str | Path | None = None) -> PortableModel:
    """Load and validate the bundled frozen inference artifact."""

    try:
        raw = _artifact_bytes(path)
    except OSError as exc:
        raise ProductError(f"Could not read the model artifact: {exc}") from exc
    sha256 = hashlib.sha256(raw).hexdigest()
    if path is None and sha256 != EXPECTED_DEFAULT_ARTIFACT_SHA256:
        raise ProductError(
            "Bundled model checksum mismatch; reinstall the package before predicting"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductError("The model artifact is not valid UTF-8 JSON") from exc

    if not isinstance(payload, dict):
        raise ProductError("The model artifact root must be a JSON object")

    if payload.get("schema_version") != 1:
        raise ProductError("Only portable model schema version 1 is supported")
    if payload.get("artifact_id") != "incretinselect_aligned_ridge_v1":
        raise ProductError("Unexpected model artifact ID")

    contract = payload.get("input_contract", {})
    if not isinstance(contract, dict):
        raise ProductError("The model input contract must be a JSON object")
    alphabet = str(contract.get("alphabet", ""))
    try:
        aligned_length = int(contract.get("aligned_length", 0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProductError("The model aligned length must be an integer") from exc
    if alphabet != DEFAULT_ALPHABET or aligned_length != MODEL_INPUT_LENGTH:
        raise ProductError("The model input contract does not match this software")

    model = payload.get("model", {})
    if not isinstance(model, dict):
        raise ProductError("The model parameters must be a JSON object")
    try:
        feature_mean = np.asarray(model.get("feature_mean"), dtype=float)
        target_mean = np.asarray(model.get("target_mean"), dtype=float)
        coefficients = np.asarray(model.get("coefficients"), dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProductError("Model arrays must contain numeric values") from exc
    feature_count = aligned_length * len(alphabet)
    if feature_mean.shape != (feature_count,):
        raise ProductError("Model feature mean has the wrong shape")
    if target_mean.shape != (2,):
        raise ProductError("Model target mean has the wrong shape")
    if coefficients.shape != (feature_count, 2):
        raise ProductError("Model coefficients have the wrong shape")
    if not (
        np.isfinite(feature_mean).all()
        and np.isfinite(target_mean).all()
        and np.isfinite(coefficients).all()
    ):
        raise ProductError("Model arrays contain non-finite values")

    applicability_reference = payload.get("applicability_reference", {})
    if not isinstance(applicability_reference, dict):
        raise ProductError("The applicability reference must be a JSON object")
    if applicability_reference.get("labels_included") is not False:
        raise ProductError(
            "The applicability reference must declare labels_included=false"
        )
    references_raw = applicability_reference.get("sequences", [])
    if not isinstance(references_raw, list):
        raise ProductError("Model applicability sequences must be a JSON array")
    references: list[dict[str, str]] = []
    for row in references_raw:
        if not isinstance(row, dict):
            raise ProductError("Model applicability references are malformed")
        reference = {
            "peptide_id": str(row.get("peptide_id", "")),
            "component_id": str(row.get("component_id", "")),
            "aligned_sequence": str(row.get("aligned_sequence", "")),
        }
        if (
            not reference["peptide_id"]
            or not reference["component_id"]
            or len(reference["aligned_sequence"]) != aligned_length
            or set(reference["aligned_sequence"]) - set(alphabet)
        ):
            raise ProductError("Model applicability references are malformed")
        references.append(reference)
    if len(references) != 125 or len({row["peptide_id"] for row in references}) != 125:
        raise ProductError(
            "Model artifact must contain 125 unique references without activity outcomes"
        )

    try:
        selected_alpha = float(model.get("selected_alpha", math.nan))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProductError("Model ridge strength must be numeric") from exc
    if not math.isfinite(selected_alpha) or selected_alpha <= 0:
        raise ProductError("Model ridge strength must be positive and finite")

    benchmark = payload.get("benchmark_context", {})
    provenance = payload.get("provenance", {})
    if not isinstance(benchmark, dict) or not isinstance(provenance, dict):
        raise ProductError("Model benchmark context and provenance must be JSON objects")

    return PortableModel(
        artifact_id=str(payload["artifact_id"]),
        artifact_version=str(payload.get("artifact_version", "")),
        sha256=sha256,
        alphabet=alphabet,
        aligned_length=aligned_length,
        selected_alpha=selected_alpha,
        feature_mean=feature_mean,
        target_mean=target_mean,
        coefficients=coefficients,
        references=tuple(references),
        benchmark=dict(benchmark),
        provenance=dict(provenance),
    )


def normalize_aligned_sequence(value: str) -> str:
    """Normalize whitespace/case while enforcing the frozen 30-column contract."""

    if not isinstance(value, str):
        raise ProductError("Sequence input must be text")
    if ">" in value:
        raise ProductError(
            "FASTA headers are not accepted. Paste one 30-column aligned sequence only."
        )
    sequence = "".join(value.split()).upper()
    if not sequence:
        raise ProductError("Sequence input is empty")
    if len(sequence) != MODEL_INPUT_LENGTH:
        raise ProductError(
            "This frozen model requires exactly 30 aligned characters; "
            f"received {len(sequence)}. Add explicit '-' alignment gaps where required. "
            "The software will not guess an alignment or trim residues."
        )
    invalid = sorted(set(sequence) - ALLOWED_SYMBOLS)
    if invalid:
        raise ProductError(
            "Unsupported sequence symbols: "
            f"{''.join(invalid)}. Only the 20 standard amino acids and '-' alignment gaps "
            "are supported; modifications such as Aib or lipidation are not encoded."
        )
    if set(sequence) == {"-"}:
        raise ProductError("An all-gap sequence cannot be predicted")
    return sequence


def _applicability(sequence: str, model: PortableModel) -> dict[str, Any]:
    scored = [
        (
            aligned_identity(sequence, row["aligned_sequence"]),
            row["peptide_id"],
            row["component_id"],
        )
        for row in model.references
    ]
    maximum = max(score for score, _, _ in scored)
    nearest = sorted(
        (peptide_id, component_id)
        for score, peptide_id, component_id in scored
        if abs(score - maximum) <= 1e-12
    )
    exact_reference_match = maximum >= 1.0 - 1e-12
    if exact_reference_match:
        tier = "close_analogue"
        evidence_state = "training_reference_match"
        summary = (
            "The input matches a training reference exactly. This is an in-sample model "
            "estimate and does not demonstrate predictive accuracy on a new peptide."
        )
    elif maximum >= 0.85:
        tier = "close_analogue"
        evidence_state = "local_analogue_mixed_evidence"
        summary = (
            "The input meets the 0.85 local-analog software gate. This threshold "
            "defined benchmark sequence components; it was not calibrated to prediction "
            "error. Transfer among 15 published local analogs was mixed."
        )
    elif maximum >= 0.70:
        tier = "distant_analogue"
        evidence_state = "outside_ranking_scope"
        summary = (
            "The input falls below the 0.85 identity gate. Its numeric estimates are "
            "shown for inspection but are outside the supported ranking scope."
        )
    else:
        tier = "outside_reference_neighborhood"
        evidence_state = "far_outside_ranking_scope"
        summary = (
            "The input is far from every reference peptide. Its numeric estimates are "
            "extrapolations and should not be used to rank experiments."
        )
    return {
        "tier": tier,
        "evidence_state": evidence_state,
        "exact_reference_match": exact_reference_match,
        "nearest_aligned_identity": maximum,
        "nearest_reference_ids": [peptide_id for peptide_id, _ in nearest],
        "nearest_component_ids": sorted({component_id for _, component_id in nearest}),
        "threshold_note": (
            "The 0.85 threshold defines sequence-identity components in the benchmark; "
            "0.70 is an interface heuristic. Neither is calibrated to prediction error."
        ),
        "summary": summary,
    }


def _direction(selectivity_log10: float) -> str:
    fold_ratio = 10.0**selectivity_log10
    if fold_ratio >= 3.0:
        return "Lower predicted EC50 at GLP-1R"
    if fold_ratio <= 1.0 / 3.0:
        return "Lower predicted EC50 at GCGR"
    return "Predicted EC50 values within three-fold"


def _predict_log10_values(sequence: str, model: PortableModel) -> np.ndarray:
    """Return GCGR and GLP-1R log10 EC50 values for one validated alignment."""

    features = encode_aligned_sequences(
        [sequence],
        alphabet=model.alphabet,
        expected_length=model.aligned_length,
    )
    values = (features - model.feature_mean) @ model.coefficients + model.target_mean
    return values[0]


def _nearest_reference_comparison(
    sequence: str,
    values: np.ndarray,
    applicability: dict[str, Any],
    model: PortableModel,
) -> dict[str, Any]:
    """Exactly decompose the linear-model contrast to one nearest reference.

    The coefficients make this an algebraic explanation of the model output. It
    is not a causal estimate of what an experimental substitution will do.
    """

    reference_id = str(applicability["nearest_reference_ids"][0])
    reference = next(row for row in model.references if row["peptide_id"] == reference_id)
    reference_sequence = reference["aligned_sequence"]
    reference_values = _predict_log10_values(reference_sequence, model)
    alphabet_index = {symbol: index for index, symbol in enumerate(model.alphabet)}
    width = len(model.alphabet)
    changes: list[dict[str, Any]] = []
    contribution_sum = np.zeros(2, dtype=float)
    for position, (reference_symbol, query_symbol) in enumerate(
        zip(reference_sequence, sequence, strict=True),
        start=1,
    ):
        if reference_symbol == query_symbol:
            continue
        query_index = (position - 1) * width + alphabet_index[query_symbol]
        reference_index = (position - 1) * width + alphabet_index[reference_symbol]
        contribution = model.coefficients[query_index] - model.coefficients[reference_index]
        contribution_sum += contribution
        gcgr_delta, glp1r_delta = map(float, contribution)
        changes.append(
            {
                "alignment_position": position,
                "reference_symbol": reference_symbol,
                "query_symbol": query_symbol,
                "gcgr_delta_log10_ec50_pm": gcgr_delta,
                "glp1r_delta_log10_ec50_pm": glp1r_delta,
                "selectivity_delta_log10_ratio": gcgr_delta - glp1r_delta,
            }
        )

    delta = np.asarray(values, dtype=float) - reference_values
    residual = delta - contribution_sum
    gcgr_delta, glp1r_delta = map(float, delta)
    return {
        "reference_id": reference_id,
        "reference_component_id": reference["component_id"],
        "reference_aligned_sequence": reference_sequence,
        "nearest_reference_tie_count": len(applicability["nearest_reference_ids"]),
        "changed_position_count": len(changes),
        "reference_prediction": {
            "gcgr_log10_ec50_pm": float(reference_values[0]),
            "glp1r_log10_ec50_pm": float(reference_values[1]),
        },
        "query_minus_reference": {
            "gcgr_delta_log10_ec50_pm": gcgr_delta,
            "glp1r_delta_log10_ec50_pm": glp1r_delta,
            "selectivity_delta_log10_ratio": gcgr_delta - glp1r_delta,
            "gcgr_ec50_fold_ratio": 10.0**gcgr_delta,
            "glp1r_ec50_fold_ratio": 10.0**glp1r_delta,
        },
        "position_contributions": changes,
        "decomposition_max_abs_residual_log10": float(np.max(np.abs(residual))),
        "interpretation": (
            "Positive deltas mean the query has a higher predicted EC50 than the "
            "reference; negative deltas mean a lower predicted EC50."
        ),
        "scientific_boundary": (
            "This is an exact decomposition of the fitted linear model, not a causal "
            "substitution effect or experimental validation."
        ),
    }


def predict(sequence: str, model: PortableModel | None = None) -> dict[str, Any]:
    """Predict two cAMP EC50 endpoints and their derived potency balance."""

    fitted = model or load_model()
    normalized = normalize_aligned_sequence(sequence)
    values = _predict_log10_values(normalized, fitted)
    gcgr_log10, glp1r_log10 = map(float, values)
    gcgr_pm = 10.0**gcgr_log10
    glp1r_pm = 10.0**glp1r_log10
    selectivity = gcgr_log10 - glp1r_log10
    applicability = _applicability(normalized, fitted)
    comparison = _nearest_reference_comparison(
        normalized,
        values,
        applicability,
        fitted,
    )

    residue_count = sum(symbol != "-" for symbol in normalized)
    ranking_exclusions: list[str] = []
    if applicability["tier"] != "close_analogue":
        ranking_exclusions.append(str(applicability["summary"]))
    if residue_count < 26:
        ranking_exclusions.append(
            f"The input contains {residue_count} standard residues; exploratory ranking "
            "requires at least 26."
        )
    ranking_support = {
        "enabled": not ranking_exclusions,
        "identity_gate": 0.85,
        "minimum_standard_residue_count": 26,
        "exclusion_reasons": ranking_exclusions,
        "boundary": (
            "Passing these software gates does not establish prediction accuracy or "
            "experimental priority."
        ),
    }

    warnings = [
        (
            "Estimates apply to the source study's cell-based cAMP assay and do not "
            "measure binding affinity, maximal assay response, safety, or in vivo activity."
        ),
        (
            "The locked retrospective P1–P15 external evaluation was mixed: ridge had "
            "lower GCGR point error, but its dependence-aware interval crossed zero, "
            "and higher pooled GLP-1R error than 1-NN."
        ),
        (
            "The model cannot represent Aib, lipidation, amidation, cyclization, stapling, "
            "or other noncanonical chemistry. '-' means an alignment gap only."
        ),
    ]
    warnings.extend(ranking_exclusions)
    if applicability["exact_reference_match"]:
        warnings.append(str(applicability["summary"]))

    return {
        "schema_version": 1,
        "model": {
            "software_version": __version__,
            "artifact_id": fitted.artifact_id,
            "artifact_version": fitted.artifact_version,
            "artifact_sha256": fitted.sha256,
            "selected_alpha": fitted.selected_alpha,
            "training_records": 125,
        },
        "input": {
            "aligned_sequence": normalized,
            "aligned_length": len(normalized),
            "standard_residue_count": residue_count,
            "alignment_gaps": normalized.count("-"),
        },
        "predictions": {
            "gcgr": {
                "endpoint": "cAMP accumulation EC50",
                "log10_ec50_pm": gcgr_log10,
                "ec50_pm": gcgr_pm,
                "ec50_nm": gcgr_pm / 1000.0,
            },
            "glp1r": {
                "endpoint": "cAMP accumulation EC50",
                "log10_ec50_pm": glp1r_log10,
                "ec50_pm": glp1r_pm,
                "ec50_nm": glp1r_pm / 1000.0,
            },
            "selectivity": {
                "definition": "GCGR EC50 / GLP-1R EC50",
                "log10_ec50_ratio": selectivity,
                "ec50_fold_ratio": 10.0**selectivity,
                "interpretation": _direction(selectivity),
                "interpretation_boundary": (
                    "The three-fold wording is descriptive, not a validated decision cutoff."
                ),
            },
        },
        "applicability": applicability,
        "exploratory_ranking": ranking_support,
        "nearest_reference_comparison": comparison,
        "benchmark_context": fitted.benchmark,
        "warnings": warnings,
    }


def model_info(model: PortableModel | None = None) -> dict[str, Any]:
    """Return provenance without exposing assay outcomes or refitting the model."""

    fitted = model or load_model()
    return {
        "artifact_id": fitted.artifact_id,
        "artifact_version": fitted.artifact_version,
        "artifact_sha256": fitted.sha256,
        "input_contract": {
            "aligned_length": fitted.aligned_length,
            "alphabet": fitted.alphabet,
        },
        "selected_alpha": fitted.selected_alpha,
        "applicability_reference_sequences": len(fitted.references),
        "benchmark_context": fitted.benchmark,
        "provenance": fitted.provenance,
    }
