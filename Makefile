.PHONY: install install-dev test lint api docker-up

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
