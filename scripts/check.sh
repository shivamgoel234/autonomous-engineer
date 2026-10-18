#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check --config backend/pyproject.toml backend sandbox scripts
.venv/bin/ruff format --check --config backend/pyproject.toml backend sandbox scripts
.venv/bin/python -m pytest backend/tests -q
(cd frontend && npm test && npm run build)
