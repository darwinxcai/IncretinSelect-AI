# Candidate-screening example

This example exercises the batch-screening workflow without assay outcomes. The
first three rows are training-set reference sequences stored in the model artifact
without their activity measurements. The all-alanine row demonstrates out-of-scope
handling and is not a biological negative control.

Run:

```bash
incretin-screen examples/candidate_screening/candidates.csv \
  --objective dual \
  --output examples/candidate_screening/screened_dual.csv \
  --receipt examples/candidate_screening/screening_receipt.json \
  --overwrite
```

The three reference rows meet the ranking gates. The artificial row retains its
numeric extrapolation but receives no rank because it is
`outside_reference_neighborhood`. Every input row remains in the output with an
explicit status or exclusion reason.

The `dual` objective ranks candidates by the larger, less favorable of their two
predicted log10(EC50 / 1 pM) values; lower scores rank first. This is a comparison
rule for predicted potency at both receptors, not evidence of dual agonism. Because
the three reference sequences were used to fit the model, this example tests
software behavior only and provides no estimate of predictive accuracy. It does not
use sequences or outcome labels from the locked retrospective P1–P15 external
evaluation.
