.PHONY: install install-dev test lint format quality api docker-up bump-version pilot-evidence pilot-integration-pack

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
