"""Device boundary, leases, and safety primitives."""

from .backend import DeviceBackend, DeviceHealth, DeviceSnapshot, Uiautomator2Backend
from .lease import DeviceLease, DeviceLeaseStore, LeaseConflict, LeaseLost
from .settings import DeviceStateJournal, DeviceStateRecoveryError
from .single_shot import AtMostOnceDispatcher, DispatchOutcome, IdempotencyConflict

__all__ = [
    "AtMostOnceDispatcher",
    "DeviceBackend",
    "DeviceHealth",
    "DeviceLease",
    "DeviceLeaseStore",
    "DeviceSnapshot",
    "DeviceStateJournal",
    "DeviceStateRecoveryError",
    "DispatchOutcome",
    "IdempotencyConflict",
    "LeaseConflict",
    "LeaseLost",
    "Uiautomator2Backend",
]
