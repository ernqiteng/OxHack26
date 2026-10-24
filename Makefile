.PHONY: setup test test-db test-live lint db dashboard

setup:            ## create venv and install everything
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "now edit .env"

test:             ## unit + contract tests, no network, no DB
	.venv/bin/pytest tests/unit tests/contracts

test-db:          ## tests that need the local Docker TimescaleDB
	./scripts/dev_db.sh
	.venv/bin/pytest tests/db

test-live:        ## tests that hit real Tiger / Vultr / Elexon (costs money)
	TEMPO_LIVE=1 .venv/bin/pytest tests/live -m live

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

db:               ## start local DB and apply schema
	./scripts/dev_db.sh

dashboard:
	.venv/bin/streamlit run tempo/dashboard/app.py
