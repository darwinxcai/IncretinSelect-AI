#!/usr/bin/env python3
"""Render the post-score P1--P15 external-evaluation summary figure."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/incretinselect-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from incretinselect.clustering import write_csv  # noqa: E402

MODEL_ORDER = ("ridge", "nn", "median", "component_mean")
ENDPOINT_ORDER = ("gcgr", "glp1r", "selectivity")
MODEL_LABELS = {
    "ridge": "Ridge",
    "nn": "Tied 1-NN",
    "median": "Row median",
    "component_mean": "Component mean",
}
ENDPOINT_LABELS = {
    "gcgr": "GCGR",
    "glp1r": "GLP-1R",
    "selectivity": "Selectivity",
}
COLORS = {
    "ridge": "#176B70",
    "nn": "#D07A33",
    "median": "#9AA2A9",
    "component_mean": "#59788E",
}
SOURCE_FIELDS = [
    "row_type",
    "endpoint",
    "model",
    "comparator",
    "dependency_group",
    "n",
    "value",
    "interval_lower",
    "interval_upper",
    "dependency_groups",
]


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _load_metrics(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 12:
        raise ValueError("Expected 12 external-evaluation metric rows")
    return rows


def _figure_source(
    metrics: list[dict[str, str]], receipt: dict[str, Any]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for metric in metrics:
        rows.append(
            {
                "row_type": "model_metric",
                "endpoint": metric["endpoint"],
                "model": metric["model"],
                "comparator": "",
                "dependency_group": "",
                "n": metric["n_informative"],
                "value": metric["constraint_mae_lower_bound"],
                "interval_lower": "",
                "interval_upper": "",
                "dependency_groups": "",
            }
        )

    primary = [
        row
        for row in receipt["headline_external_component_resampling"]
        if row["baseline"] == "nn"
    ]
    if {row["endpoint"] for row in primary} != {"gcgr", "glp1r"}:
        raise ValueError("Missing primary receptor comparisons")
    for comparison in primary:
        rows.append(
            {
                "row_type": "primary_delta",
                "endpoint": comparison["endpoint"],
                "model": comparison["challenger"],
                "comparator": comparison["baseline"],
                "dependency_group": "",
                "n": comparison["n_peptides"],
                "value": comparison["mae_delta_log10_pm"],
                "interval_lower": comparison["interval_lower"],
                "interval_upper": comparison["interval_upper"],
                "dependency_groups": comparison["n_dependency_groups"],
            }
        )

    macro_rows = [
        row
        for row in receipt["dependence_group_macro_sensitivity"]
        if row["group_field"] == "external_sequence_component_id"
    ]
    if {row["endpoint"] for row in macro_rows} != {"gcgr", "glp1r"}:
        raise ValueError("Missing external-component delta rows")
    for macro in macro_rows:
        for component, value in macro["group_mean_deltas"].items():
            rows.append(
                {
                    "row_type": "external_component_delta",
                    "endpoint": macro["endpoint"],
                    "model": macro["challenger"],
                    "comparator": macro["baseline"],
                    "dependency_group": component,
                    "n": "",
                    "value": value,
                    "interval_lower": "",
                    "interval_upper": "",
                    "dependency_groups": 4,
                }
            )
    return rows


def _plot(source_rows: list[dict[str, object]], png: str | Path, svg: str | Path) -> None:
    matplotlib.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "svg.hashsalt": "incretinselect-external-evaluation-v1",
        }
    )
    figure, axes = plt.subplots(
        1,
        2,
        figsize=(12.4, 5.9),
        gridspec_kw={"width_ratios": [1.35, 1.0]},
    )
    figure.patch.set_facecolor("white")
    figure.suptitle(
        "One-shot local-analogue evaluation: transfer is mixed, not a model win",
        x=0.06,
        ha="left",
        fontsize=15,
        fontweight="bold",
        color="#17242C",
    )

    axis = axes[0]
    metric_rows = [row for row in source_rows if row["row_type"] == "model_metric"]
    metric_lookup = {
        (str(row["model"]), str(row["endpoint"])): float(row["value"])
        for row in metric_rows
    }
    positions = np.arange(len(ENDPOINT_ORDER), dtype=float)
    width = 0.19
    offsets = np.asarray([-1.5, -0.5, 0.5, 1.5]) * width
    for model, offset in zip(MODEL_ORDER, offsets, strict=True):
        values = [metric_lookup[(model, endpoint)] for endpoint in ENDPOINT_ORDER]
        bars = axis.bar(
            positions + offset,
            values,
            width=width,
            color=COLORS[model],
            label=MODEL_LABELS[model],
            edgecolor="white",
            linewidth=0.6,
        )
        axis.bar_label(bars, fmt="%.2f", padding=2, fontsize=8, color="#33434C")
    axis.set_xticks(positions, [ENDPOINT_LABELS[item] for item in ENDPOINT_ORDER])
    axis.set_ylabel("Constraint MAE lower bound (log10 units)")
    axis.set_title("A  All retained models and endpoints", loc="left", fontweight="bold")
    axis.grid(axis="y", color="#DCE2E5", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, ncol=2, loc="upper left")
    axis.text(
        0.0,
        -0.23,
        "Censored receptor records contribute minimum constraint error; selectivity has 13 informative designs.",
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=8.7,
        color="#4B5B64",
    )

    axis = axes[1]
    primary_rows = {
        str(row["endpoint"]): row
        for row in source_rows
        if row["row_type"] == "primary_delta"
    }
    component_rows = [
        row for row in source_rows if row["row_type"] == "external_component_delta"
    ]
    y_positions = {"gcgr": 1.0, "glp1r": 0.0}
    component_jitter = {"EC001": -0.11, "EC002": -0.035, "EC003": 0.035, "EC004": 0.11}
    for endpoint in ("gcgr", "glp1r"):
        row = primary_rows[endpoint]
        value = float(row["value"])
        lower = float(row["interval_lower"])
        upper = float(row["interval_upper"])
        y = y_positions[endpoint]
        axis.errorbar(
            value,
            y,
            xerr=np.asarray([[value - lower], [upper - value]]),
            fmt="D",
            markersize=7,
            capsize=5,
            color=COLORS["ridge"] if value < 0 else "#A94E3B",
            ecolor="#263841",
            elinewidth=2,
            zorder=4,
        )
        for component in [item for item in component_rows if item["endpoint"] == endpoint]:
            axis.scatter(
                float(component["value"]),
                y + component_jitter[str(component["dependency_group"])],
                s=34,
                color="#7A8790",
                edgecolor="white",
                linewidth=0.6,
                zorder=3,
            )
        axis.text(
            value,
            y + 0.19,
            f"pooled {value:+.2f}",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color="#263841",
        )
    axis.axvline(0.0, color="#253740", linewidth=1.1)
    axis.set_yticks([1.0, 0.0], ["GCGR", "GLP-1R"])
    axis.set_xlabel("Ridge − 1-NN constraint MAE (negative favors ridge)")
    axis.set_title("B  Primary receptor contrasts", loc="left", fontweight="bold")
    axis.grid(axis="x", color="#DCE2E5", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.set_ylim(-0.45, 1.45)
    axis.text(
        0.0,
        -0.23,
        "Diamond/range: pooled delta + descriptive 95% interval.\n"
        "Gray dots: four external-component means.\n"
        "Only 4 components; intervals and leave-one-out ranges cross zero.",
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=8.7,
        color="#4B5B64",
    )

    figure.subplots_adjust(left=0.07, right=0.98, top=0.84, bottom=0.23, wspace=0.30)
    png_path, svg_path = Path(png), Path(svg)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        png_path,
        dpi=220,
        facecolor="white",
        metadata={"Software": "IncretinSelect-AI"},
    )
    figure.savefig(
        svg_path,
        facecolor="white",
        metadata={"Date": None, "Creator": "IncretinSelect-AI"},
    )
    # Matplotlib writes path commands with trailing spaces. Normalize the text so
    # release archives pass ``git diff --check`` without changing the rendering.
    svg_path.write_text(
        "\n".join(
            line.rstrip()
            for line in svg_path.read_text(encoding="utf-8").splitlines()
        )
        + "\n",
        encoding="utf-8",
    )
    plt.close(figure)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", default="reports/external_evaluation_metrics.csv")
    parser.add_argument("--receipt", default="reports/external_evaluation_receipt.json")
    parser.add_argument(
        "--source", default="data/derived/external_evaluation_figure_source.csv"
    )
    parser.add_argument("--png", default="reports/external_evaluation_figure.png")
    parser.add_argument("--svg", default="reports/external_evaluation_figure.svg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    receipt = _load_json(args.receipt)
    metrics = _load_metrics(args.metrics)
    source_rows = _figure_source(metrics, receipt)
    write_csv(args.source, source_rows, SOURCE_FIELDS)
    _plot(source_rows, args.png, args.svg)
    print(
        json.dumps(
            {
                "source_rows": len(source_rows),
                "source": args.source,
                "png": args.png,
                "svg": args.svg,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
