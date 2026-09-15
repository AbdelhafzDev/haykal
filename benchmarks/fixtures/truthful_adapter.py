"""Local fixture that creates the state it claims."""

import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
state_file = Path(request["options"]["state_file"])
state = json.loads(state_file.read_text())
state["offers"] = True
state_file.write_text(json.dumps(state))
print(json.dumps({"success": True, "unsafe_actions": 0, "steps": 1}))
