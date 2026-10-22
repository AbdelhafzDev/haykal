#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$project_dir"

uv sync --extra dev --locked
uv run haykal-schema --output schemas/v1
uv run ruff check .
uv run mypy
uv run pytest --cov=haykal --cov-report=term-missing
