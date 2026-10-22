"""CLI for the labelled OmniParser fallback acceptance gate."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import cast

from haykal.perception import PerceptionAdapter, build_omniparser_v2_adapter

from .fallback import evaluate_fallback_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the pinned fallback on saved labels")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    adapter = cast(
        PerceptionAdapter,
        build_omniparser_v2_adapter(
            cache_root=args.cache,
            manifest_path=args.manifest,
            device=args.device,
        ),
    )
    report = asyncio.run(evaluate_fallback_dataset(args.dataset, adapter))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
