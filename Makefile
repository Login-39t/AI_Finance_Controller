PY := ./.venv/Scripts/python.exe

.PHONY: install test api web build lint migrate

install:
	python -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m pip install -e backend
	npm install --prefix frontend

# Backend on :8000. PYTHONPATH covers the app and the framework-free domain package.
api:
	PYTHONPATH="backend/src;packages/domain" $(PY) -m uvicorn ledgergraph_api.main:app --reload --port 8000

# Frontend on :3000.
web:
	npm run dev --prefix frontend

test:
	$(PY) -m pytest

build:
	npm run build --prefix frontend

lint:
	$(PY) -m ruff check backend packages tests

# Applies db/schema.sql through alembic. Needs a reachable Postgres.
migrate:
	cd backend && ../.venv/Scripts/python.exe -m alembic upgrade head
