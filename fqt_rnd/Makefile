.PHONY: verify audit report development-pipeline engine-suite release oos canary

verify:
	python tools/verify_project.py

audit:
	python tools/collect_results.py
	python tools/audit_strategies.py
	python tools/source_inventory.py
	python tools/scan_secrets.py
	python tools/statistical_stress.py
	python tools/summarize_causality.py
	python tools/version_audit.py
	python tools/build_gate_matrix.py

report:
	python tools/build_report_artifact.py
	node "$${REPORT_BUILDER:-/root/.codex/plugins/cache/openai-curated-remote/data-analytics/0.2.8-13ceeea1f599/skills/build-report/scripts/deliver_portable_artifact.mjs}" --input report/artifact.json --output report/report.html | tee report/delivery_receipt.json

development-pipeline:
	bash scripts/run_development_pipeline.sh

engine-suite:
	bash scripts/run_engine_suite.sh

release:
	python tools/build_release.py

oos:
	@echo "BLOCKIERT: OOS remains sealed until decisions/promotion_decision.json says all_targets_pass=true." >&2
	@exit 2

canary:
	@echo "BLOCKIERT: no strategy passed promotion and OOS gates; no dry-run trading process started." >&2
	@exit 2
