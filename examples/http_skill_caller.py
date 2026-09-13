"""Run a published skill and review approval with a separate credential."""

from __future__ import annotations

import os

from haykal.contracts import RunRequest
from haykal.sdk import HaykalClient

base_url = "http://127.0.0.1:8421"
caller = HaykalClient(base_url, os.environ["HAYKAL_API_TOKEN"])
approver = HaykalClient(base_url, os.environ["HAYKAL_APPROVER_TOKEN"])

run = caller.run_skill(
    RunRequest(
        session_id=os.environ["HAYKAL_SESSION_ID"],
        skill="matjar.prepare_pizza_order",
        version="1.0.0",
        inputs={"maximum_total": {"amount": 60, "currency": "SAR"}},
    )
)
if run.status == "approval_required":
    challenge = approver.approval_challenge(run.run_id)
    print("Review material before approving:", challenge.material)
    if os.environ.get("HAYKAL_EXAMPLE_APPROVE") == "yes":
        run = approver.approve_run(run.run_id, challenge)
print(run.status, run.trace_id)
