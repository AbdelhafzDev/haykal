"""Command-line entry point for reproducible M0 checks."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from .checks import build_report
from .device_smoke import run_device_smoke
from .inventory import build_inventory


def _write_report(report: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="haykal-m0")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="audit host, Android, and pinned dependency state")
    doctor.add_argument("--output", type=Path)
    inventory = commands.add_parser(
        "inventory", help="record package versions and license metadata"
    )
    inventory.add_argument("--project-root", type=Path, default=Path.cwd())
    inventory.add_argument("--output", type=Path)
    device = commands.add_parser("device-smoke", help="capture live UIAutomator2 evidence")
    device.add_argument("--serial", required=True)
    device.add_argument("--artifact-root", type=Path, default=Path("reports/m0/artifacts"))
    device.add_argument("--timeout-s", type=float, default=15.0)
    device.add_argument("--output", type=Path)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "doctor":
        _write_report(build_report(), args.output)
        return 0
    if args.command == "inventory":
        _write_report(build_inventory(args.project_root), args.output)
        return 0
    if args.command == "device-smoke":
        report = asyncio.run(
            run_device_smoke(
                serial=args.serial,
                artifact_root=args.artifact_root,
                timeout_s=args.timeout_s,
            )
        )
        _write_report(report, args.output)
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
