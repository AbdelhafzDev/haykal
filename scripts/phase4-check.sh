#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$project_dir"

uv sync --all-extras --locked
uv run haykal-schema --output schemas/v1
uv run ruff format --check src tests
uv run ruff check .
uv run mypy
uv run pytest --cov=haykal --cov-report=term-missing
uv run haykal lint skills/dev.haykal.refapps.matjar/offers.yaml >/dev/null
uv run haykal lint skills/dev.haykal.refapps.matjar/prepare-order.yaml >/dev/null
uv build
