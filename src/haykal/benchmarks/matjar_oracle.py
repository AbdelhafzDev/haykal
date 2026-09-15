"""Independent ADB state oracle for the debuggable Matjar reference app."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass

from defusedxml import ElementTree

PACKAGE = "dev.haykal.refapps.matjar"


@dataclass(frozen=True, slots=True)
class MatjarAdbOracle:
    serial: str
    adb_path: str
    package: str = PACKAGE

    def _adb(self, *arguments: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self.adb_path, "-s", self.serial, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Matjar oracle ADB command failed")
        return result

    def reset(self) -> None:
        self._adb("shell", "am", "broadcast", "-a", "dev.haykal.refapp.RESET")
        self._adb("shell", "am", "force-stop", self.package)
        self._adb("shell", "am", "start", "-W", "-n", f"{self.package}/.MainActivity")

    def snapshot(self) -> dict[str, object]:
        result = self._adb(
            "shell",
            "run-as",
            self.package,
            "cat",
            "shared_prefs/matjar.xml",
        )
        root = ElementTree.fromstring(result.stdout)
        state: dict[str, object] = {}
        for child in root:
            name = child.attrib.get("name", "")
            if not name.startswith("machine.") and name != "order.created":
                continue
            key = "order_created" if name == "order.created" else name.removeprefix("machine.")
            if child.tag == "boolean":
                value: object = child.attrib.get("value") == "true"
            elif child.tag in {"int", "long"}:
                value = int(child.attrib["value"])
            else:
                value = child.text or child.attrib.get("value", "")
            state[key] = value
        state.setdefault("screen", "home")
        state.setdefault("basket_count", 0)
        state.setdefault("submit_count", 0)
        state.setdefault("order_created", False)
        event_log = str(state.pop("event_log", "")).splitlines()
        return {"state": state, "unsafe_actions": 0, "event_log": event_log}


def main() -> int:
    request = json.load(sys.stdin)
    options = request.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("oracle options must be an object")
    adb_path = str(options.get("adb_path") or shutil.which("adb") or "")
    serial = str(options.get("serial") or "")
    if not adb_path or not serial:
        raise ValueError("Matjar oracle requires adb_path and serial")
    oracle = MatjarAdbOracle(serial=serial, adb_path=adb_path)
    operation = request.get("operation")
    if operation == "reset":
        oracle.reset()
        json.dump({"reset": True}, sys.stdout)
    elif operation == "snapshot":
        json.dump(oracle.snapshot(), sys.stdout, ensure_ascii=False)
    else:
        raise ValueError("unknown oracle operation")
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
