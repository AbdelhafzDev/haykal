# PR.1 — OmniParser V2 fallback

Status: **implementation complete; production evidence pending**

Release candidate: `0.0.4`

## Shipped boundary

- Accessibility remains the primary source.
- Microsoft OmniParser V2 `icon_detect_v3` and `icon_caption` are available as
  the optional `omniparser` extra.
- The production runtime never downloads code or weights. Cache preparation is
  an explicit operator command and runtime startup verifies every pinned size
  and SHA-256 digest before importing the ML stack.
- The model manifest is bundled in the wheel. Operators may override it only by
  passing another strict manifest explicitly.
- Automatic vision fallback runs for sparse accessibility scenes and after a
  selector has no accessibility target. Callers can also request vision
  explicitly through Python, HTTP, MCP, or the CLI.
- Vision candidates enter the existing scene/fusion/evidence path. Effective
  risk classification still occurs after final target resolution; a
  vision-discovered payment control therefore requires approval even when the
  caller declares navigation risk.
- Model files appear in the generated SBOM even when the optional ML packages
  are not installed.
- `haykal-evaluate-fallback` now runs the production adapter and resolver over a
  digest-pinned labelled dataset and fails the release gate on accuracy,
  irreversible mis-resolution, unsafe ambiguity, or p95 latency. See the
  [evaluation runbook](pr1-fallback-evaluation.md).

## Offline setup

```bash
python -m pip install 'haykal-runtime[omniparser]==0.0.4'
haykal-prepare-omniparser --cache /var/lib/haykal/models/omniparser-v2
```

The preparation host may use the network. Copy the completed cache to the
private production host and start Haykal with:

```bash
haykal --state-dir /var/lib/haykal serve \
  --device-serial emulator-5554 \
  --omniparser-cache /var/lib/haykal/models/omniparser-v2 \
  --omniparser-device cuda
```

`--omniparser-manifest` is optional because the exact pinned manifest ships in
the wheel. Supplying a cache path enables the fallback; omitting it preserves
the accessibility-only runtime and public contracts.

## Pinned upstream inputs

- OmniParser repository commit:
  `354021201345a96178360b28733573e27269f2de`
- OmniParser V2 model revision:
  `f55d0750e5b94db2125ef0b45b0fa4a85ddc59b4`
- Florence-2 processor revision:
  `5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac`
- Detector weight SHA-256:
  `11c6cbb77f22569fab22d86c76407a83ec81ab89dbfe28279854822d6e3fb00c`
- Captioner weight SHA-256:
  `01b934b0fe2d07b181e2d07752f16ae27c9d0ea88ddffe13a9a003aa9680f233`

See `THIRD_PARTY_NOTICES.md` for the MIT and Apache-2.0 inventory.

## Remaining acceptance evidence

This implementation does **not** pass the production fallback gate by itself.
PR.1 still requires the labelled Matjar and authorized regional datasets on the
declared reference host, at least 95% correct fallback target resolution, zero
wrong irreversible dispatches, fail-closed ambiguity results, and fallback P95
latency no greater than three seconds. The new wheel must then repeat hosted
P95.4 acceptance on clean API 34 and 35 VMs before PR.2 begins.
