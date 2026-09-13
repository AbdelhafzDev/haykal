# Matjar

Package: `dev.haykal.refapps.matjar`

Matjar is the deterministic Arabic/English storefront described by the reference
manifest. It will combine View, Compose, and embedded WebView screens in one APK,
use an in-memory/fixed-seed catalogue, and persist fake orders locally so submit
reconciliation can be tested after a simulated crash.

Required properties:

- No network access or network permission.
- No real payment integration, credentials, or user data.
- Reset to a named seed through `dev.haykal.refapp.RESET`.
- Fault toggles through `dev.haykal.refapp.SET_FAULT`.
- Machine-readable state through a debug-only content provider used by benchmark
  assertions, never through a model's interpretation.
- Fake payment display only; no credential or card entry surface.
