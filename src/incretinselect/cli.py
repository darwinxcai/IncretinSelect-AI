"""Command-line interface for the frozen IncretinSelect research model."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from incretinselect import __version__
from incretinselect.product import ProductError, model_info, predict, predict_raw

EXAMPLE_SEQUENCE = "HSQGTFTSDYSKYLDSRAASEFVQWLISH-"
EXAMPLE_RAW_SEQUENCE = EXAMPLE_SEQUENCE.rstrip("-")
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


def _comparison_status(evidence_state: str, ranking_enabled: bool) -> str:
    if evidence_state == "training_reference_match":
        return "In-sample reference · not an independent prediction"
    if ranking_enabled:
        return "Eligible for exploratory comparison"
    return "Do not use for candidate ranking"


def _validation_evidence(evidence_state: str) -> str:
    if evidence_state == "training_reference_match":
        return "In-sample evidence only"
    if evidence_state == "local_analogue_mixed_evidence":
        return "Mixed retrospective transfer"
    return "No supported transfer evidence"


def _fold_comparison(fold_ratio: float, receptor: str) -> str:
    if math.isclose(fold_ratio, 1.0, rel_tol=0.0, abs_tol=1e-12):
        return f"{receptor} EC50 is unchanged from the closest development sequence."
    if fold_ratio > 1:
        return (
            f"Query {receptor} EC50 is predicted {_number(fold_ratio)}× higher than "
            "the closest development sequence."
        )
    return (
        f"Query {receptor} EC50 is predicted {_number(1 / fold_ratio)}× lower than "
        "the closest development sequence."
    )


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
    applicability_labels = {
        "training_reference_match": "Training-set match · in-sample",
        "local_analogue_mixed_evidence": "Within local-analog scope · exploratory use",
        "outside_ranking_scope": "Outside supported comparison scope",
        "far_outside_ranking_scope": "Distant extrapolation · do not rank",
    }
    applicability_label = applicability_labels.get(
        applicability["evidence_state"], "Applicability unavailable"
    )
    ranking = result["exploratory_ranking"]
    comparison_status = _comparison_status(
        applicability["evidence_state"], ranking["enabled"]
    )
    validation_evidence = _validation_evidence(applicability["evidence_state"])
    ratio = float(selectivity["ec50_fold_ratio"])
    if ratio >= 3:
        ratio_sentence = (
            f"GCGR EC50 is predicted to be {_number(ratio)}× higher than GLP-1R EC50."
        )
    elif ratio <= 1 / 3:
        ratio_sentence = (
            f"GLP-1R EC50 is predicted to be {_number(1 / ratio)}× higher than GCGR EC50."
        )
    else:
        ratio_sentence = (
            "The two predicted EC50 values are within "
            f"{_number(max(ratio, 1 / ratio))}×."
        )
    lines = [
        "IncretinSelect-AI — research estimate",
        "=" * 43,
        "Result overview",
        f"  Model applicability : {applicability_label}",
        f"  Comparison status   : {comparison_status}",
        f"  Receptor profile    : {selectivity['interpretation']}",
        f"  Validation evidence : {validation_evidence}",
        "",
        f"Input sequence : {result['input']['original_sequence']}",
        f"Model alignment: {result['input']['aligned_sequence']}",
        f"Input mapping  : {result['input']['alignment_note']}",
        "",
        "Predicted functional potency — cell-based cAMP EC50",
        f"  GLP-1R : log10(EC50 / 1 pM) {glp1r['log10_ec50_pm']:.4f} | "
        f"{_number(glp1r['ec50_pm'])} pM | {_number(glp1r['ec50_nm'])} nM",
        f"  GCGR   : log10(EC50 / 1 pM) {gcgr['log10_ec50_pm']:.4f} | "
        f"{_number(gcgr['ec50_pm'])} pM | {_number(gcgr['ec50_nm'])} nM",
        "",
        "Predicted receptor profile",
        f"  {selectivity['interpretation']}: {ratio_sentence}",
        "  Functional-potency balance only; not binding selectivity or proof of dual agonism.",
        "",
        "Model applicability",
        f"  Assessment       : {applicability_label}",
        f"  Nearest identity : {applicability['nearest_aligned_identity'] * 100:.1f}%",
        f"  Nearest reference: {nearest}",
        f"  Meaning          : {applicability['summary']}",
        "",
        "Comparison with the closest development sequence",
        f"  Reference        : {comparison['reference_id']}",
        f"  Changed positions: {comparison['changed_position_count']}",
        f"  GLP-1R           : {_fold_comparison(delta['glp1r_ec50_fold_ratio'], 'GLP-1R')}",
        f"                     Δlog10 EC50 {delta['glp1r_delta_log10_ec50_pm']:+.4f}",
        f"  GCGR             : {_fold_comparison(delta['gcgr_ec50_fold_ratio'], 'GCGR')}",
        f"                     Δlog10 EC50 {delta['gcgr_delta_log10_ec50_pm']:+.4f}",
        f"  Boundary         : {comparison['scientific_boundary']}",
        "",
        "Benchmark performance (not an individual confidence interval)",
    ]
    for endpoint, label in (("glp1r", "GLP-1R"), ("gcgr", "GCGR"), ("selectivity", "Balance")):
        row = metrics.get(endpoint, {})
        if row:
            lines.append(
                f"  {label:<7}: development MAE {row['development_oof_mae_log10']:.2f} log10 "
                f"(~{row['development_oof_geometric_fold_error']:.1f}-fold)"
            )
    lines.extend(["", "Interpretation limits"])
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
    metrics = result["benchmark_context"].get("metrics", {})
    applicability_labels = {
        "training_reference_match": "Training-set match · in-sample",
        "local_analogue_mixed_evidence": "Within local-analog scope · exploratory use",
        "outside_ranking_scope": "Outside supported comparison scope",
        "far_outside_ranking_scope": "Distant extrapolation · do not rank",
    }
    applicability_label = applicability_labels.get(
        applicability["evidence_state"], "Applicability unavailable"
    )
    comparison_status = _comparison_status(
        applicability["evidence_state"], ranking["enabled"]
    )
    validation_evidence = _validation_evidence(applicability["evidence_state"])
    ratio = float(predictions["selectivity"]["ec50_fold_ratio"])
    if ratio >= 3:
        ratio_sentence = (
            f"GCGR EC50 is predicted to be {_number(ratio)}× higher than GLP-1R EC50."
        )
    elif ratio <= 1 / 3:
        ratio_sentence = (
            f"GLP-1R EC50 is predicted to be {_number(1 / ratio)}× higher than GCGR EC50."
        )
    else:
        ratio_sentence = (
            "The two predicted EC50 values are within "
            f"{_number(max(ratio, 1 / ratio))}×."
        )
    lines = [
        "# IncretinSelect-AI result",
        "",
        "## Result overview",
        "",
        "| Question | Assessment |",
        "|:--|:--|",
        f"| Model applicability | {applicability_label} |",
        f"| Comparison status | {comparison_status} |",
        f"| Predicted receptor profile | {predictions['selectivity']['interpretation']} |",
        f"| Validation evidence | {validation_evidence} |",
        "",
        f"**Input sequence:** `{result['input']['original_sequence']}`  ",
        f"**Model alignment:** `{result['input']['aligned_sequence']}`  ",
        f"**Input mapping:** {result['input']['alignment_note']}",
        "",
        "## Predicted functional potency",
        "",
        "Cell-based cAMP EC50 in the source assay; lower predicted EC50 means greater "
        "functional potency in that assay.",
        "",
        "| Receptor | pM | nM | Model scale: log10(EC50 / 1 pM) |",
        "|:--|--:|--:|--:|",
        (
            f"| GLP-1R | {_number(predictions['glp1r']['ec50_pm'])} | "
            f"{_number(predictions['glp1r']['ec50_nm'])} | "
            f"{predictions['glp1r']['log10_ec50_pm']:.4f} |"
        ),
        (
            f"| GCGR | {_number(predictions['gcgr']['ec50_pm'])} | "
            f"{_number(predictions['gcgr']['ec50_nm'])} | "
            f"{predictions['gcgr']['log10_ec50_pm']:.4f} |"
        ),
        "",
        f"**Predicted receptor profile: {predictions['selectivity']['interpretation']}.** "
        + ratio_sentence,
        "This describes functional-potency balance, not binding selectivity or evidence "
        "of dual agonism.",
        "",
        "## Model applicability",
        "",
        f"- Assessment: {applicability_label}",
        f"- Nearest aligned identity: {applicability['nearest_aligned_identity'] * 100:.1f}%",
        f"- Nearest reference: `{comparison['reference_id']}`",
        f"- Changed alignment positions: {comparison['changed_position_count']}",
        f"- Meaning: {applicability['summary']}",
        "- Candidate comparison: "
        + ("eligible for exploratory use" if ranking["enabled"] else "disabled"),
        "",
        "## Comparison with the closest development sequence",
        "",
        "| Endpoint | Plain-language comparison | Δ log10 EC50 |",
        "|:--|:--|--:|",
        (
            "| GLP-1R | "
            f"{_fold_comparison(delta['glp1r_ec50_fold_ratio'], 'GLP-1R')} | "
            f"{delta['glp1r_delta_log10_ec50_pm']:+.4f} |"
        ),
        (
            "| GCGR | "
            f"{_fold_comparison(delta['gcgr_ec50_fold_ratio'], 'GCGR')} | "
            f"{delta['gcgr_delta_log10_ec50_pm']:+.4f} |"
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
            "## Benchmark performance",
            "",
            f"- GLP-1R development MAE: {metrics['glp1r']['development_oof_mae_log10']:.2f} "
            f"log10 units (~{metrics['glp1r']['development_oof_geometric_fold_error']:.1f}-fold)",
            f"- GCGR development MAE: {metrics['gcgr']['development_oof_mae_log10']:.2f} "
            f"log10 units (~{metrics['gcgr']['development_oof_geometric_fold_error']:.1f}-fold)",
            "- Receptor-balance development MAE: "
            f"{metrics['selectivity']['development_oof_mae_log10']:.2f} log10 units "
            f"(~{metrics['selectivity']['development_oof_geometric_fold_error']:.1f}-fold)",
            "",
            "These are population-level cross-validated errors, not uncertainty intervals "
            "for this peptide. Evaluation on 15 published designs showed mixed transfer "
            "and no overall superiority over nearest-neighbor prediction.",
            "",
            "## Interpretation limits",
            "",
            "- Endpoint: cell-based cAMP EC50—not binding affinity, maximal response, "
            "safety, stability, pharmacokinetics, or in vivo efficacy.",
            "- Chemistry: Aib, lipidation, amidation, cyclization, stapling, D-amino "
            "acids, and other noncanonical modifications are not represented.",
            "- Applicability: estimates outside the local-analog gate are extrapolations "
            "and should not be used for ranking.",
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
        "original_sequence": _safe_csv_text(result["input"]["original_sequence"]),
        "aligned_sequence": _safe_csv_text(result["input"]["aligned_sequence"]),
        "alignment_method": result["input"]["alignment_method"],
        "alignment_status": result["input"]["alignment_status"],
        "alignment_reference_ids": ";".join(
            result["input"]["alignment_reference_ids"]
        ),
        "alignment_adapter_id": result["input"]["alignment_adapter_id"] or "",
        "alignment_adapter_version": (
            result["input"]["alignment_adapter_version"] or ""
        ),
        "alignment_adapter_sha256": (
            result["input"]["alignment_adapter_sha256"] or ""
        ),
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
            "Estimate GLP-1R and GCGR cell-based cAMP EC50 from one 26--30-residue "
            "incretin-like peptide or an expert-supplied 30-column alignment. The model "
            "does not predict binding affinity."
        ),
        epilog=(
            "Example: incretin-predict --sequence-file candidate.fasta\n"
            "Raw 26--29-residue local analogs are mapped only when the separately frozen "
            "adapter finds one unambiguous alignment. Residues are never trimmed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "sequence",
        nargs="?",
        help=(
            "A raw 26--30-residue canonical sequence. To provide exactly 30 model "
            "columns with explicit '-' gaps, also pass --aligned."
        ),
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
            "Read one raw or aligned sequence from UTF-8 text or single-record FASTA. "
            "Use '-' to read from standard input and avoid exposing a sequence in "
            "shell history or process listings."
        ),
    )
    parser.add_argument(
        "--aligned",
        action="store_true",
        help=(
            "Treat the input as an expert-supplied 30-column alignment. Use this for "
            "reviewed out-of-scope alignments; raw input is the default."
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
        help="Run the bundled example without supplying a sequence.",
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
                (EXAMPLE_SEQUENCE if args.aligned else EXAMPLE_RAW_SEQUENCE)
                if args.example
                else _read_sequence_file(args.sequence_file)
                if args.sequence_file is not None
                else args.sequence_option
                if args.sequence_option is not None
                else args.sequence
            )
            if not sequence:
                parser.error("a peptide sequence is required (or use --example)")
            result = predict(sequence) if args.aligned else predict_raw(sequence)
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
