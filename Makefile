.PHONY: test lint product-smoke static-demo release-check release-readiness product-model fetch validate holdout splits baseline sequence-model figure external-predict external-score post-score-figure structures audit reproduce

PYTHON ?= python
PYTHONPATH := src

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m ruff check .

product-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/smoke_product.py

static-demo:
	$(PYTHON) scripts/sync_static_demo.py --check
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_static_demo.py --json-output reports/static_demo_verification.json

release-check:
	$(PYTHON) scripts/sync_package_resources.py --check
	$(PYTHON) scripts/sync_sdist_manifest.py --check
	$(PYTHON) scripts/verify_distribution.py --json-output reports/distribution_verification.json

release-readiness:
	$(PYTHON) scripts/audit_release_readiness.py

product-model:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/build_product_model.py

fetch:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/fetch_public_data.py --source puszkarska_2024_training --output-dir data/raw
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/fetch_public_data.py --source puszkarska_2024_prospective_holdout --output-dir data/raw

validate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/validate_activity_dataset.py data/raw/training_data.xlsx --config configs/activity_schema.json --json-output reports/activity_validation.json

holdout:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/freeze_prospective_holdout.py

splits:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/freeze_sequence_splits.py

baseline:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_cpu_baseline.py

sequence-model:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_cpu_sequence_model.py

figure: sequence-model
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/plot_cpu_sequence_model.py

external-predict:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/freeze_external_predictions.py

external-score:
	@test -n "$(LOCK_COMMIT)" || (echo "LOCK_COMMIT is required" && exit 2)
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/score_external_evaluation.py --lock-commit $(LOCK_COMMIT)

post-score-figure:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/plot_external_evaluation.py

structures:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/build_structure_manifest.py --seed configs/structure_targets.csv --output data/derived/structures.csv

audit: validate holdout splits baseline figure test

reproduce: fetch audit structures
