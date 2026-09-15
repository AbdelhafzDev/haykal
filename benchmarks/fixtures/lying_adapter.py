"""Adversarial fixture that claims success without changing external state."""

import json
import sys

json.load(sys.stdin)
print(json.dumps({"success": True, "unsafe_actions": 0, "steps": 1}))
