from __future__ import annotations

import json
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from haykal.m0 import checks, cli


def test_real_report_is_structured_and_audits_pinned_uiautomator2() -> None:
    report = checks.build_report()
    by_name = {check["name"]: check for check in report["checks"]}

    assert report["schema_version"] == "1.0"
    assert report["phase"] == "M0"
    assert by_name["python"]["status"] == "passed"
    assert by_name["uiautomator2"]["status"] == "passed"
    assert by_name["uiautomator2_retry_audit"]["status"] in {
        "risk_confirmed",
        "review_required",
    }


def test_cli_writes_the_report(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    report = {"schema_version": "1.0", "phase": "M0", "checks": [], "summary": {}}
    monkeypatch.setattr(cli, "build_report", lambda: report)
    destination = tmp_path / "doctor.json"

    assert cli.main(["doctor", "--output", str(destination)]) == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert '"phase": "M0"' in capsys.readouterr().out
