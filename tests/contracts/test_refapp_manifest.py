from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_reference_manifest_has_the_focused_two_app_scope() -> None:
    manifest = json.loads((ROOT / "refapps/manifest.json").read_text(encoding="utf-8"))
    apps = {app["name"]: app for app in manifest["apps"]}

    assert apps.keys() == {"matjar", "flutter-sparse"}
    assert set(apps["matjar"]["technologies"]) == {
        "android-view",
        "jetpack-compose",
        "webview",
    }
    assert "flutter" in apps["flutter-sparse"]["technologies"]
    assert len(apps["matjar"]["faults"]) == 13
    assert len(apps["matjar"]["faults"]) == len(set(apps["matjar"]["faults"]))


def test_reference_apps_have_no_network_or_real_payment_contract() -> None:
    for readme in ("refapps/matjar/README.md", "refapps/flutter-sparse/README.md"):
        content = (ROOT / readme).read_text(encoding="utf-8").casefold()
        assert "no network" in content
        assert "no real payment" in content


def test_flutter_version_pin_is_consistent_across_build_surfaces() -> None:
    toolchain = json.loads((ROOT / "toolchains/flutter-sdk.json").read_text(encoding="utf-8"))
    version = toolchain["version"]
    pubspec = (ROOT / "refapps/flutter-sparse/pubspec.yaml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/phase2.yml").read_text(encoding="utf-8")

    assert f"flutter: {version}" in pubspec
    assert f'flutter-version: "{version}"' in workflow
    assert len(toolchain["macos_arm64"]["sha256"]) == 64
