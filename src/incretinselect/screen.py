"""Guarded batch screening for the frozen IncretinSelect research model.

The interface keeps every input row visible but ranks only local analogs that meet
the residue-count gate. A user must also state the receptor objective explicitly;
there is no catch-all "best peptide" score.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from incretinselect import __version__
from incretinselect.product import PortableModel, ProductError, load_model, predict

INPUT_COLUMNS = ("candidate_id", "aligned_sequence")
MAX_CANDIDATES = 10_000
MAX_INPUT_BYTES = 10_000_000
MIN_RANKING_RESIDUES = 26
RANKING_TIE_TOLERANCE = 1e-12
CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

ENDPOINT_WARNING = (
    "Cell-based cAMP EC50 functional-potency estimate; not binding affinity, "
    "maximal assay response, safety, or drug validation."
)
RANKING_WARNING = (
    "Exploratory model ordering for experiment planning; not an experimental "
    "recommendation."
)

OBJECTIVES: dict[str, dict[str, str]] = {
    "glp1r": {
        "definition": "minimize predicted GLP-1R log10(EC50 / 1 pM)",
        "score": "glp1r_log10_ec50_pm",
    },
    "gcgr": {
        "definition": "minimize predicted GCGR log10(EC50 / 1 pM)",
        "score": "gcgr_log10_ec50_pm",
    },
    "dual": {
        "definition": (
            "minimize the larger of predicted GLP-1R and GCGR "
            "log10(EC50 / 1 pM) values"
        ),
        "score": "max_receptor_log10_ec50_pm",
    },
}

OUTPUT_COLUMNS = (
    "input_row",
    "candidate_id",
    "aligned_sequence",
    "status",
    "error_code",
    "error_message",
    "ranking_objective",
    "ranking_objective_definition",
    "ranking_eligible",
    "ranking_exclusion_reason",
    "rank",
    "ranking_score",
    "score_delta_from_first_log10",
    "score_fold_ratio_from_first",
    "development_mae_context_log10",
    "within_one_development_mae_of_first",
    "ranking_context",
    "glp1r_log10_ec50_pm",
    "glp1r_ec50_pm",
    "gcgr_log10_ec50_pm",
    "gcgr_ec50_pm",
    "selectivity_log10_gcgr_over_glp1r",
    "applicability_tier",
    "applicability_evidence_state",
    "exact_reference_match",
    "nearest_aligned_identity",
    "nearest_reference_ids",
    "standard_residue_count",
    "duplicate_sequence_count",
    "software_version",
    "artifact_id",
    "artifact_version",
    "artifact_sha256",
    "endpoint_warning",
    "validation_warning",
    "ranking_warning",
)


class ScreeningError(ValueError):
    """Raised when a batch cannot be screened safely."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_file_bounded(path: Path, maximum_bytes: int) -> bytes:
    """Read at most one byte beyond the limit from an opened regular file."""

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    file_descriptor: int | None = os.open(path, flags)
    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ScreeningError(f"Input CSV is not a regular file: {path}")
        if metadata.st_size > maximum_bytes:
            raise ScreeningError(
                f"Input CSV is {metadata.st_size} bytes; "
                f"the safety limit is {maximum_bytes}"
            )
        with os.fdopen(file_descriptor, "rb") as handle:
            file_descriptor = None
            raw = handle.read(maximum_bytes + 1)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
    if len(raw) > maximum_bytes:
        raise ScreeningError(
            f"Input CSV exceeds the {maximum_bytes}-byte safety limit"
        )
    return raw


def _number(value: float) -> str:
    """Render stable, compact machine-readable floating-point output."""

    return format(value, ".15g")


def _blank_output_row(
    input_row: int,
    candidate_id: str,
    sequence: str,
    objective: str,
    model: PortableModel,
) -> dict[str, str]:
    row = {column: "" for column in OUTPUT_COLUMNS}
    row.update(
        {
            "input_row": str(input_row),
            "candidate_id": candidate_id,
            "aligned_sequence": sequence,
            "ranking_objective": objective,
            "ranking_objective_definition": OBJECTIVES[objective]["definition"],
            "ranking_eligible": "false",
            "software_version": __version__,
            "artifact_id": model.artifact_id,
            "artifact_version": model.artifact_version,
            "artifact_sha256": model.sha256,
            "endpoint_warning": ENDPOINT_WARNING,
            "validation_warning": str(model.benchmark.get("external_evaluation", "")),
            "ranking_warning": RANKING_WARNING,
        }
    )
    return row


def _safe_csv_text(value: str) -> str:
    """Keep rejected user text visible without creating spreadsheet formulas."""

    escaped = "".join(
        character
        if ord(character) >= 32 and ord(character) != 127
        else f"\\u{ord(character):04x}"
        for character in value
    )
    if escaped.startswith(("=", "+", "-", "@")):
        return "'" + escaped
    return escaped


def _validate_candidate_id(candidate_id: str) -> str | None:
    if not candidate_id:
        return "Candidate ID is empty"
    if not CANDIDATE_ID_PATTERN.fullmatch(candidate_id):
        return (
            "Candidate ID must start with a letter or number and contain at most "
            "128 letters, numbers, '.', '_', ':', or '-'."
        )
    return None


def _read_candidates(raw: bytes) -> list[dict[str, str]]:
    if len(raw) > MAX_INPUT_BYTES:
        raise ScreeningError(
            f"Input CSV is {len(raw)} bytes; the safety limit is {MAX_INPUT_BYTES}"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ScreeningError("Input CSV must be UTF-8 encoded") from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if reader.fieldnames is None:
            raise ScreeningError("Input CSV has no header row")
        fieldnames = tuple(name.strip() for name in reader.fieldnames)
        if len(fieldnames) != len(set(fieldnames)):
            raise ScreeningError("Input CSV has duplicate column names")
        if set(fieldnames) != set(INPUT_COLUMNS) or len(fieldnames) != len(INPUT_COLUMNS):
            raise ScreeningError(
                "Input CSV must contain exactly these columns: "
                + ", ".join(INPUT_COLUMNS)
            )
        reader.fieldnames = list(fieldnames)
        records = []
        for row_number, row in enumerate(reader, start=1):
            if row_number > MAX_CANDIDATES:
                raise ScreeningError(
                    f"Input CSV has more than {MAX_CANDIDATES} rows; "
                    f"the safety limit is {MAX_CANDIDATES}"
                )
            if None in row:
                raise ScreeningError(
                    f"Candidate row {row_number} has more than {len(INPUT_COLUMNS)} fields"
                )
            records.append(
                {
                    "candidate_id": str(row.get("candidate_id") or "").strip(),
                    "aligned_sequence": str(row.get("aligned_sequence") or ""),
                }
            )
    except csv.Error as exc:
        raise ScreeningError(f"Input CSV is malformed: {exc}") from exc

    if not records:
        raise ScreeningError("Input CSV contains no candidate rows")
    if len(records) > MAX_CANDIDATES:
        raise ScreeningError(
            f"Input CSV has {len(records)} rows; the safety limit is {MAX_CANDIDATES}"
        )

    nonblank_ids = [row["candidate_id"] for row in records if row["candidate_id"]]
    duplicates = sorted(
        candidate_id for candidate_id, count in Counter(nonblank_ids).items() if count > 1
    )
    if duplicates:
        preview = ", ".join(_safe_csv_text(value) for value in duplicates[:5])
        suffix = "" if len(duplicates) <= 5 else f" (+{len(duplicates) - 5} more)"
        raise ScreeningError(f"Candidate IDs must be unique; duplicates: {preview}{suffix}")
    return records


def _ranking_score(result: dict[str, Any], objective: str) -> float:
    glp1r = float(result["predictions"]["glp1r"]["log10_ec50_pm"])
    gcgr = float(result["predictions"]["gcgr"]["log10_ec50_pm"])
    if objective == "glp1r":
        return glp1r
    if objective == "gcgr":
        return gcgr
    return max(glp1r, gcgr)


def _development_mae_context(
    model: PortableModel, objective: str
) -> tuple[float, str, str]:
    """Return population-level error context for an ordering objective.

    The dual score has not been benchmarked as its own endpoint. Its context is
    therefore the larger of the two receptor-specific development OOF MAEs, used
    only as a conservative descriptive reference.
    """

    metrics = model.benchmark.get("metrics", {})
    if objective in {"glp1r", "gcgr"}:
        value = float(metrics[objective]["development_oof_mae_log10"])
        source = f"{objective}_development_oof_mae_log10"
        note = (
            "Population-level development out-of-fold MAE for this receptor; "
            "not an individual confidence interval or significance threshold."
        )
        return value, source, note

    value = max(
        float(metrics["glp1r"]["development_oof_mae_log10"]),
        float(metrics["gcgr"]["development_oof_mae_log10"]),
    )
    return (
        value,
        "larger_receptor_development_oof_mae_log10",
        "Conservative descriptive reference for the dual max-receptor score; the "
        "dual objective was not benchmarked as a separate endpoint. This is not an "
        "individual confidence interval or significance threshold.",
    )


def screen_records(
    records: list[dict[str, str]],
    objective: str,
    *,
    model: PortableModel | None = None,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Predict and conservatively rank parsed candidate rows."""

    if objective not in OBJECTIVES:
        raise ScreeningError(f"Unknown ranking objective: {objective}")
    fitted = model or load_model()
    rows: list[dict[str, str]] = []
    normalized_counts: dict[str, int] = {}
    normalized_by_input_row: dict[int, str] = {}
    raw_ranking_scores: dict[int, float] = {}

    for input_row, record in enumerate(records, start=1):
        candidate_id = record["candidate_id"]
        raw_sequence = record["aligned_sequence"]
        row = _blank_output_row(
            input_row,
            _safe_csv_text(candidate_id),
            _safe_csv_text(raw_sequence.strip()),
            objective,
            fitted,
        )
        id_error = _validate_candidate_id(candidate_id)
        if id_error:
            row.update(
                {
                    "status": "input_error",
                    "error_code": "invalid_candidate_id",
                    "error_message": id_error,
                }
            )
            rows.append(row)
            continue

        try:
            result = predict(raw_sequence, fitted)
        except ProductError as exc:
            row.update(
                {
                    "status": "input_error",
                    "error_code": "invalid_aligned_sequence",
                    "error_message": str(exc),
                }
            )
            rows.append(row)
            continue

        normalized = str(result["input"]["aligned_sequence"])
        normalized_counts[normalized] = normalized_counts.get(normalized, 0) + 1
        normalized_by_input_row[input_row] = normalized
        predictions = result["predictions"]
        applicability = result["applicability"]
        residue_count = int(result["input"]["standard_residue_count"])
        exclusion_reasons: list[str] = []
        if applicability["tier"] != "close_analogue":
            exclusion_reasons.append(f"applicability_tier={applicability['tier']}")
        if residue_count < MIN_RANKING_RESIDUES:
            exclusion_reasons.append(
                f"standard_residue_count={residue_count} is below {MIN_RANKING_RESIDUES}"
            )
        eligible = not exclusion_reasons
        score = _ranking_score(result, objective)
        if eligible:
            raw_ranking_scores[input_row] = score
        row.update(
            {
                "aligned_sequence": _safe_csv_text(normalized),
                "status": "pending_rank" if eligible else "not_ranked_out_of_scope",
                "ranking_eligible": "true" if eligible else "false",
                "ranking_exclusion_reason": "; ".join(exclusion_reasons),
                "ranking_score": _number(score) if eligible else "",
                "glp1r_log10_ec50_pm": _number(
                    float(predictions["glp1r"]["log10_ec50_pm"])
                ),
                "glp1r_ec50_pm": _number(float(predictions["glp1r"]["ec50_pm"])),
                "gcgr_log10_ec50_pm": _number(
                    float(predictions["gcgr"]["log10_ec50_pm"])
                ),
                "gcgr_ec50_pm": _number(float(predictions["gcgr"]["ec50_pm"])),
                "selectivity_log10_gcgr_over_glp1r": _number(
                    float(predictions["selectivity"]["log10_ec50_ratio"])
                ),
                "applicability_tier": str(applicability["tier"]),
                "applicability_evidence_state": str(
                    applicability["evidence_state"]
                ),
                "exact_reference_match": (
                    "true" if applicability["exact_reference_match"] else "false"
                ),
                "nearest_aligned_identity": _number(
                    float(applicability["nearest_aligned_identity"])
                ),
                "nearest_reference_ids": ";".join(applicability["nearest_reference_ids"]),
                "standard_residue_count": str(residue_count),
            }
        )
        rows.append(row)

    for row in rows:
        if row["status"] != "input_error":
            normalized = normalized_by_input_row[int(row["input_row"])]
            row["duplicate_sequence_count"] = str(normalized_counts[normalized])

    eligible_rows = [row for row in rows if row["status"] == "pending_rank"]
    eligible_rows.sort(
        key=lambda row: (
            raw_ranking_scores[int(row["input_row"])],
            int(row["input_row"]),
        )
    )
    mae_context, _, _ = _development_mae_context(fitted, objective)
    best_score = (
        raw_ranking_scores[int(eligible_rows[0]["input_row"])]
        if eligible_rows
        else None
    )
    rank = 0
    previous_score: float | None = None
    for row in eligible_rows:
        score = raw_ranking_scores[int(row["input_row"])]
        if previous_score is None or not math.isclose(
            score,
            previous_score,
            rel_tol=0.0,
            abs_tol=RANKING_TIE_TOLERANCE,
        ):
            rank += 1
            previous_score = score
        row["rank"] = str(rank)
        row["status"] = "ranked"
        delta = score - best_score if best_score is not None else 0.0
        within_context = delta <= mae_context + RANKING_TIE_TOLERANCE
        row["score_delta_from_first_log10"] = _number(delta)
        row["score_fold_ratio_from_first"] = _number(10**delta)
        row["development_mae_context_log10"] = _number(mae_context)
        row["within_one_development_mae_of_first"] = (
            "true" if within_context else "false"
        )
        row["ranking_context"] = (
            "within_one_development_mae_of_first"
            if within_context
            else "more_than_one_development_mae_from_first"
        )

    remainder = [row for row in rows if row["status"] != "ranked"]
    remainder.sort(key=lambda row: int(row["input_row"]))
    ordered = eligible_rows + remainder
    counts = {
        "total_rows": len(rows),
        "valid_prediction_rows": sum(row["status"] != "input_error" for row in rows),
        "input_error_rows": sum(row["status"] == "input_error" for row in rows),
        "ranking_eligible_rows": len(eligible_rows),
        "ranked_rows": len(eligible_rows),
        "out_of_scope_rows": sum(
            row["status"] == "not_ranked_out_of_scope" for row in rows
        ),
        "within_one_development_mae_of_first_rows": sum(
            row["within_one_development_mae_of_first"] == "true" for row in rows
        ),
    }
    return ordered, counts


def _render_csv(rows: list[dict[str, str]]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def build_screening(
    raw_input: bytes,
    objective: str,
    *,
    input_filename: str = "candidates.csv",
    output_filename: str = "screened_candidates.csv",
    model: PortableModel | None = None,
) -> tuple[str, dict[str, Any], int]:
    """Build deterministic screening CSV and receipt content from input bytes."""

    fitted = model or load_model()
    records = _read_candidates(raw_input)
    rows, counts = screen_records(records, objective, model=fitted)
    mae_context, mae_source, mae_note = _development_mae_context(fitted, objective)
    rendered = _render_csv(rows)
    rendered_bytes = rendered.encode("utf-8")
    if counts["ranking_eligible_rows"] == 0:
        status = "no_rankable_rows"
        exit_code = 3
    elif counts["input_error_rows"]:
        status = "completed_with_row_errors"
        exit_code = 1
    else:
        status = "completed"
        exit_code = 0
    receipt = {
        "schema_version": 1,
        "tool": "incretin-screen",
        "status": status,
        "exit_code": exit_code,
        "input": {
            "filename": input_filename,
            "sha256": _sha256(raw_input),
            "required_columns": list(INPUT_COLUMNS),
            "maximum_rows": MAX_CANDIDATES,
            "maximum_bytes": MAX_INPUT_BYTES,
        },
        "output": {
            "filename": output_filename,
            "sha256": _sha256(rendered_bytes),
            "columns": list(OUTPUT_COLUMNS),
        },
        "objective": {
            "name": objective,
            "definition": OBJECTIVES[objective]["definition"],
            "direction": "lower score ranks first",
        },
        "ranking_gate": {
            "required_applicability_tier": "close_analogue",
            "minimum_standard_residue_count": MIN_RANKING_RESIDUES,
            "scientific_boundary": (
                "This software gate enables exploratory ordering; it is not a "
                "calibrated accuracy or validation threshold."
            ),
            "tie_policy": (
                "dense rank when scores are equal within absolute tolerance "
                f"{RANKING_TIE_TOLERANCE:g}; input order breaks display ties"
            ),
        },
        "ranking_context": {
            "development_mae_log10": mae_context,
            "source": mae_source,
            "interpretation": mae_note,
            "row_field": "score_delta_from_first_log10",
        },
        "counts": counts,
        "model": {
            "software_version": __version__,
            "artifact_id": fitted.artifact_id,
            "artifact_version": fitted.artifact_version,
            "artifact_sha256": fitted.sha256,
            "benchmark_context": fitted.benchmark,
        },
        "scientific_boundaries": {
            "endpoint": "cell-based cAMP EC50 functional potency, not binding affinity",
            "experimental_recommendation_claim": False,
            "holdout_labels_accessed": False,
            "p1_p15_outcomes_accessed": False,
            "structure_inference_run": False,
            "missing_values_converted_to_negative_labels": False,
        },
    }
    return rendered, receipt, exit_code


def _preflight_destination(path: Path, *, overwrite: bool) -> None:
    """Reject unsafe destinations before either batch artifact is replaced."""

    if path.is_symlink():
        raise ScreeningError(f"Output path must not be a symbolic link: {path}")
    if path.exists():
        if not path.is_file():
            raise ScreeningError(f"Output path is not a regular file: {path}")
        if not overwrite:
            raise ScreeningError(f"Refusing to overwrite existing file: {path}")

    # Do not call mkdir yet: first prove that the nearest existing ancestor of
    # *both* destinations is a directory. This catches paths beneath a regular
    # file without touching the other artifact.
    ancestor = path.parent
    while not ancestor.exists():
        if ancestor.is_symlink():
            raise ScreeningError(
                f"Output parent must not be a symbolic link: {ancestor}"
            )
        if ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise ScreeningError(f"Output parent is not a directory: {ancestor}")


def _stage_text(path: Path, content: str) -> Path:
    """Write and fsync content beside its destination without replacing it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _reserve_backup(path: Path) -> Path:
    """Reserve a collision-safe backup name in the destination directory."""

    file_descriptor, backup_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".bak", dir=path.parent
    )
    os.close(file_descriptor)
    return Path(backup_name)


def _atomic_write_pair(
    output_path: Path,
    output_content: str,
    receipt_path: Path,
    receipt_content: str,
    *,
    overwrite: bool,
) -> None:
    """Replace the CSV and receipt as one rollback-protected operation.

    Both payloads are staged before either destination changes. Existing files
    are then moved aside, and any failure while committing either artifact
    restores the complete previous pair.
    """

    artifacts = (
        (output_path, output_content),
        (receipt_path, receipt_content),
    )
    for path, _ in artifacts:
        _preflight_destination(path, overwrite=overwrite)

    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    preserved_backups: set[Path] = set()
    committed: set[Path] = set()
    try:
        # A permission error, bad parent, or full disk for the receipt therefore
        # occurs while the original output is still untouched.
        for path, content in artifacts:
            staged[path] = _stage_text(path, content)

        # Recheck after staging to catch destination changes before commit.
        for path, _ in artifacts:
            _preflight_destination(path, overwrite=overwrite)

        for path, _ in artifacts:
            if path.exists():
                backup = _reserve_backup(path)
                try:
                    os.replace(path, backup)
                except BaseException:
                    backup.unlink(missing_ok=True)
                    raise
                backups[path] = backup

        for path, _ in artifacts:
            os.replace(staged[path], path)
            staged.pop(path)
            committed.add(path)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for path, _ in reversed(artifacts):
            try:
                if path in committed:
                    path.unlink(missing_ok=True)
                backup = backups.get(path)
                if backup is not None and backup.exists():
                    os.replace(backup, path)
            except OSError as rollback_exc:
                backup = backups.get(path)
                if backup is not None and backup.exists():
                    preserved_backups.add(backup)
                    rollback_errors.append(
                        f"{path}: {rollback_exc}; original preserved at {backup}"
                    )
                else:
                    rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            raise ScreeningError(
                "Batch artifact write failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup not in preserved_backups:
                backup.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incretin-screen",
        description=(
            "Compare a CSV of aligned 30-position incretin-like peptides. Only rows "
            "meeting the 0.85 identity and 26-residue software gates are ranked."
        ),
        epilog=(
            "Required CSV columns: candidate_id,aligned_sequence\n"
            "Example: incretin-screen candidates.csv --objective dual "
            "--output screened.csv --receipt screening_receipt.json\n"
            "Outputs are research estimates of cell-based cAMP EC50, not affinity or "
            "experimental recommendations."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument(
        "--objective",
        choices=tuple(OBJECTIVES),
        required=True,
        help=(
            "Required ranking objective: minimize predicted GLP-1R EC50, predicted "
            "GCGR EC50, or the larger of the two predicted EC50 values."
        ),
    )
    parser.add_argument("--output", type=Path, required=True, help="Output screening CSV.")
    parser.add_argument(
        "--receipt",
        type=Path,
        required=True,
        help="Machine-readable JSON audit receipt.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace existing output and receipt files.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.output.is_symlink() or args.receipt.is_symlink():
            raise ScreeningError(
                "output and receipt paths must not be symbolic links"
            )
        input_path = args.input_csv.resolve()
        output_path = args.output.resolve()
        receipt_path = args.receipt.resolve()
        if len({input_path, output_path, receipt_path}) != 3:
            raise ScreeningError(
                "input, output, and receipt paths must be different"
            )
        if not args.overwrite:
            existing = [path for path in (output_path, receipt_path) if path.exists()]
            if existing:
                raise ScreeningError(
                    "Refusing to overwrite existing file(s): "
                    + ", ".join(str(path) for path in existing)
                )
        raw = _read_regular_file_bounded(input_path, MAX_INPUT_BYTES)
        rendered, receipt, exit_code = build_screening(
            raw,
            args.objective,
            input_filename=input_path.name,
            output_filename=output_path.name,
        )
        _atomic_write_pair(
            output_path,
            rendered,
            receipt_path,
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            overwrite=args.overwrite,
        )
    except (OSError, RuntimeError, ScreeningError, ProductError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"screening {receipt['status']}: {receipt['counts']['ranked_rows']} ranked, "
        f"{receipt['counts']['out_of_scope_rows']} out of scope, "
        f"{receipt['counts']['input_error_rows']} input errors"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
