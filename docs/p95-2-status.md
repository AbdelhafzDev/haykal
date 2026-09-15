# P95.2 status: real reliability and device readiness

Decision: **complete locally; overall release remains no-go**

P95.2 replaces the old synthetic interruption counter and storage-only health
claim. It does not claim the eight-hour P95.5 soak, hosted API 34/35 wheel matrix,
or external validation.

## Readiness model

- `/livez` reports only process/event-loop liveness.
- `/healthz` is the minimal compatibility aggregate.
- `/readyz` returns 200 only for a fully ready report and 503 for degraded or
  unhealthy states.
- Device readiness checks ADB response, exact target authorization, lease
  freshness/availability, UIAutomator2 responsiveness, pending device-setting
  recovery, private state access, SQLite integrity, artifact digests, and disk
  capacity.
- Missing device diagnostics fail closed. Offline maintenance must explicitly use
  `diagnostics --storage-only`; it cannot be confused with service readiness.
- Public endpoints expose counts only. Serial, path, lease generation, and failure
  details remain behind authenticated diagnostics.

## Actual fault matrix

The supervisor is a separate process and kills worker processes at the prepared,
dispatch-started, post-effect/pre-commit, and post-commit boundaries. It then
reconciles the durable single-shot ledger and independently counts external
effects. Additional cases interrupt a live SQLite transaction, corrupt an
artifact, kill lease and device-setting owners, impose an OS file-size limit on
artifact and trace writes, stop/restart the UIAutomator2 helper, reconnect the
configured ADB target, and change/restore the device IME.

No checkpoint produced more than one irreversible external effect. Prepared or
post-effect ambiguity reconciled as `outcome_unknown`; completed dispatch
reconciled as dispatched. SQLite remained valid with zero uncommitted rows,
artifact corruption was detected by `ArtifactStore.get`, replacement lease
generation recovered and released cleanly, pending IME state was recovered, and
disk pressure published neither an artifact nor a trace event.

## Development soak

The 30-minute profile runs four concurrent workers with real SQLite rollback and
artifact-corruption injection. A monitor samples RSS, open descriptors, file
count, artifact bytes, SQLite bytes, total state bytes, operation latency, and
recovery counts. Online trace retention creates a finite stabilization window;
the report evaluates the second-half state/RSS slopes against declared limits.

Final result: 1,804.65 seconds, 2,747,317 operations, 74,250 independently
injected and detected storage faults, zero unexpected or artifact-integrity
failures, 6.48 ms p95 latency, 84,377,600 peak RSS bytes, 19,419,216 final
state bytes, 19 peak open descriptors, -68.17 state bytes/second and 0 RSS
bytes/second after stabilization. All declared limits passed and
`thirty_minute_gate_eligible` is true. The saved SVG plots RSS, total state, and
SQLite bytes across all 356 samples.

## Evidence

| Gate | Result |
| --- | --- |
| Host process checkpoints | 4/4 passed; at most one external effect |
| SQLite interruption | passed; quick check `ok`, uncommitted row absent |
| Artifact corruption/truncation | passed; digest read rejected corruption |
| Lease owner process death | passed; generation advanced and replacement released |
| Settings/IME owner death | passed; pending baseline recovered |
| OS disk/file limit | passed; no artifact or trace event published |
| UIAutomator2 agent death | passed on API 37; helper restarted and responded |
| ADB disconnect/reconnect | passed on API 37; target returned to `device` |
| Device IME interruption | passed on API 37; exact prior IME restored |
| Connected/absent readiness | connected `ready`; absent target `unhealthy`, exit 2 |
| Phase 5 reference lifecycle | offers, approval stop, one-shot reconciliation, trace export, backup/restore passed on API 37 |
| Full host gate | 508 passed, 2 P95.3 xfailed; 84.62% coverage; Ruff, strict mypy over 97 source files, 21 schemas, build, wheel-only install, secret scan, dependency audit, and Actionlint passed |

Evidence identities:

- fault-matrix report SHA-256: `cf0b65d64259962252285a3a58efc3aff97f33c661904bd825671e03d42a99e1`
- 30-minute soak report SHA-256: `ed98ef096bcb3ee1e3ed7245edd5ac56b0526e732eaf16b91e95b558c10d6ac3`
- bounded-growth SVG SHA-256: `671c433b64cea5827218dfdbd4e3720c9189ef420cfc3dfb7440b849e78ff976`
- wheel SHA-256: `bf60a912d992df05f4f284cebd18bcf11c6f8e9f05fee2cc10f9acc643e4a933`
- Matjar APK SHA-256: `22296d98d427ff5e1903319bea4e181c74848c58cd4ccedad732e34ce332132d`
- implementation commit: `b89045f5d0a748021d43b6deebbc2503195672b5`

Reproduction:

```sh
./scripts/phase5-check.sh
ANDROID_SDK_ROOT=/opt/android-sdk ANDROID_SERIAL=emulator-5554 \
  ./scripts/p95-2-device-check.sh /empty/p95-2-device-evidence
haykal hardening-run --duration-s 1800 --workers 4 --chaos-every 37 \
  --output /evidence/soak.json --output-state /empty/soak-state
```

The P95.0 hosted fresh-checkout evidence is still unavailable because this
repository has no configured remote. If all evidence above remains green, the
honest overall score is **83/100 official**, or **85/100 conditional** on that
hosted baseline. P95.3 is next: independent Matjar oracle scoring and
cryptographic benchmark pinning.
