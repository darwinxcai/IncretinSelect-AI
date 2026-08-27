# Browser application

This directory contains the static application deployed through GitHub Pages. It
runs the same released model as the Python package and supports aligned FASTA/text
input, CSV screening, and local result downloads. Imported sequences and
calculations remain in the browser; no sequence data are sent to a backend,
analytics service, or external API.

## Run locally

From the repository root:

```bash
python -m http.server 8000 --directory docs
```

Open `http://127.0.0.1:8000`. Direct `file://` access is unsupported because the
application fetches and verifies its model artifact before enabling prediction.

To confirm that the browser artifact is current and numerically consistent with the
Python package, run:

```bash
make static-demo
```

Update the browser copy of the model only with
`scripts/sync_static_demo.py`. Deployment requires the model checksum, privacy
checks, and browser/Python parity checks to pass.

## Input and ranking scope

Single-sequence input must contain one 30-position alignment using the 20 standard
amino-acid letters and `-` for gaps. Batch input must be a UTF-8 CSV with exactly
`candidate_id,aligned_sequence` and an explicit GLP-1R, GCGR, or dual ranking
objective.

The application ranks an input only when its nearest-reference aligned identity is
at least 0.85 and it contains at least 26 standard residues. The 0.85 threshold was
used to define sequence components in the development benchmark; its use here is a
software gate, not a calibrated estimate of prediction confidence. Invalid and
out-of-scope rows remain in the downloaded output with their status and exclusion
reason.

The current model uses sequence features only, so structure files are not supported.
Outputs are point estimates of cell-based cAMP EC50. They do not measure binding
affinity, maximal assay response, safety, in vivo activity, or clinical benefit and do not
constitute candidate recommendations. The locked retrospective P1–P15 external
evaluation was mixed; see
[`reports/EXTERNAL_EVALUATION.md`](../reports/EXTERNAL_EVALUATION.md) for the
complete result.
