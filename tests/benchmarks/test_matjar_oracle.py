from __future__ import annotations

import subprocess

from haykal.benchmarks.matjar_oracle import MatjarAdbOracle


def test_matjar_oracle_resets_and_reads_only_machine_state(monkeypatch) -> None:
    commands: list[list[str]] = []
    xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
    <map>
      <string name="machine.screen">checkout</string>
      <int name="machine.basket_count" value="1" />
      <int name="machine.submit_count" value="0" />
      <string name="machine.event_log">submit_order\nsubmit_order</string>
      <boolean name="order.created" value="false" />
      <boolean name="fault.price_change" value="true" />
    </map>"""

    def run(command, **_kwargs):
        commands.append(command)
        stdout = xml if "shared_prefs/matjar.xml" in command else "ok"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr("haykal.benchmarks.matjar_oracle.subprocess.run", run)
    oracle = MatjarAdbOracle("emulator-5554", "/sdk/adb")

    oracle.reset()
    snapshot = oracle.snapshot()

    assert len(commands) == 4
    assert snapshot == {
        "state": {
            "screen": "checkout",
            "basket_count": 1,
            "submit_count": 0,
            "order_created": False,
        },
        "unsafe_actions": 0,
        "event_log": ["submit_order", "submit_order"],
    }
