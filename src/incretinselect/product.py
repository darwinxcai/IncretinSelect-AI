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
    """Validated frozen coefficients plus label-free applicability references."""

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

    raw = _artifact_bytes(path)
    sha256 = hashlib.sha256(raw).hexdigest()
    if path is None and sha256 != EXPECTED_DEFAULT_ARTIFACT_SHA256:
        raise ProductError(
            "Bundled model checksum mismatch; reinstall the package before predicting"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductError("The model artifact is not valid UTF-8 JSON") from exc

    if payload.get("schema_version") != 1:
        raise ProductError("Only portable model schema version 1 is supported")
    if payload.get("artifact_id") != "incretinselect_aligned_ridge_v1":
        raise ProductError("Unexpected model artifact ID")

    contract = payload.get("input_contract", {})
    alphabet = str(contract.get("alphabet", ""))
    aligned_length = int(contract.get("aligned_length", 0))
    if alphabet != DEFAULT_ALPHABET or aligned_length != MODEL_INPUT_LENGTH:
        raise ProductError("The model input contract does not match this software")

    model = payload.get("model", {})
    feature_mean = np.asarray(model.get("feature_mean"), dtype=float)
    target_mean = np.asarray(model.get("target_mean"), dtype=float)
    coefficients = np.asarray(model.get("coefficients"), dtype=float)
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

    references_raw = payload.get("applicability_reference", {}).get("sequences", [])
    references: list[dict[str, str]] = []
    for row in references_raw:
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
        raise ProductError("Model artifact must contain 125 unique label-free references")

    selected_alpha = float(model.get("selected_alpha", math.nan))
    if not math.isfinite(selected_alpha) or selected_alpha <= 0:
        raise ProductError("Model ridge strength must be positive and finite")

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
        benchmark=dict(payload.get("benchmark_context", {})),
        provenance=dict(payload.get("provenance", {})),
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
    if maximum >= 0.85:
        tier = "close_analogue"
        summary = (
            "The input has a close aligned-sequence analogue in the 125-peptide "
            "reference set. This supports interpolation, but does not validate the estimate."
        )
    elif maximum >= 0.70:
        tier = "distant_analogue"
        summary = (
            "The input is not a close analogue of the reference peptides. Treat both "
            "receptor estimates as high-risk extrapolations."
        )
    else:
        tier = "outside_reference_neighborhood"
        summary = (
            "The input is far from every reference peptide. The numeric output is an "
            "extrapolation and should not be used to rank experiments."
        )
    return {
        "tier": tier,
        "nearest_aligned_identity": maximum,
        "nearest_reference_ids": [peptide_id for peptide_id, _ in nearest],
        "nearest_component_ids": sorted({component_id for _, component_id in nearest}),
        "threshold_note": (
            "The 0.85 boundary was the benchmark's sequence-family threshold. The 0.70 "
            "lower display boundary is a conservative interface heuristic. Neither is a "
            "calibrated probability-of-correctness cutoff."
        ),
        "summary": summary,
    }


def _direction(selectivity_log10: float) -> str:
    fold_ratio = 10.0**selectivity_log10
    if fold_ratio >= 3.0:
        return "GLP-1R-favoured predicted functional potency"
    if fold_ratio <= 1.0 / 3.0:
        return "GCGR-favoured predicted functional potency"
    return "roughly balanced predicted functional potency (within three-fold)"


def predict(sequence: str, model: PortableModel | None = None) -> dict[str, Any]:
    """Predict two cAMP EC50 endpoints and their derived potency balance."""

    fitted = model or load_model()
    normalized = normalize_aligned_sequence(sequence)
    features = encode_aligned_sequences(
        [normalized],
        alphabet=fitted.alphabet,
        expected_length=fitted.aligned_length,
    )
    values = (features - fitted.feature_mean) @ fitted.coefficients + fitted.target_mean
    gcgr_log10, glp1r_log10 = map(float, values[0])
    gcgr_pm = 10.0**gcgr_log10
    glp1r_pm = 10.0**glp1r_log10
    selectivity = gcgr_log10 - glp1r_log10
    applicability = _applicability(normalized, fitted)

    warnings = [
        (
            "Research use only: these are sequence-model point estimates of cell-based "
            "cAMP EC50 functional potency, not binding affinity, efficacy, safety, or "
            "activity in animals or people."
        ),
        (
            "The separate 15-peptide evaluation was mixed: the GCGR point error was lower "
            "but its dependence-aware interval crossed zero, while pooled GLP-1R error "
            "was worse versus the nearest-neighbour comparator."
        ),
        (
            "The model cannot represent Aib, lipidation, amidation, cyclization, stapling, "
            "or other noncanonical chemistry. '-' means an alignment gap only."
        ),
    ]
    if applicability["tier"] != "close_analogue":
        warnings.append(str(applicability["summary"]))
    residue_count = sum(symbol != "-" for symbol in normalized)
    if residue_count < 26:
        warnings.append(
            "The input has fewer residues than any modeled 30-column core; this is outside "
            "the training length range and should not be used for candidate ranking."
        )

    return {
        "schema_version": 1,
        "model": {
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
