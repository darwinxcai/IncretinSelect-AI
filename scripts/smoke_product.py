#!/usr/bin/env python3
"""Offline smoke test for the installed CLI model and local web renderer."""

from __future__ import annotations

import math

from incretinselect.cli import EXAMPLE_SEQUENCE, format_csv, format_text
from incretinselect.product import predict
from incretinselect.screen import build_screening
from incretinselect.web import render_page


def main() -> int:
    result = predict(EXAMPLE_SEQUENCE)
    gcgr = float(result["predictions"]["gcgr"]["log10_ec50_pm"])
    glp1r = float(result["predictions"]["glp1r"]["log10_ec50_pm"])
    if not math.isfinite(gcgr) or not math.isfinite(glp1r):
        raise RuntimeError("Model returned a non-finite estimate")
    if abs(gcgr - 0.9868330997153905) > 1e-12:
        raise RuntimeError("Bundled model does not reproduce the locked P1 GCGR estimate")
    if abs(glp1r - 1.012508198632634) > 1e-12:
        raise RuntimeError("Bundled model does not reproduce the locked P1 GLP-1R estimate")
    if "not binding affinity" not in format_text(result):
        raise RuntimeError("Terminal output lost the required endpoint warning")
    if EXAMPLE_SEQUENCE not in format_csv(result):
        raise RuntimeError("CSV output lost the input sequence")
    page = render_page(sequence=EXAMPLE_SEQUENCE, result=result)
    if (
        "Sequence-only functional-potency estimate" not in page
        or result["model"]["artifact_sha256"] not in page
    ):
        raise RuntimeError("Local web interface did not render a complete result")
    screening_input = (
        "candidate_id,aligned_sequence\n"
        "demo_ref_93,HSQGTFTSDYSKYLDSRAASEFVQWLISE-\n"
        "demo_ref_11,HSQGTFTSDYSKYLDSRAAAKFVQWLLNGG\n"
        "outside_guardrail,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
    ).encode("utf-8")
    screening_csv, screening_receipt, screening_exit = build_screening(
        screening_input,
        "dual",
    )
    if screening_exit != 0 or screening_receipt["counts"]["ranked_rows"] != 2:
        raise RuntimeError("Guarded batch screening did not rank the label-free demo rows")
    if screening_receipt["counts"]["out_of_scope_rows"] != 1:
        raise RuntimeError("Guarded batch screening did not retain the out-of-scope row")
    if "not binding affinity" not in screening_csv:
        raise RuntimeError("Batch screening output lost the required endpoint warning")
    print(
        "product smoke test passed: locked example reproduced, CLI/CSV rendered, "
        f"batch screening guarded, web page rendered ({len(page)} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
