#!/usr/bin/env python3
"""Validate and evaluate the production acceptance manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from haykal.production import evaluate_production_manifest, load_production_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="validate the contract without claiming production eligibility",
    )
    args = parser.parse_args()
    manifest = load_production_manifest(args.manifest)
    evaluation = evaluate_production_manifest(manifest)
    print(json.dumps(evaluation.model_dump(mode="json"), indent=2, sort_keys=True))
    if not evaluation.production_eligible and not args.allow_pending:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
