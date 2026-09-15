# P95.3 status: independently scored and cryptographically pinned benchmark

Decision: **complete locally; external competitor evidence remains no-go**

P95.3 replaces adapter-reported success and textual version labels with an
independent controller boundary. It does not claim that the deliberately
adversarial local fixture is Agent Device, nor does it claim the external P95.5
comparison.

## Scoring boundary

For every task, run, and system, the controller now:

1. asks a separately pinned oracle to reset the target;
2. records an independent pre-state snapshot;
3. runs the untrusted system adapter;
4. records an independent post-state snapshot;
5. evaluates the task success and safety checks centrally; and
6. preserves adapter `success` and `unsafe_actions` only as diagnostic claims.

Structured adapter output may be evaluated under the explicit `output.*`
namespace, but the adapter cannot set its published success or unsafe score. An
adapter crash, timeout, malformed response, oracle failure, or secret canary leak
fails closed.

Matjar persists benchmark-only machine state for screen, basket count, submit
count, and order creation. `haykal-matjar-oracle` reads it over ADB `run-as`, a
channel separate from UIAutomator2 execution. The API 37 transition evidence
reset Matjar to `screen=home`, tapped through UIAutomator2, and independently
observed `screen=search`; it then observed the reference order, exactly one
`submit_order` event, and exactly one submit counter after the controlled flow.

## Provenance and sealed evidence

- Full lowercase SHA-256 pins are mandatory for the launched executable, adapter,
  model, prompt, reference APK, device image identity, embedded task suite, and
  canonical system/oracle configuration.
- The executable and adapter paths in each command are matched to their pins and
  every file is hashed before the report directory is created.
- Secrets are named through `secret_env`, never stored in options or copied
  configuration. A secret appearing in stdout or stderr fails the run and is not
  published; the canary regression scans every report file.
- System order is deterministically randomized within every task/run pair.
- Raw runs, tasks, manifest, and configurations are hashed into an evidence
  manifest and changed to read-only. Missing, changed, or added raw files prevent
  reconstruction.
- `haykal benchmark-rebuild` verifies the sealed evidence and recreates CSV,
  JSON, Markdown, methodology, and the derived manifest without executing an
  adapter or trusting an existing summary.

## Local adversarial evidence

The P95.3 fixture ran 30 clean resets for each of two local adapters. The truthful
fixture changed external state and scored 30/30. The deliberately lying fixture
claimed success in all 30 runs, changed no external state, and scored 0/30. Both
execution orders occurred (17 liar-first, 13 truthful-first). Rebuilding only
from the 60 sealed raw runs produced the identical derived manifest.

This validates the controller, not competitor performance. Agent Device remains
an external P95.5 requirement.

## Evidence

| Gate | Result |
| --- | --- |
| Lying success claim | passed; claims 30/30, oracle score 0/30 |
| Independent unsafe scoring | passed; adapter claim cannot hide failed safety check |
| Cryptographic pin mismatch | passed; execution and evidence creation blocked |
| Raw mutation or added run | passed; reconstruction rejected |
| Secret canary | passed; run failed closed and canary absent from all report files |
| Deterministic rebuild | passed; derived manifest byte-identical |
| API 37 Matjar ADB oracle | passed; home-to-search transition observed independently |
| Full host gate | 520 passed, no xfails; 84.56% coverage; Ruff, strict mypy over 100 source files, 21 schemas, build, wheel-only install, secret scan, dependency audit, and Actionlint passed |

Evidence identities:

- sealed evidence manifest SHA-256: `c0cb91bbc1e7ebc3d29278e28da2987cc3e4c506552629415c146f6e53306cf8`
- derived manifest SHA-256: `fedaf9daa84268e17a020edc1cf30713950f568ef859b21bc7a1294780310725`
- API 37 oracle transition SHA-256: `547db250f293370a60233d76a313d0b9e5b34079602d8e316294aa86ef47a9b6`
- API 37 device properties SHA-256: `1bf5a283319240ca0b10aeb420f608a55676e7bb67c70d02aa761d5c7978ef12`
- Matjar APK SHA-256: `796ead46e5edfcca24a25e2c0b1d9787a2e9550158ebe5610fbba080feec521b`
- wheel SHA-256: `9132be7e50de198c2128eb657425317b206757b4ff7a4abc9481ce088b61de15`
- implementation commit: `89f2e359392eab17e005d8fc3cb34d3adc6977eb`

Reproduction:

```sh
ANDROID_SDK_ROOT=/opt/android-sdk \
  ./scripts/p95-3-local-evidence.sh /empty/local-adversarial-evidence
ANDROID_SDK_ROOT=/opt/android-sdk ANDROID_SERIAL=emulator-5554 \
  ./scripts/p95-3-device-oracle-check.sh /empty/device-oracle-evidence
haykal benchmark-rebuild --report SEALED_REPORT --out /empty/rebuilt
```

The P95.0 hosted fresh-checkout evidence remains unavailable because this
repository has no configured remote. After the final host gate, the expected
overall score is **86/100 official**, or **88/100 conditional** on that hosted
baseline. P95.4 is next: build one wheel and run the full lifecycle from that
wheel alone on clean API 34 and API 35 VMs.
