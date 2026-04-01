.PHONY: install install-dev test lint api docker-up bump-version

install:
	pip install -e .

install-dev:
	pip install -e .[api,dev]

test:
	pytest

lint:
	ruff check src tests
	mypy src

api:
	python -m uvicorn sena.api.app:app --reload

docker-up:
	docker compose up --build


bump-version:
	@test -n "$(VERSION)" || (echo "Usage: make bump-version VERSION=X.Y.Z" && exit 1)
	python scripts/bump_version.py $(VERSION)
