#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
report_dir="$project_dir/reports/m5"

"$project_dir/scripts/phase4-reference-check.sh"
mkdir -p "$report_dir"

database="$(find "$project_dir/reports/m4/state" -name runtime.sqlite3 -type f -print | sort | tail -n 1)"
if [[ -z "$database" ]]; then
  echo "No Phase 4 trace database found" >&2
  exit 2
fi
run_root="$(dirname "$database")"
trace_id="$(uv run python - "$database" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    row = connection.execute(
        "SELECT trace_id FROM trace_event ORDER BY rowid LIMIT 1"
    ).fetchone()
if row is None:
    raise SystemExit("trace database is empty")
print(row[0])
PY
)"

rm -rf -- "$report_dir/trace-example"
uv run haykal --state-dir "$run_root" trace-export "$trace_id" \
  --output "$report_dir/trace-example" >/dev/null

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
uv run haykal --state-dir "$run_root" backup --output "$temporary/state.tar.gz" >/dev/null
uv run haykal restore "$temporary/state.tar.gz" --destination "$temporary/restored" >/dev/null
uv run haykal --state-dir "$temporary/restored" diagnostics >/dev/null

test -s "$report_dir/trace-example/index.html"
test -s "$report_dir/trace-example/trace.json"
echo "Phase 5 reference acceptance passed: Phase 4 lifecycle, static trace, backup, restore"
