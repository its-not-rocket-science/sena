.PHONY: install install-dev test lint format quality api docker-up bump-version pilot-evidence pilot-integration-pack demo-k8s demo-monitoring integration-matrix-check

install:
	pip install -e .

install-dev:
	pip install -e .[api,dev]

test:
	pytest

lint:
	ruff check src/sena tests
	mypy src/sena

format:
	ruff format src/sena tests --exclude src/sena/legacy

quality:
	ruff format --check src/sena tests --exclude src/sena/legacy
	ruff check src/sena tests
	pytest
api:
	python -m uvicorn sena.api.app:app --reload

docker-up:
	docker compose up --build


bump-version:
	@test -n "$(VERSION)" || (echo "Usage: make bump-version VERSION=X.Y.Z" && exit 1)
	python scripts/bump_version.py $(VERSION)


pilot-evidence:
	PYTHONPATH=src python scripts/generate_pilot_evidence.py --output-dir docs/examples/pilot_evidence_sample --clean

pilot-integration-pack:
	PYTHONPATH=src python scripts/generate_integration_pilot_pack.py --output-dir docs/examples/pilot_integration_pack --clean

demo-k8s:
	@mkdir -p examples/k8s_admission_demo/artifacts/audit
	@touch examples/k8s_admission_demo/artifacts/audit/demo_audit.jsonl
	@SENA_POLICY_DIR=examples/k8s_admission_demo/policies \
	SENA_BUNDLE_NAME=k8s-admission-demo \
	SENA_BUNDLE_VERSION=2026.04 \
	SENA_AUDIT_SINK_JSONL=examples/k8s_admission_demo/artifacts/audit/demo_audit.jsonl \
	python -m uvicorn sena.api.app:app --host 127.0.0.1 --port 8000 >/tmp/sena-k8s-demo-api.log 2>&1 & \
	API_PID=$$!; \
	trap 'kill $$API_PID 2>/dev/null || true' EXIT INT TERM; \
	sleep 2; \
	PYTHONPATH=src python examples/k8s_admission_demo/verify_demo.py; \
	STATUS=$$?; \
	kill $$API_PID 2>/dev/null || true; \
	wait $$API_PID 2>/dev/null || true; \
	exit $$STATUS

demo-monitoring:
	@mkdir -p monitoring/artifacts
	@touch monitoring/artifacts/demo_audit.jsonl
	docker compose -f docker-compose-monitoring.yml up --build -d
	PYTHONPATH=src python scripts/generate_traffic.py --base-url http://127.0.0.1:8000


integration-matrix-check:
	PYTHONPATH=src python scripts/generate_integration_confidence_matrix.py --check
