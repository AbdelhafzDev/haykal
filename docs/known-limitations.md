# Known limitations

- Android emulators and controlled VMs only. Physical devices, iOS, remote device
  farms, multi-tenancy, and enterprise SSO are outside the MVP.
- UIAutomator2 is the only execution backend. It requires its on-device service
  and has an exclusive UiAutomation connection, so Espresso, Appium, or Maestro
  cannot control the same device concurrently.
- OCR and vision adapters exist, but no production OCR/vision model and weights
  are selected until licensing and the labelled Arabic benchmark pass. Sparse
  Flutter/image-only tasks therefore remain release blockers.
- Secure fields and card-data entry are unsupported. Arabic input is supported
  only on validated non-secure field classes.
- ADB, device identity, login persistence, OTP provisioning, and emulator
  acceptance remain the deployment operator's responsibility.
- HTTP is not a TLS server. Remote binding requires explicit acknowledgement and
  an external authenticated TLS proxy.
- Approval authority is service-level, not enterprise identity-aware. Caller and
  approver credentials must be provisioned separately.
- Trace retention deletes by age. It does not yet calculate cross-trace artifact
  reachability; artifact age must be at least as long as trace age.
- Backup archives are integrity-checked but not encrypted. Encrypt them with the
  deployment's storage/KMS controls.
- Candidate patches are diagnostic records only; there is no automatic learning
  or promotion.
- Maestro is compatibility-import scope for a later milestone, not an executor.
- The comparative Agent Device run, two authorized regional-app runs, eight-hour
  device soak, and non-core authoring exercise have not been completed. No release
  reliability claim should be made until their reports exist.
