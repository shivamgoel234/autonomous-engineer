#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
.venv/bin/python -m pip install -e backend --no-deps
(cd frontend && npm ci)
printf 'Setup complete. Follow README.md to configure tokens and start both servers.\n'
