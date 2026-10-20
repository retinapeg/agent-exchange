import json
from exchange.common import DATA, config, uid, write_json
from exchange.client import PeerClient, checked_artifact

BRIEF = "Fictional job: Climate data engineer\nMust: Python for data validation\nRequired: Explain reproducible analyses\nPreferred: SQL and geospatial data\nThe team collaborates remotely."
CSV = "id,age,score\na,24,8\nb,,10\nb,,10\nc,-4,19\nd,oops,3\n"


async def demo():
    c = config()
    wire = []
    client = PeerClient(c, recorder=wire.append)
    refresh = await client.http("registry", "POST", "/refresh")
    refresh.raise_for_status()
    brief = {"service": "requirements", "source": BRIEF}
    events = [e async for e in client.stream("requirements", "SendStreamingMessage", client.request(brief), key=uid())]
    task_id = events[0]["task"]["id"]
    task = await client.rpc("requirements", "GetTask", {"id": task_id})
    assert checked_artifact(task, brief)["accepted"]
    missing = {"service": "csv-audit", "source": CSV}
    first = (await client.rpc("csv", "SendMessage", client.request(missing)))["task"]
    assert first["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    full = {**missing, "ranges": {"age": [0, 120], "score": [0, 10]}}
    continued = (await client.rpc("csv", "SendMessage", client.request(full, task_id=first["id"], context_id=first["contextId"])))["task"]
    assert checked_artifact(continued, full)["accepted"]
    cancel = (await client.rpc("csv", "SendMessage", client.request(full, immediate=True)))["task"]
    canceled = await client.rpc("csv", "CancelTask", {"id": cancel["id"]})
    assert canceled["status"]["state"] == "TASK_STATE_CANCELED"
    bad = {"service": "csv-audit", "source": "x,x\n1,2\n", "ranges": {}}
    failed = (await client.rpc("csv", "SendMessage", client.request(bad)))["task"]
    assert failed["status"]["state"] == "TASK_STATE_FAILED"
    recovered = (await client.rpc("csv", "SendMessage", client.request(full)))["task"]
    assert checked_artifact(recovered, full)["accepted"]
    third = {"service": "verify", "submission": full, "artifact": continued["artifacts"][0]["parts"][0]["data"]}
    verification = (await client.rpc("verifier", "SendMessage", client.request(third)))["task"]
    assert checked_artifact(verification, third)["accepted"]
    response = await client.http("buyer", "POST", "/run", json={"task": brief}, headers={"Idempotency-Key": uid()})
    response.raise_for_status()
    buyer = response.json()
    assert buyer["verifier"]["accepted"]
    result = {"status": "passed", "separate_http_providers": 3, "stream_events": len(events), "clarification": True, "cancellation": True,
              "failure_and_recovery": True, "independent_verification": True, "task_ids": [task_id, first["id"], cancel["id"], failed["id"], recovered["id"], verification["id"]], "buyer": buyer}
    write_json(DATA / "receipts" / "demo-wire.json", wire)
    write_json(DATA / "receipts" / "demo.json", result)
    return result
