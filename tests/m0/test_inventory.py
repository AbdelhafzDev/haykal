from __future__ import annotations

from pathlib import Path

from haykal.m0.inventory import build_inventory


def test_inventory_is_sorted_and_hashes_lock(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("locked", encoding="utf-8")
    inventory = build_inventory(tmp_path)
    packages = inventory["packages"]
    names = [str(package["name"]) for package in packages]

    assert inventory["schema_version"] == "1.0"
    assert inventory["uv_lock"]["digest"].startswith("sha256:")
    assert names == sorted(names, key=str.casefold)
    assert any(name.casefold() == "uiautomator2" for name in names)


def test_inventory_marks_missing_lock(tmp_path: Path) -> None:
    assert build_inventory(tmp_path)["uv_lock"]["digest"] is None
