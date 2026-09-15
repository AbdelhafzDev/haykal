from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import haykal.m4.skill_smoke as skill_smoke
from haykal.m4.skill_smoke import _change_checkout_price


def _evidence(root: Path, api: int, digest: str, *, status: str = "passed") -> Path:
    root.mkdir()
    (root / "acceptance-manifest.json").write_text(
        json.dumps(
            {
                "status": status,
                "release": {"wheel_sha256": digest},
                "device": {"api_level": api, "vm_identity": f"fingerprint-{api}"},
            }
        )
    )
    return root


def test_matrix_attestation_requires_two_api_levels_and_one_wheel(tmp_path: Path) -> None:
    first = _evidence(tmp_path / "api-34", 34, "a" * 64)
    second = _evidence(tmp_path / "api-35", 35, "a" * 64)
    output = tmp_path / "attestation.json"
    script = Path(__file__).parents[2] / "scripts" / "p95-4-verify-matrix.py"

    subprocess.run(
        ["python3", str(script), str(first), str(second), "--output", str(output)],
        check=True,
    )

    assert json.loads(output.read_text())["api_levels"] == [34, 35]


def test_matrix_attestation_rejects_different_wheels(tmp_path: Path) -> None:
    first = _evidence(tmp_path / "api-34", 34, "a" * 64)
    second = _evidence(tmp_path / "api-35", 35, "b" * 64)
    script = Path(__file__).parents[2] / "scripts" / "p95-4-verify-matrix.py"

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(
            ["python3", str(script), str(first), str(second), "--output", str(tmp_path / "x")],
            check=True,
        )


def test_stale_gate_changes_material_and_restarts_reference_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setenv("HAYKAL_ADB_PATH", "/sdk/adb")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        skill_smoke,
        "connect",
        lambda _serial: (
            lambda **_selector: type("Visible", (), {"wait": lambda self, timeout: timeout == 30})()
        ),
    )
    _change_checkout_price("emulator-5554")

    assert len(commands) == 1
    assert "price_change" in commands[0]
