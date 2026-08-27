# Training-only sequence split audit

**Frozen:** 2026-08-20
**Input:** 125 aligned training sequences; no potency values or P1–P15 labels were
used to select the threshold or assign folds.

## Predeclared rule

For each candidate threshold, sequences are nodes in a graph and an edge joins a
pair whose aligned identity meets the threshold. Connected components remain
intact. Components are placed, largest first, into the currently smallest of
three folds. The selected threshold is the **lowest** candidate that produces at
least nine components and a largest/smallest fold-size ratio no greater than
1.10. Lower thresholds are more conservative against analog leakage, so this
rule selects the most conservative candidate that remains evaluable.

Identity is exact character agreement over alignment columns where at least one
sequence is non-gap; double-gap columns are excluded. The rule is stored in
`configs/sequence_split.json`.

## Threshold audit

| Identity | Components | Singletons | Largest | Fold sizes | Size ratio | Eligible |
|---:|---:|---:|---:|:---:|---:|:---:|
| 0.70 | 5 | 2 | 119 | 119 / 3 / 3 | 39.667 | False |
| 0.75 | 8 | 4 | 73 | 73 / 44 / 8 | 9.125 | False |
| 0.80 | 12 | 5 | 54 | 54 / 40 / 31 | 1.742 | False |
| 0.85 **(selected)** | 17 | 8 | 40 | 42 / 42 / 41 | 1.024 | True |
| 0.90 | 21 | 11 | 39 | 42 / 42 / 41 | 1.024 | True |
| 0.95 | 53 | 35 | 33 | 42 / 42 / 41 | 1.024 | True |

## Frozen split

- Selected identity threshold: **0.85**.
- Connected components: **17**.
- Deterministic outer-fold sizes: **42 / 42 / 41**.
- Maximum identity observed across two different folds:
  **0.8333** (seq_pep13 vs seq_pep65), below
  the 0.85 clustering boundary.
- Frozen assignments: `data/derived/sequence_clusters.csv` and
  `data/derived/outer_folds.csv`.

The connected-component rule prevents any direct pair at or above 0.85 identity
from crossing folds. It does not make these 125 engineered peptides equivalent to
a broad natural-family benchmark; performance must be described as
cluster-held-out generalization within this same-assay design set.

## Reproduce

```bash
python scripts/freeze_sequence_splits.py
```

The command verifies the public training-workbook checksum and fails if the
machine-selected threshold differs from the predeclared frozen value.
