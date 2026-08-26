#!/usr/bin/env python3
"""Render the deterministic publication figure for the CPU sequence analysis."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/incretinselect-matplotlib")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "incretinselect-cpu-sequence-v1"

import matplotlib.pyplot as plt  # noqa: E402

ENDPOINTS = (
    ("GCGR", "gcgr_log10_ec50_pm", "A"),
    ("GLP-1R", "glp1r_log10_ec50_pm", "B"),
)
COMPARISON_ORDER = (
    "GCGR log10 EC50 (pM)",
    "GLP-1R log10 EC50 (pM)",
    "selectivity log10 ratio",
)
COMPARISON_LABELS = {
    "GCGR log10 EC50 (pM)": "GCGR",
    "GLP-1R log10 EC50 (pM)": "GLP-1R",
    "selectivity log10 ratio": "Selectivity",
}
FOLD_STYLES = {
    1: ("#4477AA", "o"),
    2: ("#CC6677", "s"),
    3: ("#228833", "^"),
}
SOURCE_FIELDS = [
    "panel",
    "row_type",
    "peptide_id",
    "cluster_id",
    "outer_fold",
    "endpoint",
    "model",
    "actual_log10",
    "predicted_log10",
    "pooled_mae_log10",
    "spearman_rho",
    "r_squared",
    "ridge_mae_log10",
    "nn_mae_log10",
    "mae_delta_log10",
    "ci_lower",
    "ci_upper",
    "confidence_level",
    "bootstrap_resamples",
    "bootstrap_seed",
]


def _load_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_source(path: str | Path, rows: list[dict[str, object]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _figure_source_rows(
    predictions: list[dict[str, str]], payload: dict[str, Any]
) -> list[dict[str, object]]:
    metrics = {
        (row["model"], row["endpoint"]): row
        for row in payload["pooled_metrics"]
    }
    comparisons = {row["endpoint"]: row for row in payload["paired_comparisons"]}
    rows: list[dict[str, object]] = []
    for endpoint, column, panel in ENDPOINTS:
        metric_endpoint = f"{endpoint} log10 EC50 (pM)"
        metric = metrics[("ridge", metric_endpoint)]
        for prediction in predictions:
            rows.append(
                {
                    "panel": panel,
                    "row_type": "oof_prediction",
                    "peptide_id": prediction["peptide_id"],
                    "cluster_id": prediction["cluster_id"],
                    "outer_fold": prediction["outer_fold"],
                    "endpoint": endpoint,
                    "model": "component_weighted_ridge",
                    "actual_log10": prediction[f"actual_{column}"],
                    "predicted_log10": prediction[f"ridge_{column}"],
                    "pooled_mae_log10": metric["mae_log10_pm"],
                    "spearman_rho": metric["spearman_rho"],
                    "r_squared": metric["r_squared"],
                    "ridge_mae_log10": "",
                    "nn_mae_log10": "",
                    "mae_delta_log10": "",
                    "ci_lower": "",
                    "ci_upper": "",
                    "confidence_level": "",
                    "bootstrap_resamples": "",
                    "bootstrap_seed": "",
                }
            )
    for endpoint in COMPARISON_ORDER:
        comparison = comparisons[endpoint]
        rows.append(
            {
                "panel": "C",
                "row_type": "paired_mae_comparison",
                "peptide_id": "",
                "cluster_id": "",
                "outer_fold": "",
                "endpoint": COMPARISON_LABELS[endpoint],
                "model": "ridge_minus_tied_1nn",
                "actual_log10": "",
                "predicted_log10": "",
                "pooled_mae_log10": "",
                "spearman_rho": "",
                "r_squared": "",
                "ridge_mae_log10": comparison["ridge_mae_log10_pm"],
                "nn_mae_log10": comparison["nn_mae_log10_pm"],
                "mae_delta_log10": comparison["mae_delta_log10_pm"],
                "ci_lower": comparison["ci_lower"],
                "ci_upper": comparison["ci_upper"],
                "confidence_level": comparison["confidence_level"],
                "bootstrap_resamples": comparison["resamples"],
                "bootstrap_seed": comparison["seed"],
            }
        )
    return rows


def _axis_limits(actual: list[float], predicted: list[float]) -> tuple[float, float]:
    lower = math.floor((min(actual + predicted) - 0.1) * 2.0) / 2.0
    upper = math.ceil((max(actual + predicted) + 0.1) * 2.0) / 2.0
    return lower, upper


def _render(
    predictions: list[dict[str, str]],
    payload: dict[str, Any],
    png_path: str | Path,
    svg_path: str | Path,
) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9.5,
            "axes.linewidth": 0.8,
            "axes.edgecolor": "#333333",
            "xtick.color": "#333333",
            "ytick.color": "#333333",
            "text.color": "#222222",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    figure = plt.figure(figsize=(10.4, 7.25))
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=(1.0, 0.68),
        left=0.075,
        right=0.975,
        top=0.91,
        bottom=0.105,
        hspace=0.42,
        wspace=0.24,
    )
    metric_lookup = {
        (row["model"], row["endpoint"]): row
        for row in payload["pooled_metrics"]
    }

    for index, (endpoint, column, panel) in enumerate(ENDPOINTS):
        axis = figure.add_subplot(grid[0, index])
        actual = [float(row[f"actual_{column}"]) for row in predictions]
        predicted = [float(row[f"ridge_{column}"]) for row in predictions]
        lower, upper = _axis_limits(actual, predicted)
        axis.plot(
            [lower, upper],
            [lower, upper],
            color="#777777",
            linewidth=1.0,
            linestyle=(0, (4, 3)),
            zorder=1,
        )
        for fold, (color, marker) in FOLD_STYLES.items():
            selected = [row for row in predictions if int(row["outer_fold"]) == fold]
            axis.scatter(
                [float(row[f"actual_{column}"]) for row in selected],
                [float(row[f"ridge_{column}"]) for row in selected],
                s=30,
                marker=marker,
                color=color,
                edgecolor="white",
                linewidth=0.45,
                alpha=0.82,
                label=f"Outer fold {fold}",
                zorder=2,
            )
        axis.set_xlim(lower, upper)
        axis.set_ylim(lower, upper)
        axis.set_aspect("equal", adjustable="box")
        axis.grid(color="#E1E1E1", linewidth=0.65, alpha=0.75)
        axis.set_axisbelow(True)
        axis.set_xlabel("Observed log$_{10}$ EC50 (pM)")
        axis.set_ylabel("OOF predicted log$_{10}$ EC50 (pM)")
        axis.set_title(f"Nested ridge: {endpoint}", loc="left", fontweight="semibold")
        axis.text(
            -0.13,
            1.08,
            panel,
            transform=axis.transAxes,
            fontsize=13,
            fontweight="bold",
            va="top",
        )
        metric = metric_lookup[("ridge", f"{endpoint} log10 EC50 (pM)")]
        annotation = (
            f"MAE = {metric['mae_log10_pm']:.3f}\n"
            f"Spearman $\\rho$ = {metric['spearman_rho']:.3f}\n"
            f"$R^2$ = {metric['r_squared']:.3f}"
        )
        axis.text(
            0.04,
            0.96,
            annotation,
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=8.5,
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": "#BBBBBB",
                "linewidth": 0.6,
                "alpha": 0.9,
            },
        )
        if index == 0:
            axis.legend(
                loc="lower right",
                frameon=True,
                framealpha=0.92,
                edgecolor="#BBBBBB",
                fontsize=8,
            )

    comparison_axis = figure.add_subplot(grid[1, :])
    comparisons = {row["endpoint"]: row for row in payload["paired_comparisons"]}
    y_positions = [2, 1, 0]
    comparison_axis.axvspan(-0.9, 0.0, color="#4477AA", alpha=0.055, zorder=0)
    comparison_axis.axvspan(0.0, 0.4, color="#CC6677", alpha=0.055, zorder=0)
    comparison_axis.axvline(0.0, color="#333333", linewidth=1.0, zorder=1)
    for y_position, endpoint in zip(y_positions, COMPARISON_ORDER, strict=True):
        row = comparisons[endpoint]
        delta = float(row["mae_delta_log10_pm"])
        lower = float(row["ci_lower"])
        upper = float(row["ci_upper"])
        color = "#4477AA" if delta < 0 else "#CC6677"
        comparison_axis.errorbar(
            delta,
            y_position,
            xerr=[[delta - lower], [upper - delta]],
            fmt="o",
            markersize=6.5,
            color=color,
            ecolor=color,
            elinewidth=1.8,
            capsize=4,
            capthick=1.2,
            markeredgecolor="white",
            markeredgewidth=0.5,
            zorder=3,
        )
        comparison_axis.text(
            0.37,
            y_position,
            f"$\\Delta$ = {delta:+.3f}",
            ha="right",
            va="center",
            fontsize=8.5,
        )
    comparison_axis.set_xlim(-0.9, 0.4)
    comparison_axis.set_ylim(-0.65, 2.65)
    comparison_axis.set_yticks(y_positions, [COMPARISON_LABELS[item] for item in COMPARISON_ORDER])
    comparison_axis.set_xlabel("Pooled MAE difference (ridge − tied 1-NN), log$_{10}$ units")
    comparison_axis.set_title(
        "Paired whole-component bootstrap comparison",
        loc="left",
        fontweight="semibold",
    )
    comparison_axis.text(
        -0.055,
        1.09,
        "C",
        transform=comparison_axis.transAxes,
        fontsize=13,
        fontweight="bold",
        va="top",
    )
    comparison_axis.text(
        0.22,
        0.93,
        "Ridge lower error",
        transform=comparison_axis.transAxes,
        ha="center",
        va="bottom",
        color="#315C8A",
        fontsize=8,
    )
    comparison_axis.text(
        0.83,
        0.93,
        "1-NN lower error",
        transform=comparison_axis.transAxes,
        ha="center",
        va="bottom",
        color="#9E4A5A",
        fontsize=8,
    )
    comparison_axis.grid(axis="x", color="#DDDDDD", linewidth=0.65)
    comparison_axis.set_axisbelow(True)
    comparison_axis.spines["top"].set_visible(False)
    comparison_axis.spines["right"].set_visible(False)

    figure.suptitle(
        "Cluster-held-out sequence modeling of incretin receptor potency",
        x=0.075,
        y=0.972,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    figure.text(
        0.075,
        0.035,
        (
            "OOF = out of fold; n = 125 peptides in 17 sequence components. "
            "Error bars: 95% percentile intervals from 10,000 paired component "
            "resamples. All intervals cross zero."
        ),
        ha="left",
        va="bottom",
        fontsize=8,
        color="#444444",
    )

    png_output = Path(png_path)
    svg_output = Path(svg_path)
    png_output.parent.mkdir(parents=True, exist_ok=True)
    svg_output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        png_output,
        dpi=220,
        metadata={"Software": "IncretinSelect-AI"},
    )
    figure.savefig(
        svg_output,
        metadata={"Creator": "IncretinSelect-AI", "Date": None},
    )
    plt.close(figure)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predictions", default="data/derived/sequence_model_oof_predictions.csv"
    )
    parser.add_argument("--report-json", default="reports/cpu_sequence_model.json")
    parser.add_argument(
        "--source-csv", default="data/derived/cpu_sequence_model_figure_source.csv"
    )
    parser.add_argument("--png", default="reports/cpu_sequence_model_oof_figure.png")
    parser.add_argument("--svg", default="reports/cpu_sequence_model_oof_figure.svg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    predictions = _load_csv(args.predictions)
    payload = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    if len(predictions) != 125 or len({row["peptide_id"] for row in predictions}) != 125:
        raise ValueError("Figure requires exactly 125 unique OOF predictions")
    if payload.get("holdout_labels_accessed") or payload.get("holdout_sequences_accessed"):
        raise ValueError("Figure input report violates the prospective holdout boundary")
    source_rows = _figure_source_rows(predictions, payload)
    _write_source(args.source_csv, source_rows)
    _render(predictions, payload, args.png, args.svg)
    print(
        json.dumps(
            {
                "source_rows": len(source_rows),
                "source_csv": args.source_csv,
                "png": args.png,
                "svg": args.svg,
                "holdout_data_accessed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
