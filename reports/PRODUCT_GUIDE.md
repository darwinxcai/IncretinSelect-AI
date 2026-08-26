# IncretinSelect-AI local product guide

## Objective

The app answers a narrow research question:

> For an incretin-like peptide represented in the model's 30-position alignment,
> what cell-based cAMP EC50 values does the frozen sequence model estimate for
> GLP-1R and GCGR, and how similar is that sequence to the model's references?

This could support early hypothesis formation when a scientist has several
compatible sequence variants and wants to compare their predicted receptor
balance before deciding what to test. It is not evidence that a peptide binds,
activates either receptor, is a good drug, or is safe.

## Install and run

Python 3.10 or newer is required. No GPU, web API, or raw experimental workbook
is required for inference.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .

incretin-predict --example
incretin-screen examples/candidate_screening/candidates.csv \
  --objective dual --output screened.csv --receipt screening_receipt.json
incretin-web --open
```

The web app is served only on `127.0.0.1`; submitted sequences are processed by
the local Python process and are not sent to another service.

## Zero-install browser route

The static demo in `docs/` runs the same frozen coefficients directly in a modern
browser. It has no backend, external API, CDN, analytics, or outbound sequence
transmission. The browser hashes the copied model before enabling inference, and
CI compares its numerical output with the Python package on 12 label-free model
references.

```bash
python -m http.server 8000 --directory docs
```

Open `http://127.0.0.1:8000`. The public GitHub Pages workflow deploys only after
the model-copy, privacy, and browser/Python parity checks pass. The browser route
has the same 30-position input contract and scientific limitations as the Python
CLI; it is a more accessible interface, not a stronger model.

## Input contract

The model does not accept an arbitrary raw peptide. It accepts exactly 30 aligned
characters drawn from:

```text
-ACDEFGHIKLMNPQRSTVWY
```

Lowercase and whitespace are normalized. The software rejects FASTA headers,
wrong lengths, ambiguous residues, and noncanonical symbols. It never pads,
truncates, or auto-aligns the sequence.

Example input:

```text
positions  123456789012345678901234567890
sequence   HSQGTFTSDYSKYLDSRAASEFVQWLISH-
```

Why this matters: the source study used a curated 30-column alignment. Some long
constructs included terminal linker residues that were absent from that aligned
model input, while some shorter cores needed internal or terminal gaps. Silently
taking the first 30 residues would therefore be scientifically wrong. A raw
sequence must first be mapped into the same alignment and checked by the user.

`-` is an alignment gap. It does not encode a cleavage, linker, or chemical
modification. The model cannot represent Aib, lipidation, amidation, cyclization,
stapling, D-amino acids, or other noncanonical chemistry.

## Read the output

For each receptor, the app reports the same point estimate in three forms:

- `log10 EC50 (pM)`, which is the scale learned by the model;
- EC50 in pM;
- EC50 in nM.

Lower EC50 means that less peptide is predicted to be needed for half of the
measured maximum cAMP response in the assay. EC50 combines properties of the
ligand, receptor, expression system, and signaling assay. It is not a dissociation
constant or binding affinity, and it is not maximum efficacy.

The balance is defined as:

```text
log10(GCGR EC50 / GLP-1R EC50)
```

- A positive value means GLP-1R is predicted to have the lower EC50.
- A negative value means GCGR is predicted to have the lower EC50.
- Zero means equal predicted EC50 values.

The interface calls values within three-fold “roughly balanced.” That wording is
descriptive and is not a validated experimental decision threshold. Potency at two
receptors also does not prove dual agonism because maximum response is not modeled.

## Applicability and uncertainty

The app compares the query with 125 label-free aligned reference sequences. The
nearest identity is used only as a transparent applicability check:

- at least 0.85: `close_analogue`;
- 0.70 to below 0.85: `distant_analogue`;
- below 0.70: `outside_reference_neighborhood`.

The 0.85 value was the benchmark's sequence-family boundary. The 0.70 lower display
boundary is a conservative interface heuristic rather than a benchmark-selected
cutoff. Neither is a calibrated confidence probability, and a close analogue can
still receive a poor prediction.

Development cross-validation produced mean absolute errors of approximately:

| Output | MAE in log10 units | Geometric fold error |
|:---|---:|---:|
| GCGR EC50 | 0.63 | 4.2-fold |
| GLP-1R EC50 | 1.07 | 11.7-fold |
| EC50 balance | 1.14 | 13.7-fold |

These are population-level summaries, not confidence intervals for a new query.
On 15 separately scored published designs, the GCGR point error was lower but its
dependence-aware interval crossed zero, while pooled GLP-1R error was worse versus
the nearest-sequence comparator. The release therefore reports no overall external
superiority.

## Structured use

```bash
incretin-predict HSQGTFTSDYSKYLDSRAASEFVQWLISH- --format json
incretin-predict HSQGTFTSDYSKYLDSRAASEFVQWLISH- --format csv --output result.csv
incretin-predict --model-info
```

JSON retains warnings, applicability details, benchmark context, version, and
checksum. CSV gives one flat row for a workflow or spreadsheet.

## Compare a candidate shortlist

`incretin-screen` accepts a UTF-8 CSV with exactly two columns:

```text
candidate_id,aligned_sequence
variant_a,HSQGTFTSDYSKYLDSRAASEFVQWLISE-
```

The user must choose one objective. `glp1r` and `gcgr` sort by the corresponding
predicted log10 EC50. `dual` sorts by the larger (less favorable) of the two
receptor log10 EC50 values. Lower is first for every objective. There is no
selectivity-only ranking because a sequence predicted weak at both receptors can
still look balanced, and receptor balance was the weakest development comparison.

Ranking has two hard safety gates: the applicability tier must be
`close_analogue`, and the aligned input must contain at least 26 standard
residues. Valid rows outside either gate keep their numeric extrapolation but have
a blank rank and a specific exclusion reason. Malformed rows also remain in the
file as `input_error`; a partial run returns exit code 1. Duplicate candidate IDs
are fatal, while duplicate sequences receive the same dense rank.

The output JSON receipt records SHA-256 checksums for the exact input and CSV,
the objective definition, row-state counts, ranking rule, model checksum, and
false values for P1–P15 outcome access and structure inference. Output files are
each written through a per-file atomic replace and are not replaced unless
`--overwrite` is supplied.

The checked example in `examples/candidate_screening/` uses only three label-free
development references and one artificial out-of-scope row. The reference rows
are in-sample, so the example verifies the software contract rather than model
accuracy. A shortlist rank remains exploratory model ordering for human review,
not an experimental recommendation or evidence of dual agonism.

## Verification and provenance

```bash
make test
make product-smoke
make static-demo
make release-check
```

The release check builds the wheel without contacting an external model or data
service, verifies that the bundled model and entry points are present, installs
the wheel into a temporary environment, and runs JSON, single-prediction CSV,
guarded batch-screening, and local-browser smoke tests from outside the source
tree. Its receipt is written to
`reports/distribution_verification.json`.

The checked-in artifact is `incretinselect_aligned_ridge_v1` version `1.0.0`.
It contains the frozen transformed ridge parameters and 125 label-free reference
alignments, but no per-reference activity labels. The build receipt records the
source checksums, selected ridge strength, and artifact checksum in
`reports/product_model_receipt.json`.

The artifact reproduces all P1–P15 ridge estimates in the prediction file that was
committed before external outcome scoring. Its training data and aligned reference
sequences derive from Puszkarska *et al.*, *Nature Chemistry* (2024),
DOI `10.1038/s41557-024-01532-x`, under CC BY 4.0. Original project code is MIT
licensed; see `DATA_LICENSE.md` for the data boundary.
