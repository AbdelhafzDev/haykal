from __future__ import annotations

from pathlib import Path

import pytest

from haykal.device.lease import DeviceLeaseStore
from haykal.device.settings import (
    DeviceStateConflict,
    DeviceStateJournal,
    DeviceStateRecoveryError,
)


def test_new_lease_recovers_state_abandoned_by_crashed_owner(tmp_path: Path) -> None:
    database = tmp_path / "device.db"
    leases = DeviceLeaseStore(database)
    journal = DeviceStateJournal(database)
    crashed = leases.acquire("vm-1", "worker-a", ttl_s=5, now=100)
    journal.record_baseline(crashed, "default_input_method", "original/.Ime")

    replacement = leases.acquire("vm-1", "worker-b", ttl_s=10, now=106)
    restored: list[tuple[str, str]] = []
    assert (
        journal.recover_prior(
            replacement,
            lambda setting: restored.append((setting.key, setting.original_value)),
        )
        == 1
    )
    assert restored == [("default_input_method", "original/.Ime")]
    assert journal.pending_before(replacement) == []


def test_failed_recovery_remains_pending_for_next_attempt(tmp_path: Path) -> None:
    database = tmp_path / "device.db"
    leases = DeviceLeaseStore(database)
    journal = DeviceStateJournal(database)
    crashed = leases.acquire("vm-1", "worker-a", ttl_s=5, now=100)
    journal.record_baseline(crashed, "default_input_method", "original/.Ime")
    replacement = leases.acquire("vm-1", "worker-b", ttl_s=10, now=106)

    def fail(_setting: object) -> None:
        raise RuntimeError("device unavailable")

    with pytest.raises(DeviceStateRecoveryError):
        journal.recover_prior(replacement, fail)
    assert len(journal.pending_before(replacement)) == 1


def test_baseline_is_immutable_within_a_generation(tmp_path: Path) -> None:
    database = tmp_path / "device.db"
    leases = DeviceLeaseStore(database)
    journal = DeviceStateJournal(database)
    lease = leases.acquire("vm-1", "worker-a", ttl_s=5, now=100)
    journal.record_baseline(lease, "default_input_method", "original/.Ime")

    with pytest.raises(DeviceStateConflict):
        journal.record_baseline(lease, "default_input_method", "other/.Ime")
