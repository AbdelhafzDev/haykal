# Flutter sparse reference app

Package: `dev.haykal.refapps.flutter_sparse`

This deterministic, offline app provides three surfaces: semantics enabled,
semantics disabled with the same visual layout, and an image-painted Arabic price
card. It isolates the hierarchy-sparse cases that must trigger Haykal's OCR and
vision fallback.

It performs no network requests and contains no real payment integration,
credentials, or user data.

The three declared faults are controlled through the shared broadcast contract:

```shell
adb shell am broadcast -a dev.haykal.refapp.SET_FAULT \
  -p dev.haykal.refapps.flutter_sparse \
  --es name arabic_indic_digits --ez enabled true
adb shell am broadcast -a dev.haykal.refapp.RESET \
  -p dev.haykal.refapps.flutter_sparse
```

Build and verify with the pinned Flutter 3.47.4 SDK:

```shell
FLUTTER_BIN=/path/to/flutter/bin/flutter ./scripts/flutter-sparse-check.sh
```
