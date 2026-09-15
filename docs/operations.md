# Installation, upgrade, backup, and recovery

## Supported deployment

The MVP is a single-host private runtime controlling one Android emulator or VM.
Use Python 3.11–3.13, a pinned Android SDK/VM image, and the wheel produced by
`uv build`. The state directory contains SQLite journals, signed skill objects,
and sensitive screen artifacts; create it on encrypted storage with mode `0700`.

## Clean installation

```bash
uv sync --all-extras --locked
./scripts/phase5-check.sh
uv build
python3 -m venv /opt/haykal/venv
/opt/haykal/venv/bin/pip install dist/haykal_runtime-0.0.1-py3-none-any.whl
HAYKAL_API_TOKEN="$(openssl rand -hex 32)" \
  /opt/haykal/venv/bin/haykal --state-dir /var/lib/haykal serve \
  --device-serial emulator-5554 --adb-path /opt/android-sdk/platform-tools/adb
```

Keep caller, approver, and approval-signing credentials distinct. Bind to
loopback. A non-loopback bind is refused unless the operator explicitly supplies
`--allow-remote-behind-tls`; that flag is an acknowledgement, not TLS itself.

## Upgrade

1. Stop accepting new sessions and allow current runs to reach a durable pause.
2. Run `haykal --state-dir STATE diagnostics --device SERIAL --adb-path ADB` and
   create a backup.
3. Install the new wheel in a new virtual environment; do not mutate the old one.
4. Run diagnostics and the shipped smoke checks against a restored copy.
5. Switch the service atomically. Keep the old environment and backup until the
   acceptance run completes.

Skill versions are immutable. Publish a new skill version rather than replacing
existing signed content. Database migrations must be forward-only and backed up
before the new binary opens production state.

## Backup

```bash
haykal --state-dir /var/lib/haykal backup --output /secure/haykal-2026-09-13.tar.gz
```

The command uses SQLite's online backup API, includes content-addressed artifacts
and signed skill objects, and writes a checksum manifest. Store archives encrypted
and apply the same retention policy as raw screenshots.

## Recovery drill

Restore never overwrites a populated directory:

```bash
haykal restore /secure/haykal-2026-09-13.tar.gz \
  --destination /var/lib/haykal-restored
haykal --state-dir /var/lib/haykal-restored diagnostics --storage-only
```

The restore rejects traversal links, devices, undeclared files, and digest
mismatches. Start a service only after diagnostics pass. Runs whose action was
prepared but not committed remain `outcome_unknown`; operators reconcile them and
must not manually replay the action.

## Retention and trace export

Retention previews by default and changes data only with `--apply`:

```bash
haykal --state-dir /var/lib/haykal retention --trace-days 7 --artifact-days 7
haykal --state-dir /var/lib/haykal retention --trace-days 7 --artifact-days 7 --apply
haykal --state-dir /var/lib/haykal trace-export TRACE_ID \
  --policy config/redaction.example.yaml --output /secure/exported-trace
```

Images are omitted by default. An opted-in image export applies every declared
pixel rectangle and writes a new digest; it never copies the raw image.
