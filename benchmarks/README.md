# Comparative benchmark harness

`tasks.yaml` is the machine-check inventory for the twenty declared reference
tasks. A run manifest embeds those tasks and combines them with the shape shown
in `systems.example.yaml`, providing at least pinned Haykal and Agent Device
command adapters. Each adapter receives one task as JSON on
stdin and returns machine-measured result JSON on stdout.

Run manifests reject floating versions such as `latest`, `main`, or `HEAD`.
Production reports use 30 clean starts per task. The harness writes immutable
manifest JSON, one CSV row per run, and a summary with median, p95, and Wilson
95% intervals. Step-caller and compiled-skill tracks remain separate fields and
must not be merged into one leaderboard.

Maestro MCP and ARTEMIS are omitted until M0 records an exact, reproducible
configuration. This is a published omission, not a zero score.
