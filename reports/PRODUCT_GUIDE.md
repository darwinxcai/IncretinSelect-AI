# IncretinSelect-AI product guide

## Scope

IncretinSelect-AI estimates cell-based cAMP EC50 at GLP-1R and GCGR for an
incretin-like peptide represented in the source study's 30-position alignment. It
also reports the predicted EC50 ratio between receptors, similarity to the model's
reference sequences, and evidence needed to interpret the result.

The application is intended for exploratory comparison of compatible sequences.
Its outputs do not measure binding affinity, maximal assay response, safety, in vivo
activity, or clinical benefit. A passing software gate does not establish prediction
accuracy or experimental priority.

## Run the application

Python 3.10 or newer is required for the installed package. Inference does not
require a GPU, raw experimental workbook, or external model service.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install .

incretin-predict --example
incretin-web --open
```

`incretin-web` serves the same browser application and model artifact deployed on
[GitHub Pages](https://darwinxcai.github.io/IncretinSelect-AI/), rather than a
separate local interface. It binds to `127.0.0.1` by default and processes imported
files in the browser. The hosted application likewise has no sequence-processing
backend, analytics service, or external API. Both routes verify the model checksum
before enabling prediction.

To serve the checked-out `docs/` directory directly:

```bash
python -m http.server 8000 --directory docs
```

## Input contract

Single-sequence input must contain exactly 30 aligned characters drawn from:

```text
-ACDEFGHIKLMNPQRSTVWY
```

Lowercase and whitespace are normalized. The software rejects wrong lengths,
ambiguous residues, and noncanonical symbols; it does not pad, truncate, or infer an
alignment. FASTA import accepts one record. A raw sequence must first be mapped to
the source study's alignment and reviewed by the user.

The `-` symbol denotes an alignment gap. It does not encode a linker, cleavage, or
chemical modification. The model cannot represent Aib, lipidation, amidation,
cyclization, stapling, D-amino acids, or other noncanonical chemistry. Structure
files are unsupported because the released model uses sequence features only.

## Single-sequence results

For each receptor, the application reports predicted EC50 on three scales:
log10(EC50 / 1 pM), pM, and nM. Lower EC50 indicates greater functional potency in
the source cell assay. The potency ratio is defined as:

```text
log10(GCGR EC50 / GLP-1R EC50)
```

A positive value indicates lower predicted EC50 at GLP-1R; a negative value
indicates lower predicted EC50 at GCGR. The interface describes ratios within
three-fold as roughly balanced, but this is descriptive wording rather than a
validated decision threshold or evidence of dual agonism.

Each result has one of four evidence states:

- `training_reference_match`: the input exactly matches a training reference, so
  the estimate is in-sample and does not test prediction on a new peptide;
- `local_analogue_mixed_evidence`: nearest-reference identity is at least 0.85 but
  below 1.00; the sequence passes the local-analog gate, but retrospective transfer
  among 15 published local analogs was mixed;
- `outside_ranking_scope`: identity is at least 0.70 but below 0.85, so the numeric
  estimate is displayed but not eligible for ranking; or
- `far_outside_ranking_scope`: identity is below 0.70 and the estimate is a distant
  extrapolation that should not be used to order experiments.

The 0.85 threshold defined sequence-identity components in the development
benchmark. The application reuses it as a ranking gate; it was not calibrated to
prediction error or confidence. Ranking also requires at least 26 standard
residues in the aligned input.

### Nearest-reference attribution

The ridge model is linear and additive. For the selected nearest reference, the
application reports the query-minus-reference prediction difference and decomposes
it across changed positions. If references tie, it applies a fixed selection rule
and reports the tie count.

These contributions explain the fitted model's arithmetic. They are not causal
mutation effects, experimental measurements, or evidence that a substitution will
produce the same change in the laboratory. The stored reference panel contains 125
aligned sequences with their per-reference activity outcomes omitted.

Single results can be downloaded as JSON, CSV, or a concise Markdown report. The
command line exposes the same formats:

```bash
incretin-predict HSQGTFTSDYSKYLDSRAASEFVQWLISH- --format json
incretin-predict HSQGTFTSDYSKYLDSRAASEFVQWLISH- --format csv --output result.csv
incretin-predict HSQGTFTSDYSKYLDSRAASEFVQWLISH- --format markdown --output result.md
incretin-predict --model-info
```

## Candidate-table screening

`incretin-screen` accepts a UTF-8 CSV with exactly two columns:

```text
candidate_id,aligned_sequence
variant_a,HSQGTFTSDYSKYLDSRAASEFVQWLISE-
```

The `glp1r` and `gcgr` objectives minimize the corresponding predicted
log10(EC50 / 1 pM). The `dual` objective minimizes the larger, less favorable of the
two receptor scores. Lower scores rank first. The dual score was not benchmarked as
a separate endpoint.

Only rows meeting the 0.85 identity and 26-residue gates are ranked. Invalid
and out-of-scope rows remain in the output with a status and reason. Duplicate IDs
stop the run; duplicate sequences remain visible and receive the same dense rank.

For each ordered row, the output includes its score distance from the top-ranked row in
log10 units and as an EC50 fold ratio. It also marks whether that distance is within
one development out-of-fold MAE of the top score. For a receptor-specific
objective, the context is that receptor's development MAE. For `dual`, it is the
larger receptor-specific MAE because the max-receptor score has no separate
benchmark. This comparison is population-level descriptive context—not an
individual confidence interval, significance threshold, or equivalence test.

```bash
incretin-screen examples/candidate_screening/candidates.csv \
  --objective dual \
  --output screened.csv \
  --receipt screening_receipt.json
```

The Python CLI accepts at most 10,000 rows or 10 MB; the browser accepts 500 rows or
2 MB. The receipt records SHA-256 hashes of the original input bytes and generated
output bytes, linking each result to the exact files used. It also records the
objective, ranking gates, score context, row counts, software and model versions,
and scientific boundaries.

## Validation context

Development cross-validation produced the following population-level mean absolute
errors:

| Endpoint | MAE, log10 units | Geometric fold error |
|:---|---:|---:|
| GCGR EC50 | 0.63 | 4.2-fold |
| GLP-1R EC50 | 1.07 | 11.7-fold |
| GCGR/GLP-1R EC50 ratio | 1.14 | 13.7-fold |

These values summarize the benchmark population; they are not uncertainty intervals
for individual predictions. In the locked retrospective P1–P15 external evaluation,
ridge had lower GCGR point error but higher pooled GLP-1R error than 1-NN, and the
results did not support overall model superiority. See
[`EXTERNAL_EVALUATION.md`](EXTERNAL_EVALUATION.md) for censoring rules and
dependence analyses.

## Verification and provenance

```bash
make test
make product-smoke
make static-demo
make release-check
```

The release check builds and installs the wheel outside the source tree, verifies
the packaged browser application and model, and exercises CLI, browser, export, and
batch contracts. The model artifact is `incretinselect_aligned_ridge_v1` version
`1.0.0`; software and model versions are reported separately. Its training data
derive from Puszkarska *et al.*, *Nature Chemistry* (2024), DOI
`10.1038/s41557-024-01532-x`, under CC BY 4.0. Project code is MIT-licensed; see
[`DATA_LICENSE.md`](../DATA_LICENSE.md) for the data boundary.
