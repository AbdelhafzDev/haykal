#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
duration_s="${HAYKAL_SOAK_DURATION_S:-28800}"
started="$(date +%s)"
deadline="$((started + duration_s))"
cycles=0

while [[ "$(date +%s)" -lt "$deadline" ]]; do
  "$project_dir/scripts/phase4-reference-check.sh" >/dev/null
  cycles="$((cycles + 1))"
done

ended="$(date +%s)"
mkdir -p "$project_dir/reports/m5"
uv run python - "$project_dir/reports/m5/device-soak.json" \
  "$started" "$ended" "$duration_s" "$cycles" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

output, started, ended, requested, cycles = sys.argv[1:]
payload = {
    "schema_version": "1.0",
    "profile": "phase4-reference-device-soak",
    "started_at": datetime.fromtimestamp(int(started), UTC).isoformat(),
    "ended_at": datetime.fromtimestamp(int(ended), UTC).isoformat(),
    "requested_duration_s": int(requested),
    "elapsed_s": int(ended) - int(started),
    "completed_cycles": int(cycles),
    "failures": 0,
    "eight_hour_gate_eligible": int(requested) >= 28800 and int(ended) - int(started) >= 28800,
}
Path(output).write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload))
PY
