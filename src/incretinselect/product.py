"""Portable, research-only inference for the frozen IncretinSelect model.

The model still consumes the same 30 alignment columns used during training.
For convenience, the product can map an unaligned 26--30-residue canonical
sequence into those columns when the label-free reference panel gives one
unambiguous projection. It never truncates terminal extensions or invents a
mapping when equally scoring projections disagree.
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
DEFAULT_ALIGNMENT_POLICY_NAME = "raw_alignment_adapter.json"
EXPECTED_ALIGNMENT_POLICY_SHA256 = (
    "a606f0edda342471dc5e42d667d05506ac604c53cd221ecd8e1821edff6fd5fe"
)
MODEL_INPUT_LENGTH = 30
ALLOWED_SYMBOLS = frozenset(DEFAULT_ALPHABET)
STANDARD_RESIDUES = frozenset(DEFAULT_ALPHABET.replace("-", ""))
AUTOALIGN_MIN_RESIDUES = 26
AUTOALIGN_MAX_RESIDUES = MODEL_INPUT_LENGTH

# Fixed, documented sequence-to-reference scoring for the input adapter. These
# values do not affect the frozen ridge coefficients or any benchmark result.
AUTOALIGN_MATCH_SCORE = 0
AUTOALIGN_MISMATCH_SCORE = -1
AUTOALIGN_REFERENCE_GAP_RESIDUE_SCORE = -1
AUTOALIGN_QUERY_GAP_RESIDUE_SCORE = -1


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


def load_alignment_policy() -> dict[str, Any]:
    """Load and validate the separately frozen raw-sequence adapter policy."""

    raw = (
        resources.files("incretinselect")
        .joinpath("resources", DEFAULT_ALIGNMENT_POLICY_NAME)
        .read_bytes()
    )
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != EXPECTED_ALIGNMENT_POLICY_SHA256:
        raise ProductError(
            "Bundled raw-alignment policy checksum mismatch; reinstall the package"
        )
    try:
        policy = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductError("The raw-alignment policy is not valid UTF-8 JSON") from exc
    acceptance = policy.get("acceptance_policy", {})
    alignment = policy.get("alignment_policy", {})
    if (
        policy.get("schema_version") != 1
        or policy.get("adapter_id") != "raw_alignment_adapter_v1"
        or policy.get("adapter_version") != "1.0.0"
        or policy.get("canonical_alphabet") != DEFAULT_ALPHABET.replace("-", "")
        or policy.get("labels_accessed") is not False
        or policy.get("model_coefficients_changed") is not False
        or acceptance.get("minimum_raw_residues") != AUTOALIGN_MIN_RESIDUES
        or acceptance.get("maximum_raw_residues") != AUTOALIGN_MAX_RESIDUES
        or acceptance.get("minimum_nearest_aligned_identity") != 0.85
        or acceptance.get("ambiguous_projection") != "reject"
        or acceptance.get("terminal_trimming") is not False
        or alignment.get("model_columns") != MODEL_INPUT_LENGTH
    ):
        raise ProductError("The raw-alignment policy does not match this software")
    return {**policy, "sha256": sha256}


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
    compacted = "".join(value.split())
    non_ascii = sorted({symbol for symbol in compacted if not symbol.isascii()})
    if non_ascii:
        raise ProductError(
            "Sequence input must use ASCII amino-acid letters; unsupported symbols: "
            + "".join(non_ascii)
        )
    sequence = compacted.upper()
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


def _normalize_sequence_text(value: str) -> str:
    """Normalize one sequence without yet deciding whether it is aligned."""

    if not isinstance(value, str):
        raise ProductError("Sequence input must be text")
    if ">" in value:
        raise ProductError(
            "FASTA headers are not accepted in the sequence value. Use the FASTA file "
            "option or provide the sequence alone."
        )
    compacted = "".join(value.split())
    non_ascii = sorted({symbol for symbol in compacted if not symbol.isascii()})
    if non_ascii:
        raise ProductError(
            "Sequence input must use ASCII amino-acid letters; unsupported symbols: "
            + "".join(non_ascii)
        )
    sequence = compacted.upper()
    if not sequence:
        raise ProductError("Sequence input is empty")
    invalid = sorted(set(sequence) - ALLOWED_SYMBOLS)
    if invalid:
        raise ProductError(
            "Unsupported sequence symbols: "
            f"{''.join(invalid)}. Only the 20 standard amino acids and '-' alignment gaps "
            "are supported; modifications such as Aib or lipidation are not encoded."
        )
    return sequence


def _retain_two(values: set[str]) -> tuple[str, ...]:
    """Retain enough distinct paths to prove an alignment is ambiguous."""

    return tuple(sorted(values)[:2])


def _align_raw_to_reference(raw_sequence: str, reference: str) -> tuple[int, tuple[str, ...]]:
    """Project a raw sequence onto one 30-column reference without truncation.

    Dynamic programming permits a gap in the query at any model column but does
    not discard query residues. The cost is 30-column Hamming distance to the
    reference (exact match 0; every differing column 1). At most two optimal
    strings are retained because two are sufficient to reject non-uniqueness.
    """

    query_length = len(raw_sequence)
    column_count = len(reference)
    unreachable = -10**9
    scores = [[unreachable] * (column_count + 1) for _ in range(query_length + 1)]
    paths: list[list[tuple[str, ...]]] = [
        [tuple() for _ in range(column_count + 1)]
        for _ in range(query_length + 1)
    ]
    scores[0][0] = 0
    paths[0][0] = ("",)

    def update(
        query_index: int,
        column_index: int,
        score: int,
        candidates: set[str],
    ) -> None:
        if score > scores[query_index][column_index]:
            scores[query_index][column_index] = score
            paths[query_index][column_index] = _retain_two(candidates)
        elif score == scores[query_index][column_index]:
            paths[query_index][column_index] = _retain_two(
                set(paths[query_index][column_index]) | candidates
            )

    for column_index, reference_symbol in enumerate(reference):
        for query_index in range(query_length + 1):
            current_paths = paths[query_index][column_index]
            if not current_paths:
                continue
            query_gap_score = (
                0 if reference_symbol == "-" else AUTOALIGN_QUERY_GAP_RESIDUE_SCORE
            )
            update(
                query_index,
                column_index + 1,
                scores[query_index][column_index] + query_gap_score,
                {path + "-" for path in current_paths},
            )
            if query_index == query_length:
                continue
            query_symbol = raw_sequence[query_index]
            if reference_symbol == query_symbol:
                residue_score = AUTOALIGN_MATCH_SCORE
            elif reference_symbol == "-":
                residue_score = AUTOALIGN_REFERENCE_GAP_RESIDUE_SCORE
            else:
                residue_score = AUTOALIGN_MISMATCH_SCORE
            update(
                query_index + 1,
                column_index + 1,
                scores[query_index][column_index] + residue_score,
                {path + query_symbol for path in current_paths},
            )
    return scores[query_length][column_count], paths[query_length][column_count]


def prepare_sequence(value: str, model: PortableModel) -> dict[str, Any]:
    """Return the frozen 30-column representation plus auditable mapping metadata."""

    sequence = _normalize_sequence_text(value)
    policy = load_alignment_policy()
    if "-" in sequence:
        aligned = normalize_aligned_sequence(sequence)
        return {
            "original_sequence": sequence,
            "aligned_sequence": aligned,
            "input_residue_count": sum(symbol != "-" for symbol in sequence),
            "alignment_method": "provided_30_column_alignment",
            "alignment_status": "provided",
            "alignment_reference_ids": [],
            "alignment_score": None,
            "alignment_note": (
                "The user supplied all 30 model columns, including explicit alignment gaps."
            ),
            "alignment_adapter_id": None,
            "alignment_adapter_version": None,
            "alignment_adapter_sha256": None,
        }

    residue_count = len(sequence)
    if residue_count > AUTOALIGN_MAX_RESIDUES:
        raise ProductError(
            f"The frozen model has {MODEL_INPUT_LENGTH} alignment columns, but the raw "
            f"sequence contains {residue_count} residues. Terminal extensions or "
            "insertions are not truncated automatically."
        )
    if residue_count < AUTOALIGN_MIN_RESIDUES:
        raise ProductError(
            f"Automatic alignment supports {AUTOALIGN_MIN_RESIDUES}--"
            f"{AUTOALIGN_MAX_RESIDUES} standard residues, matching the development "
            f"sequence range; received {residue_count}. A shorter peptide requires a "
            "scientifically reviewed 30-column alignment."
        )
    if set(sequence) - STANDARD_RESIDUES:
        raise ProductError("Automatic alignment accepts standard amino-acid letters only")
    if residue_count == MODEL_INPUT_LENGTH:
        nearest_identity = max(
            aligned_identity(sequence, reference["aligned_sequence"])
            for reference in model.references
        )
        if nearest_identity < 0.85:
            raise ProductError(
                "Raw-sequence mode is limited to local analogs: the sequence is only "
                f"{nearest_identity * 100:.1f}% identical to the reference panel, below "
                "the preset 85% gate. Expert users may instead provide an explicit "
                "30-column alignment for transparent out-of-scope inspection."
            )
        return {
            "original_sequence": sequence,
            "aligned_sequence": sequence,
            "input_residue_count": residue_count,
            "alignment_method": "direct_30_column_sequence",
            "alignment_status": "not_required",
            "alignment_reference_ids": [],
            "alignment_score": None,
            "alignment_note": "The 30-residue input directly fills the 30 model columns.",
            "alignment_adapter_id": policy["adapter_id"],
            "alignment_adapter_version": policy["adapter_version"],
            "alignment_adapter_sha256": policy["sha256"],
        }

    best_score: int | None = None
    best_alignments: set[str] = set()
    best_reference_ids: set[str] = set()
    for reference in model.references:
        score, alignments = _align_raw_to_reference(
            sequence,
            reference["aligned_sequence"],
        )
        if best_score is None or score > best_score:
            best_score = score
            best_alignments = set(alignments)
            best_reference_ids = {reference["peptide_id"]}
        elif score == best_score:
            best_alignments.update(alignments)
            best_reference_ids.add(reference["peptide_id"])
        if len(best_alignments) > 2:
            best_alignments = set(sorted(best_alignments)[:2])

    if best_score is None or not best_alignments:
        raise ProductError("The raw sequence could not be mapped to the model alignment")
    if len(best_alignments) != 1:
        raise ProductError(
            "Automatic alignment is ambiguous: equally scoring reference mappings place "
            "residues in different model columns. Supply a reviewed 30-column alignment "
            "with explicit '-' gaps."
        )
    aligned = next(iter(best_alignments))
    nearest_identity = max(
        aligned_identity(aligned, reference["aligned_sequence"])
        for reference in model.references
    )
    if nearest_identity < 0.85:
        raise ProductError(
            "Automatic alignment is limited to local analogs: the best projected "
            f"alignment is only {nearest_identity * 100:.1f}% identical to the reference "
            "panel, below the preset 85% gate. Supply a reviewed 30-column alignment "
            "only if an expert mapping is available."
        )
    return {
        "original_sequence": sequence,
        "aligned_sequence": aligned,
        "input_residue_count": residue_count,
        "alignment_method": "reference_panel_auto_alignment",
        "alignment_status": "mapped_unambiguously",
        "alignment_reference_ids": sorted(best_reference_ids),
        "alignment_score": best_score,
        "alignment_note": (
            f"The {residue_count}-residue input was mapped without truncation to the "
            "frozen 30-column coordinate system. The alignment score is an input-mapping "
            "heuristic, not prediction confidence."
        ),
        "alignment_adapter_id": policy["adapter_id"],
        "alignment_adapter_version": policy["adapter_version"],
        "alignment_adapter_sha256": policy["sha256"],
    }


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
        return "GLP-1R-favored"
    if fold_ratio <= 1.0 / 3.0:
        return "GCGR-favored"
    return "Approximately balanced"


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


def _predict_prepared(prepared: dict[str, Any], fitted: PortableModel) -> dict[str, Any]:
    """Predict from an explicit, audited preparation record."""

    normalized = str(prepared["aligned_sequence"])
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
            "original_sequence": prepared["original_sequence"],
            "aligned_sequence": normalized,
            "aligned_length": len(normalized),
            "standard_residue_count": residue_count,
            "alignment_gaps": normalized.count("-"),
            "input_residue_count": prepared["input_residue_count"],
            "alignment_method": prepared["alignment_method"],
            "alignment_status": prepared["alignment_status"],
            "alignment_reference_ids": prepared["alignment_reference_ids"],
            "alignment_score": prepared["alignment_score"],
            "alignment_note": prepared["alignment_note"],
            "alignment_adapter_id": prepared.get("alignment_adapter_id"),
            "alignment_adapter_version": prepared.get("alignment_adapter_version"),
            "alignment_adapter_sha256": prepared.get("alignment_adapter_sha256"),
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


def predict(sequence: str, model: PortableModel | None = None) -> dict[str, Any]:
    """Predict from an explicitly supplied 30-column model alignment."""

    fitted = model or load_model()
    normalized = normalize_aligned_sequence(sequence)
    prepared = {
        "original_sequence": normalized,
        "aligned_sequence": normalized,
        "input_residue_count": sum(symbol != "-" for symbol in normalized),
        "alignment_method": "provided_30_column_alignment",
        "alignment_status": "provided",
        "alignment_reference_ids": [],
        "alignment_score": None,
        "alignment_note": (
            "The user supplied all 30 model columns, including any explicit alignment gaps."
        ),
        "alignment_adapter_id": None,
        "alignment_adapter_version": None,
        "alignment_adapter_sha256": None,
    }
    return _predict_prepared(prepared, fitted)


def predict_raw(sequence: str, model: PortableModel | None = None) -> dict[str, Any]:
    """Align one supported raw 26--30-residue sequence, then run the strict model."""

    fitted = model or load_model()
    prepared = prepare_sequence(sequence, fitted)
    if prepared["alignment_method"] == "provided_30_column_alignment":
        raise ProductError(
            "Raw-sequence mode does not accept '-' gaps; use the explicit 30-column mode"
        )
    return _predict_prepared(prepared, fitted)


def model_info(model: PortableModel | None = None) -> dict[str, Any]:
    """Return provenance without exposing assay outcomes or refitting the model."""

    fitted = model or load_model()
    alignment_policy = load_alignment_policy()
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
        "raw_alignment_adapter": {
            "adapter_id": alignment_policy["adapter_id"],
            "adapter_version": alignment_policy["adapter_version"],
            "sha256": alignment_policy["sha256"],
            "supported_raw_residue_range": [
                AUTOALIGN_MIN_RESIDUES,
                AUTOALIGN_MAX_RESIDUES,
            ],
        },
    }
