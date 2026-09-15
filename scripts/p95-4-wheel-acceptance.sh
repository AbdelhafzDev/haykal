#!/usr/bin/env bash
set -euo pipefail

bundle="${1:?Pass the release bundle directory}"
evidence="${2:?Pass a new evidence directory}"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"
serial="${ANDROID_SERIAL:-emulator-5554}"
adb="$ANDROID_SDK_ROOT/platform-tools/adb"
expected_api="${P95_API_LEVEL:-}"
uv_bin="${HAYKAL_UV_BIN:-$(command -v uv)}"
if [[ -z "$uv_bin" ]]; then
  echo "uv is required as the wheel installer" >&2
  exit 2
fi

bundle="$(cd "$bundle" && pwd)"
if [[ -e "$evidence" ]]; then
  echo "evidence output already exists: $evidence" >&2
  exit 2
fi
mkdir -p "$evidence/logs" "$evidence/reports"
evidence="$(cd "$evidence" && pwd)"
temporary="$(mktemp -d)"
trap '"$adb" -s "$serial" logcat -d >"$evidence/logs/logcat.txt" 2>&1 || true; rm -rf -- "$temporary"' EXIT

(cd "$bundle" && shasum -a 256 -c SHA256SUMS) >"$evidence/logs/bundle-integrity.txt"
current_wheel="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["current"]["wheel"])' "$bundle/build-manifest.json")"
previous_wheel="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["previous"]["wheel"])' "$bundle/build-manifest.json")"

cd "$temporary"
python3 -m venv wheel-env
venv="$temporary/wheel-env"
"$uv_bin" pip install --python "$venv/bin/python" "$bundle/$previous_wheel" \
  >"$evidence/logs/install-previous.txt" 2>&1
"$venv/bin/python" -m pip show haykal-runtime >"$evidence/reports/package-previous.txt"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$temporary/upgrade-state" \
  hardening-run --duration-s 0.2 --workers 1 --chaos-every 1000 \
  --output "$evidence/reports/previous-state-run.json" \
  --output-state "$temporary/upgrade-state" >"$evidence/logs/previous-state-run.txt"

"$uv_bin" pip install --python "$venv/bin/python" --upgrade \
  --reinstall-package haykal-runtime "$bundle/$current_wheel" \
  >"$evidence/logs/install-current.txt" 2>&1
"$venv/bin/python" -m pip check >"$evidence/reports/pip-check.txt"
"$venv/bin/python" -m pip freeze --all >"$evidence/reports/packages.txt"
"$venv/bin/python" -m pip show haykal-runtime >"$evidence/reports/package-current.txt"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$temporary/upgrade-state" \
  diagnostics --storage-only >"$evidence/reports/upgrade-diagnostics.json"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/python" - "$bundle" "$temporary" \
  >"$evidence/reports/import-provenance.json" <<'PY'
import importlib.metadata
import json
import os
import sys
from pathlib import Path

import haykal

bundle, work = map(lambda value: Path(value).resolve(), sys.argv[1:])
module = Path(haykal.__file__).resolve()
prefix = Path(sys.prefix).resolve()
if prefix not in module.parents:
    raise SystemExit(f"haykal import escaped the wheel venv: {module}")
if bundle in module.parents or work == module or os.environ.get("PYTHONPATH"):
    raise SystemExit("source or bundle path contaminated the wheel import")
print(json.dumps({
    "cwd": str(Path.cwd()),
    "executable": str(Path(sys.executable).resolve()),
    "haykal_module": str(module),
    "distribution_version": importlib.metadata.version("haykal-runtime"),
    "pythonpath": os.environ.get("PYTHONPATH", ""),
    "source_checkout_imported": False,
}, indent=2, sort_keys=True))
PY

"$adb" -s "$serial" wait-for-device
actual_api="$("$adb" -s "$serial" shell getprop ro.build.version.sdk | tr -d '\r')"
if [[ -n "$expected_api" && "$actual_api" != "$expected_api" ]]; then
  echo "expected API $expected_api but device reports API $actual_api" >&2
  exit 2
fi
"$adb" -s "$serial" shell getprop >"$evidence/reports/device-properties.txt"
"$adb" -s "$serial" shell pm list packages -3 >"$evidence/reports/device-packages-before.txt"
"$adb" -s "$serial" install -r "$bundle/matjar-debug.apk" >"$evidence/logs/install-matjar.txt"
"$adb" -s "$serial" shell pm list packages -3 >"$evidence/reports/device-packages-after.txt"

reset_app() {
  local fault="${1:-}"
  "$adb" -s "$serial" shell am broadcast \
    -a dev.haykal.refapp.RESET -p dev.haykal.refapps.matjar >/dev/null
  if [[ -n "$fault" ]]; then
    "$adb" -s "$serial" shell am broadcast \
      -a dev.haykal.refapp.SET_FAULT -p dev.haykal.refapps.matjar \
      --es name "$fault" --ez enabled true >/dev/null
  fi
  "$adb" -s "$serial" shell am force-stop dev.haykal.refapps.matjar
  "$adb" -s "$serial" shell am start -W \
    -n dev.haykal.refapps.matjar/.MainActivity >/dev/null
}

reset_app
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal-m3" action-smoke \
  --serial "$serial" --state-dir "$temporary/primitive-state" \
  --output "$evidence/reports/primitive-action.json" >"$evidence/logs/primitive-action.txt"

reset_app
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/python" "$bundle/transport-smoke.py" \
  --serial "$serial" --adb "$adb" --state-dir "$temporary/transport-state" \
  --output "$evidence/reports/transports.json"

run_skill() {
  local skill="$1" output="$2" fault="${3:-}" mode="${4:-}"
  local inputs='{"query":"بيتزا","maximum_total":{"amount":60,"currency":"SAR"}}'
  if [[ "$skill" == "offers" ]]; then inputs='{"query":"بيتزا"}'; fi
  reset_app "$fault"
  args=(
    --serial "$serial"
    --skill "$bundle/skills/$skill.yaml"
    --state-dir "$temporary/skill-state"
    --inputs "$inputs"
    --output "$evidence/reports/$output.json"
  )
  if [[ "$mode" == "approve" ]]; then args+=(--approve-gate); fi
  if [[ "$mode" == "stale" ]]; then args+=(--approve-gate --stale-gate); fi
  HAYKAL_ADB_PATH="$adb" PYTHONPATH= PYTHONNOUSERSITE=1 \
    "$venv/bin/haykal-m4" "${args[@]}" >"$evidence/logs/$output.txt"
}

run_skill offers offers
run_skill prepare-order approval-stop
run_skill prepare-order stale-approval '' stale
run_skill prepare-order submit-timeout submit_timeout approve

database="$(find "$temporary/skill-state" -name runtime.sqlite3 -type f -print | sort | head -n 1)"
trace_id="$("$venv/bin/python" - "$database" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as connection:
    row = connection.execute("SELECT trace_id FROM trace_event ORDER BY rowid LIMIT 1").fetchone()
if row is None: raise SystemExit("trace database is empty")
print(row[0])
PY
)"
run_root="$(dirname "$database")"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$run_root" \
  trace-export "$trace_id" --output "$evidence/reports/static-trace" \
  >"$evidence/reports/trace-export.json"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$run_root" \
  retention --trace-days 7 --artifact-days 7 >"$evidence/reports/retention-preview.json"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$run_root" \
  backup --output "$evidence/reports/state-backup.tar.gz" >"$evidence/reports/backup.json"
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" restore \
  "$evidence/reports/state-backup.tar.gz" --destination "$temporary/restored-state" \
  >"$evidence/reports/restore.json"

PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$temporary/restored-state" \
  diagnostics --device "$serial" --adb-path "$adb" >"$evidence/reports/readiness-connected.json"
if PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$temporary/restored-state" \
  diagnostics --device "$serial-absent" --adb-path "$adb" \
  >"$evidence/reports/readiness-absent.json"; then
  echo "missing device unexpectedly reported ready" >&2
  exit 2
fi
PYTHONPATH= PYTHONNOUSERSITE=1 "$venv/bin/haykal" --state-dir "$temporary/restored-state" \
  diagnostics --device "$serial" --adb-path "$adb" >"$evidence/reports/readiness-recovered.json"

"$venv/bin/python" - "$bundle/build-manifest.json" "$evidence" "$actual_api" "$serial" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

build_path, root_arg, api, serial = sys.argv[1:]
root = Path(root_arg)
build = json.loads(Path(build_path).read_text())
read = lambda name: json.loads((root / "reports" / name).read_text())
offers = read("offers.json")
approval = read("approval-stop.json")
stale = read("stale-approval.json")
timeout = read("submit-timeout.json")
primitive = read("primitive-action.json")
transports = read("transports.json")
upgrade = read("upgrade-diagnostics.json")
connected = read("readiness-connected.json")
absent = read("readiness-absent.json")
recovered = read("readiness-recovered.json")
provenance = read("import-provenance.json")
retention = read("retention-preview.json")
assert offers["status"] == "completed" and len(offers["outputs"]["offers"]) == 10
assert approval["status"] == "approval_required"
assert stale["status"] == "approval_required" and stale["pending"]["reason"] == "approval_stale"
assert timeout["status"] == "completed_reconciled"
assert primitive["status"] == "passed"
assert transports["http"]["readiness"] == "ready" and transports["mcp"]["scene_id"]
assert upgrade["status"] in {"ready", "degraded"}
assert connected["status"] == "ready" and recovered["status"] == "ready"
assert absent["status"] == "unhealthy"
assert provenance["source_checkout_imported"] is False
assert build["current"]["worktree_dirty_at_build"] is False
assert retention["dry_run"] is True
assert (root / "reports/static-trace/index.html").is_file()
assert (root / "reports/static-trace/trace.json").is_file()
fingerprint = next(
    line.strip() for line in (root / "reports/device-properties.txt").read_text().splitlines()
    if line.startswith("[ro.build.fingerprint]")
)
manifest = {
    "schema_version": "1.0",
    "status": "passed",
    "release": {
        "version": build["current"]["version"],
        "commit": build["current"]["commit"],
        "wheel_sha256": build["current"]["sha256"],
        "apk_sha256": build["matjar"]["sha256"],
        "previous_version": build["previous"]["version"],
        "previous_wheel_sha256": build["previous"]["sha256"],
    },
    "device": {"serial": serial, "api_level": int(api), "vm_identity": fingerprint},
    "isolation": provenance,
    "checks": {
        "upgrade_and_schema": "passed",
        "primitive_action": "passed",
        "http": "passed",
        "mcp": "passed",
        "arabic_input_and_offers": "passed",
        "approval_stop": "passed",
        "stale_approval": "passed",
        "submit_timeout_reconciliation": "passed",
        "trace_export": "passed",
        "retention_preview": "passed",
        "backup_restore": "passed",
        "device_readiness_transition": "passed",
    },
}
output = root / "acceptance-manifest.json"
output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
(root / "evidence-sha256.txt").write_text(
    "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n"
        for path in sorted(root.rglob("*")) if path.is_file() and path.name != "evidence-sha256.txt"
    )
)
PY

echo "P95.4 wheel-only acceptance passed on Android API $actual_api: $evidence"
