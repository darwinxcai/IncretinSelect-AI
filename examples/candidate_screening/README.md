# Candidate-screening example

This example shows the batch product behavior without using assay outcomes or
P1–P15 sequences. The first three rows are anonymized development sequences from
the model artifact's label-free applicability list. The all-alanine row is an
artificial guardrail case, not a biological negative control.

Run:

```bash
incretin-screen examples/candidate_screening/candidates.csv \
  --objective dual \
  --output examples/candidate_screening/screened_dual.csv \
  --receipt examples/candidate_screening/screening_receipt.json \
  --overwrite
```

The three development references receive an exploratory rank. The artificial row
keeps its numeric extrapolation but has a blank rank and an explicit
`outside_reference_neighborhood` reason. No row disappears silently.

`dual` minimizes the less favorable (larger) of the two predicted receptor log10
EC50 values. It is a transparent comparison rule, not proof of dual agonism. The
development references were used to fit the model, so this example verifies
software behavior only; it is not a predictive-accuracy evaluation.
