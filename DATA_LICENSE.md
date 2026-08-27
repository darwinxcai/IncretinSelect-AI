# Data provenance and licensing

The MIT license in `LICENSE` applies to original code and documentation in this
repository. It does not replace the terms attached to upstream experimental data
or Protein Data Bank entries.

## Puszkarska et al. activity data

The training workbook, source-study P1–P15 workbooks, and derived tables originate
from Puszkarska *et al.*, *Nature Chemistry* (2024), DOI
[10.1038/s41557-024-01532-x](https://doi.org/10.1038/s41557-024-01532-x),
published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Raw workbooks are downloaded from checksum-pinned source URLs and are not
committed.

| Artifact | Contents | Terms |
|:---|:---|:---|
| `data/derived/sequence_clusters.csv` | Derived sequence-component IDs | CC BY 4.0 attribution to the experimental source |
| `data/derived/outer_folds.csv` | Derived cluster-intact fold assignments | CC BY 4.0 attribution to the experimental source |
| `data/derived/cluster_threshold_audit.csv` | Derived sequence-topology summary | CC BY 4.0 attribution to the experimental source |
| `data/derived/baseline_oof_predictions.csv` | Transformed activity values and predictions | CC BY 4.0 attribution to the experimental source |
| `reports/cpu_baseline_metrics.csv` | Aggregate benchmark metrics | CC BY 4.0 attribution to the experimental source |
| `data/derived/sequence_model_oof_predictions.csv` | Transformed activity values and nested ridge predictions | CC BY 4.0 attribution to the experimental source |
| `data/derived/cpu_sequence_model_figure_source.csv` | OOF points and paired model-comparison values used in the figure | CC BY 4.0 attribution to the experimental source |
| `reports/cpu_sequence_model_metrics.csv` | Aggregate nested-model metrics | CC BY 4.0 attribution to the experimental source |
| `reports/cpu_sequence_model_oof_figure.png` and `.svg` | Visualization derived from the activity data and OOF predictions | CC BY 4.0 attribution to the experimental source |
| `data/derived/external_predictions_locked.csv` | Predictions generated for the 15 published designs without using P1–P15 outcome labels | CC BY 4.0 attribution to the experimental source |
| `data/derived/external_dependency_groups.csv` | Sequence-based dependence-group assignments generated without P1–P15 outcome labels | CC BY 4.0 attribution to the experimental source |
| `reports/external_prediction_receipt.json` | Pre-score provenance, hashes, and metadata documenting prediction generation before P1–P15 outcome access | CC BY 4.0 attribution to the experimental source |
| `data/derived/external_evaluation_records.csv` | 45 peptide-endpoint exact/bound observations, predictions, and constraint losses | CC BY 4.0 attribution to the experimental source |
| `data/derived/external_evaluation_figure_source.csv` | Model metrics and dependence-aware contrasts used in the external figure | CC BY 4.0 attribution to the experimental source |
| `reports/external_evaluation_metrics.csv` | Aggregate censor-aware external-evaluation metrics | CC BY 4.0 attribution to the experimental source |
| `reports/external_evaluation_receipt.json` | Full scoring provenance, censor-aware metrics, and dependence sensitivities | CC BY 4.0 attribution to the experimental source |
| `reports/external_evaluation_figure.png` and `.svg` | Visualization derived from the published P1–P15 outcomes and locked predictions | CC BY 4.0 attribution to the experimental source |
| `src/incretinselect/assets/incretin_ridge_v1.json` | Frozen transformed model parameters and aligned reference sequences with per-reference activity outcomes omitted | CC BY 4.0 attribution to the experimental source |
| `reports/product_model_receipt.json` | Model-build checksums and fit metadata | CC BY 4.0 attribution to the experimental source |

When reusing these artifacts, cite the primary experimental paper and describe
any transformations. Exact URLs, file roles, SHA-256 values, and assay metadata
are recorded in `data/manifests/sources.json`.

## RCSB Protein Data Bank

Structure metadata and coordinates are governed by the RCSB PDB policies and the
citations attached to each entry. PDB identifiers and primary citations are
recorded in `data/derived/structures.csv`; cite the original structure papers
when reusing a complex. The manifest is a metadata index, not a relicensing of
the deposited coordinates.
