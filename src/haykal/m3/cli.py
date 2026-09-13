"""Phase 3 live evidence CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .action_smoke import run_action_smoke


def main() -> None:
    parser = argparse.ArgumentParser(prog="haykal-m3")
    commands = parser.add_subparsers(dest="command", required=True)
    action = commands.add_parser("action-smoke")
    action.add_argument("--serial", default="emulator-5554")
    action.add_argument("--state-dir", type=Path)
    action.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(
        run_action_smoke(serial=arguments.serial, state_directory=arguments.state_dir)
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
