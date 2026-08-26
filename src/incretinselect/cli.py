"""Command-line interface for the frozen IncretinSelect research model."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from incretinselect.product import ProductError, model_info, predict

EXAMPLE_SEQUENCE = "HSQGTFTSDYSKYLDSRAASEFVQWLISH-"


class OutputError(ValueError):
    """Raised when a requested output file cannot be written safely."""


def _number(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 10000 or abs(value) < 0.001:
        return f"{value:.4e}"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _safe_csv_text(value: str) -> str:
    """Prevent valid leading-gap sequences from becoming spreadsheet formulas."""

    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def format_text(result: dict[str, Any]) -> str:
    """Render one prediction as a readable terminal report."""

    predictions = result["predictions"]
    applicability = result["applicability"]
    benchmark = result["benchmark_context"]
    gcgr = predictions["gcgr"]
    glp1r = predictions["glp1r"]
    selectivity = predictions["selectivity"]
    metrics = benchmark.get("metrics", {})
    nearest = ", ".join(applicability["nearest_reference_ids"])
    lines = [
        "IncretinSelect-AI — research estimate",
        "=" * 43,
        f"Aligned input : {result['input']['aligned_sequence']}",
        "",
        "Predicted cell-based cAMP EC50 (lower EC50 = greater functional potency)",
        f"  GLP-1R : log10(pM) {glp1r['log10_ec50_pm']:.4f} | "
        f"{_number(glp1r['ec50_pm'])} pM | {_number(glp1r['ec50_nm'])} nM",
        f"  GCGR   : log10(pM) {gcgr['log10_ec50_pm']:.4f} | "
        f"{_number(gcgr['ec50_pm'])} pM | {_number(gcgr['ec50_nm'])} nM",
        "",
        "Predicted receptor balance",
        f"  log10(GCGR EC50 / GLP-1R EC50) : {selectivity['log10_ec50_ratio']:.4f}",
        f"  EC50 ratio                       : {_number(selectivity['ec50_fold_ratio'])}-fold",
        f"  Interpretation                   : {selectivity['interpretation']}",
        "",
        "Applicability check",
        f"  Tier             : {applicability['tier']}",
        f"  Nearest identity : {applicability['nearest_aligned_identity'] * 100:.1f}%",
        f"  Nearest reference: {nearest}",
        f"  Meaning          : {applicability['summary']}",
        "",
        "Benchmark context (not an individual confidence interval)",
    ]
    for endpoint, label in (("gcgr", "GCGR"), ("glp1r", "GLP-1R"), ("selectivity", "Balance")):
        row = metrics.get(endpoint, {})
        if row:
            lines.append(
                f"  {label:<7}: development MAE {row['development_oof_mae_log10']:.2f} log10 "
                f"(~{row['development_oof_geometric_fold_error']:.1f}-fold)"
            )
    lines.extend(["", "Important limitations"])
    lines.extend(f"  - {warning}" for warning in result["warnings"])
    lines.extend(
        [
            "",
            f"Model: {result['model']['artifact_id']} v{result['model']['artifact_version']}",
            f"Artifact SHA-256: {result['model']['artifact_sha256']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _flat_row(result: dict[str, Any]) -> dict[str, Any]:
    predictions = result["predictions"]
    applicability = result["applicability"]
    return {
        "aligned_sequence": _safe_csv_text(result["input"]["aligned_sequence"]),
        "glp1r_log10_ec50_pm": predictions["glp1r"]["log10_ec50_pm"],
        "glp1r_ec50_pm": predictions["glp1r"]["ec50_pm"],
        "glp1r_ec50_nm": predictions["glp1r"]["ec50_nm"],
        "gcgr_log10_ec50_pm": predictions["gcgr"]["log10_ec50_pm"],
        "gcgr_ec50_pm": predictions["gcgr"]["ec50_pm"],
        "gcgr_ec50_nm": predictions["gcgr"]["ec50_nm"],
        "selectivity_log10_gcgr_over_glp1r": predictions["selectivity"][
            "log10_ec50_ratio"
        ],
        "selectivity_ec50_fold_ratio": predictions["selectivity"]["ec50_fold_ratio"],
        "selectivity_interpretation": predictions["selectivity"]["interpretation"],
        "applicability_tier": applicability["tier"],
        "nearest_aligned_identity": applicability["nearest_aligned_identity"],
        "nearest_reference_ids": ";".join(applicability["nearest_reference_ids"]),
        "artifact_id": result["model"]["artifact_id"],
        "artifact_version": result["model"]["artifact_version"],
        "artifact_sha256": result["model"]["artifact_sha256"],
        "endpoint_warning": (
            "Cell-based cAMP EC50 functional potency; not affinity, efficacy, or safety."
        ),
    }


def format_csv(result: dict[str, Any]) -> str:
    row = _flat_row(result)
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)
    return handle.getvalue()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incretin-predict",
        description=(
            "Estimate GLP-1R and GCGR cell-based cAMP EC50 from one already-aligned "
            "30-column peptide sequence. Research use only; this is not affinity prediction."
        ),
        epilog=(
            "Example: incretin-predict " + EXAMPLE_SEQUENCE + "\n"
            "A 29-residue core needs an explicit alignment gap, usually supplied by the "
            "source alignment. This tool never guesses or trims it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "sequence",
        nargs="?",
        help="Exactly 30 aligned symbols: 20 standard amino acids plus optional '-' gaps.",
    )
    parser.add_argument(
        "--sequence",
        dest="sequence_option",
        help=(
            "Explicit sequence input. Use this form when the aligned sequence begins "
            "with '-' so it cannot be mistaken for a command-line option."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "csv"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument("--output", help="Write the result to a file instead of stdout.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace an existing --output file.",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="Run the bundled 30-column example without supplying a sequence.",
    )
    parser.add_argument(
        "--model-info",
        action="store_true",
        help="Print frozen model version, checksum, benchmark context, and provenance.",
    )
    return parser


def _write_output(path: Path, rendered: str, *, overwrite: bool) -> None:
    """Write one result atomically without silently replacing an existing file."""

    if path.is_symlink():
        raise OutputError("output path must not be a symbolic link")
    resolved = path.resolve()
    if resolved.exists() and not overwrite:
        raise OutputError(f"Refusing to overwrite existing file: {resolved}")
    if not resolved.parent.is_dir():
        raise OutputError(f"Output directory does not exist: {resolved.parent}")
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved.name}.", suffix=".tmp", dir=resolved.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    except OSError as exc:
        raise OutputError(f"Could not write output file {resolved}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.model_info:
            if args.sequence or args.sequence_option or args.example:
                parser.error("--model-info cannot be combined with a prediction input")
            rendered = json.dumps(model_info(), indent=2, sort_keys=True) + "\n"
        else:
            supplied = [
                args.sequence is not None,
                args.sequence_option is not None,
                args.example,
            ]
            if sum(supplied) > 1:
                parser.error("Supply one positional sequence, --sequence, or --example")
            sequence = (
                EXAMPLE_SEQUENCE
                if args.example
                else args.sequence_option
                if args.sequence_option is not None
                else args.sequence
            )
            if not sequence:
                parser.error("a 30-column sequence is required (or use --example)")
            result = predict(sequence)
            if args.format == "json":
                rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
            elif args.format == "csv":
                rendered = format_csv(result)
            else:
                rendered = format_text(result)
    except ProductError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.output:
            _write_output(Path(args.output), rendered, overwrite=args.overwrite)
        else:
            print(rendered, end="")
    except OutputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
