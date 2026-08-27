"""Command-line interface for the frozen IncretinSelect research model."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from incretinselect import __version__
from incretinselect.product import ProductError, model_info, predict

EXAMPLE_SEQUENCE = "HSQGTFTSDYSKYLDSRAASEFVQWLISH-"
MAX_SEQUENCE_FILE_BYTES = 65_536


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
    comparison = result["nearest_reference_comparison"]
    delta = comparison["query_minus_reference"]
    metrics = benchmark.get("metrics", {})
    nearest = ", ".join(applicability["nearest_reference_ids"])
    lines = [
        "IncretinSelect-AI — research estimate",
        "=" * 43,
        f"Aligned input : {result['input']['aligned_sequence']}",
        "",
        "Predicted cell-based cAMP EC50 (lower EC50 = greater functional potency)",
        f"  GLP-1R : log10(EC50 / 1 pM) {glp1r['log10_ec50_pm']:.4f} | "
        f"{_number(glp1r['ec50_pm'])} pM | {_number(glp1r['ec50_nm'])} nM",
        f"  GCGR   : log10(EC50 / 1 pM) {gcgr['log10_ec50_pm']:.4f} | "
        f"{_number(gcgr['ec50_pm'])} pM | {_number(gcgr['ec50_nm'])} nM",
        "",
        "Predicted GCGR/GLP-1R EC50 ratio",
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
        "Nearest-reference model comparison",
        f"  Reference        : {comparison['reference_id']}",
        f"  Changed positions: {comparison['changed_position_count']}",
        f"  GLP-1R delta     : {delta['glp1r_delta_log10_ec50_pm']:+.4f} log10 units "
        f"({_number(delta['glp1r_ec50_fold_ratio'])}x query/reference EC50)",
        f"  GCGR delta       : {delta['gcgr_delta_log10_ec50_pm']:+.4f} log10 units "
        f"({_number(delta['gcgr_ec50_fold_ratio'])}x query/reference EC50)",
        f"  Boundary         : {comparison['scientific_boundary']}",
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


def format_markdown(result: dict[str, Any]) -> str:
    """Render one prediction as a concise, lab-note-ready Markdown report."""

    predictions = result["predictions"]
    applicability = result["applicability"]
    comparison = result["nearest_reference_comparison"]
    delta = comparison["query_minus_reference"]
    ranking = result["exploratory_ranking"]
    lines = [
        "# IncretinSelect-AI result",
        "",
        f"**Aligned sequence:** `{result['input']['aligned_sequence']}`",
        "",
        "## Predicted cell-based cAMP EC50",
        "",
        "| Endpoint | log10(EC50 / 1 pM) | pM | nM |",
        "|:--|--:|--:|--:|",
        (
            f"| GLP-1R | {predictions['glp1r']['log10_ec50_pm']:.4f} | "
            f"{_number(predictions['glp1r']['ec50_pm'])} | "
            f"{_number(predictions['glp1r']['ec50_nm'])} |"
        ),
        (
            f"| GCGR | {predictions['gcgr']['log10_ec50_pm']:.4f} | "
            f"{_number(predictions['gcgr']['ec50_pm'])} | "
            f"{_number(predictions['gcgr']['ec50_nm'])} |"
        ),
        "",
        (
            "Predicted GCGR/GLP-1R EC50 ratio: "
            f"**{_number(predictions['selectivity']['ec50_fold_ratio'])}-fold** "
            f"({predictions['selectivity']['interpretation']})."
        ),
        "",
        "## Applicability",
        "",
        f"- Tier: `{applicability['tier']}`",
        f"- Nearest aligned identity: {applicability['nearest_aligned_identity'] * 100:.1f}%",
        f"- Nearest reference: `{comparison['reference_id']}`",
        f"- Changed alignment positions: {comparison['changed_position_count']}",
        f"- Assessment: {applicability['summary']}",
        (
            "- Exploratory ranking: enabled"
            if ranking["enabled"]
            else "- Exploratory ranking: disabled"
        ),
        "",
        "## Nearest-reference model comparison",
        "",
        "| Endpoint | Query − reference, log10 units | Query/reference EC50 |",
        "|:--|--:|--:|",
        (
            f"| GLP-1R | {delta['glp1r_delta_log10_ec50_pm']:+.4f} | "
            f"{_number(delta['glp1r_ec50_fold_ratio'])}x |"
        ),
        (
            f"| GCGR | {delta['gcgr_delta_log10_ec50_pm']:+.4f} | "
            f"{_number(delta['gcgr_ec50_fold_ratio'])}x |"
        ),
        "",
    ]
    changes = comparison["position_contributions"]
    if changes:
        lines.extend(
            [
                "| Position | Reference | Query | GLP-1R contribution | GCGR contribution |",
                "|--:|:--:|:--:|--:|--:|",
            ]
        )
        lines.extend(
            (
                f"| {row['alignment_position']} | `{row['reference_symbol']}` | "
                f"`{row['query_symbol']}` | {row['glp1r_delta_log10_ec50_pm']:+.4f} | "
                f"{row['gcgr_delta_log10_ec50_pm']:+.4f} |"
            )
            for row in changes
        )
        lines.append("")
    else:
        lines.extend(["The query is identical to the selected nearest reference.", ""])
    if ranking["exclusion_reasons"]:
        lines.extend(
            [
                "> **Do not use this output to rank experiments.** "
                + " ".join(ranking["exclusion_reasons"]),
                "",
            ]
        )
    if comparison["nearest_reference_tie_count"] > 1:
        lines.extend(
            [
                f"> {comparison['nearest_reference_tie_count']} references tied for nearest "
                f"identity; `{comparison['reference_id']}` was selected deterministically "
                "for the comparison.",
                "",
            ]
        )
    lines.extend(
        [
            f"> {comparison['scientific_boundary']}",
            "> Reference values in this report are model predictions, not observed assay values.",
            "",
            "## Interpretation boundary",
            "",
            "These are sequence-model point estimates of cell-based cAMP EC50. They are "
            "not binding affinity, maximal assay response, safety, or evidence of activity "
            "in vivo.",
            "The locked retrospective P1–P15 external evaluation was mixed and showed no "
            "overall model superiority.",
            "",
            f"Model: `{result['model']['artifact_id']}` v{result['model']['artifact_version']}",
            "",
            f"Artifact SHA-256: `{result['model']['artifact_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _flat_row(result: dict[str, Any]) -> dict[str, Any]:
    predictions = result["predictions"]
    applicability = result["applicability"]
    comparison = result["nearest_reference_comparison"]
    delta = comparison["query_minus_reference"]
    ranking = result["exploratory_ranking"]
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
        "standard_residue_count": result["input"]["standard_residue_count"],
        "exploratory_ranking_enabled": (
            "true" if ranking["enabled"] else "false"
        ),
        "exploratory_ranking_exclusion_reason": " ".join(
            ranking["exclusion_reasons"]
        ),
        "comparison_reference_id": comparison["reference_id"],
        "changed_position_count": comparison["changed_position_count"],
        "glp1r_delta_log10_ec50_pm_vs_reference": delta["glp1r_delta_log10_ec50_pm"],
        "gcgr_delta_log10_ec50_pm_vs_reference": delta["gcgr_delta_log10_ec50_pm"],
        "glp1r_ec50_fold_ratio_vs_reference": delta["glp1r_ec50_fold_ratio"],
        "gcgr_ec50_fold_ratio_vs_reference": delta["gcgr_ec50_fold_ratio"],
        "software_version": result["model"]["software_version"],
        "artifact_id": result["model"]["artifact_id"],
        "artifact_version": result["model"]["artifact_version"],
        "artifact_sha256": result["model"]["artifact_sha256"],
        "endpoint_warning": (
            "Cell-based cAMP EC50 functional-potency estimate; not binding affinity, "
            "maximal assay response, safety, or drug validation."
        ),
        "validation_warning": str(
            result["benchmark_context"].get("external_evaluation", "")
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
            "Estimate GLP-1R and GCGR cell-based cAMP EC50 from one aligned 30-position "
            "peptide sequence. The model does not predict binding affinity."
        ),
        epilog=(
            "Example: incretin-predict --sequence-file candidate.fasta\n"
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
        "--sequence-file",
        metavar="PATH",
        help=(
            "Read one aligned sequence from UTF-8 text or single-record FASTA. "
            "Use '-' to read from standard input and avoid exposing a sequence in "
            "shell history or process listings."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "csv", "markdown"),
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
        help="Print model version, checksum, benchmark context, and provenance.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _read_sequence_file(value: str) -> str:
    """Read bounded UTF-8 text or one FASTA record without guessing alignment."""

    try:
        if value == "-":
            raw = sys.stdin.buffer.read(MAX_SEQUENCE_FILE_BYTES + 1)
            label = "standard input"
        else:
            path = Path(value)
            if path.is_symlink():
                raise ProductError("Sequence input path must not be a symbolic link")
            label = str(path)
            flags = os.O_RDONLY
            flags |= getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NONBLOCK", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            file_descriptor: int | None = os.open(path, flags)
            try:
                metadata = os.fstat(file_descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ProductError("Sequence input path must be a regular file")
                if metadata.st_size > MAX_SEQUENCE_FILE_BYTES:
                    raise ProductError(
                        "Sequence input exceeds the "
                        f"{MAX_SEQUENCE_FILE_BYTES}-byte safety limit"
                    )
                with os.fdopen(file_descriptor, "rb") as handle:
                    file_descriptor = None
                    raw = handle.read(MAX_SEQUENCE_FILE_BYTES + 1)
            finally:
                if file_descriptor is not None:
                    os.close(file_descriptor)
    except OSError as exc:
        raise ProductError(f"Could not read sequence input {value}: {exc}") from exc
    if len(raw) > MAX_SEQUENCE_FILE_BYTES:
        raise ProductError(
            f"Sequence input exceeds the {MAX_SEQUENCE_FILE_BYTES}-byte safety limit"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProductError(f"Sequence input {label} must be valid UTF-8") from exc
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise ProductError(f"Sequence input {label} is empty")
    if lines[0].startswith(">"):
        if not lines[0][1:].strip():
            raise ProductError("FASTA header is empty")
        if any(line.startswith(">") for line in lines[1:]):
            raise ProductError("Sequence input must contain exactly one FASTA record")
        return "".join(lines[1:])
    return "".join(lines)


def _same_file(first: Path, second: Path) -> bool:
    """Compare existing aliases as well as normalized not-yet-created paths."""

    try:
        if first.exists() and second.exists() and os.path.samefile(first, second):
            return True
    except OSError:
        pass
    return first.resolve(strict=False) == second.resolve(strict=False)


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
            if args.sequence or args.sequence_option or args.sequence_file or args.example:
                parser.error("--model-info cannot be combined with a prediction input")
            rendered = json.dumps(model_info(), indent=2, sort_keys=True) + "\n"
        else:
            supplied = [
                args.sequence is not None,
                args.sequence_option is not None,
                args.sequence_file is not None,
                args.example,
            ]
            if sum(supplied) > 1:
                parser.error(
                    "Supply one positional sequence, --sequence, --sequence-file, or --example"
                )
            if (
                args.sequence_file not in (None, "-")
                and args.output
                and _same_file(Path(args.sequence_file), Path(args.output))
            ):
                raise ProductError(
                    "Sequence input and --output must refer to different files"
                )
            sequence = (
                EXAMPLE_SEQUENCE
                if args.example
                else _read_sequence_file(args.sequence_file)
                if args.sequence_file is not None
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
            elif args.format == "markdown":
                rendered = format_markdown(result)
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
