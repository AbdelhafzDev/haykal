#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
output="${1:?Pass an empty evidence output directory}"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"
if [[ -e "$output" ]]; then
  echo "evidence output already exists: $output" >&2
  exit 2
fi

cd "$project_dir"
ANDROID_HOME="$ANDROID_SDK_ROOT" \
  ./refapps/matjar/gradlew -p refapps/matjar assembleDebug >/dev/null
mkdir -p "$output"
uv run python - "$project_dir" "$output" <<'PY'
import sys
from pathlib import Path

import yaml

from haykal.benchmarks import BenchmarkTask, canonical_sha256, sha256_file

project = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
python = Path(sys.executable).resolve()
fixtures = project / "benchmarks/fixtures"
state_file = output / "independent-state.json"

def pin(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}

executable = pin(python)
oracle_adapter = pin(fixtures / "file_oracle.py")
model = pin(fixtures / "model.fixture")
prompt = pin(fixtures / "prompt.txt")
task = {
    "id": 10,
    "app": "matjar",
    "task": "Set independently observed offers state",
    "stresses": ["adversarial_adapter", "oracle"],
    "success_check": {"state": "offers", "equals": True},
}
task_model = BenchmarkTask.model_validate(task)
systems = []
for name, adapter_name in (("haykal", "truthful_adapter.py"), ("agent-device", "lying_adapter.py")):
    adapter = pin(fixtures / adapter_name)
    options = {"state_file": str(state_file)}
    configuration = {
        "name": name,
        "track": "step-caller",
        "options": options,
        "secret_env": [],
    }
    systems.append(
        {
            "name": name,
            "track": "step-caller",
            "version": adapter["sha256"],
            "command": [str(python), adapter["path"]],
            "executable": executable,
            "adapter": adapter,
            "model": model,
            "prompt": prompt,
            "configuration_sha256": canonical_sha256(configuration),
            "options": options,
        }
    )
oracle_options = {"state_file": str(state_file)}
manifest = {
    "schema_version": "2.0",
    "runs": 30,
    "random_seed": 95,
    "task_suite_sha256": canonical_sha256([task_model.model_dump(mode="json")]),
    "reference_apk": pin(project / "refapps/matjar/app/build/outputs/apk/debug/app-debug.apk"),
    "device_image": pin(fixtures / "device-image.fixture"),
    "oracle": {
        "command": [str(python), oracle_adapter["path"]],
        "executable": executable,
        "adapter": oracle_adapter,
        "configuration_sha256": canonical_sha256(
            {"options": oracle_options, "secret_env": []}
        ),
        "options": oracle_options,
    },
    "tasks": [task],
    "systems": systems,
}
(output / "run-manifest.yaml").write_text(
    yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
)
PY

uv run haykal benchmark --manifest "$output/run-manifest.yaml" --out "$output/report" >/dev/null
uv run haykal benchmark-rebuild --report "$output/report" --out "$output/rebuilt" >/dev/null
uv run python - "$output" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
summary = json.loads((root / "report/summary.json").read_text())
rates = {item["system"]: item["success_rate"] for item in summary}
assert rates == {"haykal": 1.0, "agent-device": 0.0}
assert (root / "report/derived-manifest.json").read_bytes() == (
    root / "rebuilt/derived-manifest.json"
).read_bytes()
raw = [json.loads(path.read_text()) for path in (root / "report/raw").glob("*.json")]
assert len(raw) == 60
assert all(item["result"]["adapter_claimed_success"] is True for item in raw)
assert all(
    item["result"]["success"] is False
    for item in raw
    if item["result"]["system"] == "agent-device"
)
print("P95.3 independent-oracle adversarial evidence passed")
PY
