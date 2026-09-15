from __future__ import annotations

import pytest

from haykal.hardening.faults import run_fault_matrix


def test_external_supervisor_fault_matrix_recovers_without_duplicate_effects(tmp_path) -> None:
    report = run_fault_matrix(tmp_path)
    observations = {item.fault: item for item in report.observations}

    assert report.passed
    assert len(observations) == 9
    assert observations["runtime_kill_prepared"].observation.startswith("effects=0")
    assert observations["runtime_kill_pre_commit"].observation.startswith("effects=1")
    assert observations["runtime_kill_post_commit"].observation.startswith("effects=1")
    assert "quick_check=ok" in observations["sqlite_interruption"].observation
    assert observations["artifact_corruption"].passed
    assert observations["lease_owner_death"].passed
    assert observations["ime_interruption"].passed
    assert observations["disk_full"].passed


def test_device_fault_matrix_requires_a_target_and_adb_together(tmp_path) -> None:
    with pytest.raises(ValueError, match="provided together"):
        run_fault_matrix(tmp_path, serial="emulator-5554")
