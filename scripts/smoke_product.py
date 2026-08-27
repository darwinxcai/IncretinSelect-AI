#!/usr/bin/env python3
"""Offline smoke test for the installed CLI model and local web renderer."""

from __future__ import annotations

import math

from incretinselect.cli import EXAMPLE_SEQUENCE, format_csv, format_text
from incretinselect.product import predict
from incretinselect.screen import build_screening
from incretinselect.web import render_page, verify_web_assets


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
    if "do not measure binding affinity" not in format_text(result):
        raise RuntimeError("Terminal output lost the required endpoint warning")
    if EXAMPLE_SEQUENCE not in format_csv(result):
        raise RuntimeError("CSV output lost the input sequence")
    page = render_page()
    if (
        "Candidate screen" not in page
        or verify_web_assets()["artifact_sha256"] != result["model"]["artifact_sha256"]
    ):
        raise RuntimeError("Installed web interface does not match the verified browser app")
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
        raise RuntimeError("Guarded batch screening did not rank the outcome-free demo rows")
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
