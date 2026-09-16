#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
output="${1:?Pass a new bundle directory}"
output="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$output")"
if [[ -e "$output" ]]; then
  echo "bundle output already exists: $output" >&2
  exit 2
fi
if [[ -n "$(git -C "$project_dir" status --porcelain --untracked-files=all)" ]]; then
  echo "release bundles must be built from a completely clean Git worktree" >&2
  exit 2
fi

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
mkdir -p "$temporary/current" "$temporary/current-source" \
  "$temporary/previous" "$temporary/previous-source"
current_commit="$(git -C "$project_dir" rev-parse HEAD^{commit})"
current_tree="$(git -C "$project_dir" rev-parse HEAD^{tree})"
git -C "$project_dir" archive "$current_commit" | tar -x -C "$temporary/current-source"

current_version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' \
  "$temporary/current-source/pyproject.toml" | head -n 1)"
previous_ref="${HAYKAL_PREVIOUS_REF:-}"
if [[ -z "$previous_ref" ]]; then
  while IFS= read -r candidate; do
    candidate_version="$(git -C "$project_dir" show "$candidate:pyproject.toml" \
      | sed -n 's/^version = "\([^"]*\)"/\1/p' | head -n 1)"
    if [[ -n "$candidate_version" && "$candidate_version" != "$current_version" ]]; then
      previous_ref="$candidate"
      break
    fi
  done < <(git -C "$project_dir" log --format=%H -- pyproject.toml)
fi
if [[ -z "$previous_ref" ]]; then
  echo "could not find an earlier package version; set HAYKAL_PREVIOUS_REF" >&2
  exit 2
fi
previous_commit="$(git -C "$project_dir" rev-parse "$previous_ref^{commit}")"
previous_version="$(git -C "$project_dir" show "$previous_commit:pyproject.toml" \
  | sed -n 's/^version = "\([^"]*\)"/\1/p' | head -n 1)"

(cd "$temporary/current-source" && uv build --wheel --out-dir "$temporary/current" >/dev/null)
git -C "$project_dir" archive "$previous_commit" | tar -x -C "$temporary/previous-source"
(cd "$temporary/previous-source" && uv build --wheel --out-dir "$temporary/previous" >/dev/null)
ANDROID_HOME="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}" \
  "$temporary/current-source/refapps/matjar/gradlew" \
  -p "$temporary/current-source/refapps/matjar" assembleDebug >/dev/null

mkdir -p "$output/wheels" "$output/skills"
cp "$temporary/current"/*.whl "$output/wheels/"
cp "$temporary/previous"/*.whl "$output/wheels/"
cp "$temporary/current-source/refapps/matjar/app/build/outputs/apk/debug/app-debug.apk" \
  "$output/matjar-debug.apk"
cp "$temporary/current-source/skills/dev.haykal.refapps.matjar/offers.yaml" "$output/skills/"
cp "$temporary/current-source/skills/dev.haykal.refapps.matjar/prepare-order.yaml" \
  "$output/skills/"
cp "$temporary/current-source/scripts/p95-4-transport-smoke.py" "$output/transport-smoke.py"

current_wheel="$(basename "$(find "$temporary/current" -name '*.whl' -type f -print -quit)")"
previous_wheel="$(basename "$(find "$temporary/previous" -name '*.whl' -type f -print -quit)")"
python3 - "$output" "$current_wheel" "$previous_wheel" "$current_version" \
  "$previous_version" "$current_commit" "$previous_commit" "$current_tree" <<'PY'
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1]).resolve()
current_wheel, previous_wheel = sys.argv[2:4]

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

payload = {
    "schema_version": "1.0",
    "built_at": datetime.now(UTC).isoformat(),
    "current": {
        "version": sys.argv[4],
        "commit": sys.argv[6],
        "source_tree": sys.argv[8],
        "worktree_dirty_at_build": False,
        "wheel": f"wheels/{current_wheel}",
        "sha256": digest(root / "wheels" / current_wheel),
    },
    "previous": {
        "version": sys.argv[5],
        "commit": sys.argv[7],
        "wheel": f"wheels/{previous_wheel}",
        "sha256": digest(root / "wheels" / previous_wheel),
    },
    "matjar": {"path": "matjar-debug.apk", "sha256": digest(root / "matjar-debug.apk")},
}
(root / "build-manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
files = sorted(path for path in root.rglob("*") if path.is_file())
(root / "SHA256SUMS").write_text(
    "".join(f"{digest(path)}  {path.relative_to(root).as_posix()}\n" for path in files)
)
PY
echo "Built Haykal $current_version release bundle from one promoted wheel: $output"
