#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

"$project_dir/scripts/matjar-check.sh"
"$project_dir/scripts/flutter-sparse-check.sh"
