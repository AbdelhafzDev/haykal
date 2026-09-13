"""Phase 2 diagnostic CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .scene_smoke import run_scene_smoke


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="haykal-m2")
    commands = parser.add_subparsers(dest="command", required=True)
    scene = commands.add_parser("scene-smoke")
    scene.add_argument("--serial", default="emulator-5554")
    scene.add_argument("--artifact-root", type=Path, default=Path("reports/m2/artifacts"))
    scene.add_argument("--output", type=Path)
    scene.add_argument("--session-id", default="m2-smoke")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    report = asyncio.run(
        run_scene_smoke(
            serial=arguments.serial,
            artifact_root=arguments.artifact_root,
            session_id=arguments.session_id,
        )
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
