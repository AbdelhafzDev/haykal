"""Independent file-state oracle used by the local adversarial evidence run."""

import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
state_file = Path(request["options"]["state_file"])
if request["operation"] == "reset":
    state_file.write_text(json.dumps({"offers": False, "submit_count": 0}))
    print(json.dumps({"reset": True}))
elif request["operation"] == "snapshot":
    print(
        json.dumps(
            {
                "state": json.loads(state_file.read_text()),
                "unsafe_actions": 0,
                "event_log": [],
            }
        )
    )
else:
    raise SystemExit(2)
