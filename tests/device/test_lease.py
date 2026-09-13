from __future__ import annotations

from pathlib import Path

import pytest

from haykal.device.lease import DeviceLeaseStore, LeaseConflict, LeaseLost


def test_live_lease_is_exclusive_and_heartbeat_extends_it(tmp_path: Path) -> None:
    store = DeviceLeaseStore(tmp_path / "leases.db")
    lease = store.acquire("vm-1", "worker-a", ttl_s=10, now=100)

    with pytest.raises(LeaseConflict):
        store.acquire("vm-1", "worker-b", ttl_s=10, now=105)

    extended = store.heartbeat(lease, ttl_s=20, now=105)
    assert extended.expires_at == 125
    store.release(extended)
    replacement = store.acquire("vm-1", "worker-b", ttl_s=10, now=106)
    assert replacement.generation == lease.generation + 1


def test_expired_lease_can_be_recovered_without_stale_owner_release(tmp_path: Path) -> None:
    store = DeviceLeaseStore(tmp_path / "leases.db")
    stale = store.acquire("vm-1", "worker-a", ttl_s=5, now=100)
    current = store.acquire("vm-1", "worker-b", ttl_s=10, now=106)

    assert current.generation == stale.generation + 1
    with pytest.raises(LeaseLost):
        store.release(stale)
    with pytest.raises(LeaseLost):
        store.heartbeat(stale, ttl_s=10, now=107)


def test_reap_expired_is_bounded_by_time(tmp_path: Path) -> None:
    store = DeviceLeaseStore(tmp_path / "leases.db")
    store.acquire("vm-1", "worker-a", ttl_s=5, now=100)
    store.acquire("vm-2", "worker-b", ttl_s=20, now=100)

    assert store.reap_expired(now=106) == 1
    assert store.reap_expired(now=106) == 0
