import asyncio
import copy
import json
import socket
import subprocess
import sys
import time

import httpx
import pytest
from a2a import types as t
from a2a.client import ClientFactory, ClientConfig
from a2a.client.transports.jsonrpc import JsonRpcTransport
from google.protobuf.json_format import MessageToDict, ParseDict

from exchange.client import PeerClient, checked_artifact
from exchange.common import ROOT, DATA, config, uid, write_json
from exchange.demo import BRIEF
from exchange.registry import validate_card


@pytest.fixture
def c():
    return config()


async def test_sdk_client_to_exchange(c):
    peer = c["peers"]["requirements"]
    records = []
    async def capture(response):
        if "text/event-stream" not in response.headers.get("content-type", ""):
            await response.aread()
            records.append({"request": json.loads(response.request.content) if response.request.content else None, "response": response.json()})
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + peer["tokens"]["operator"], "A2A-Version": "1.0"}, event_hooks={"response": [capture]}, trust_env=False) as http:
        # Construct everything through official SDK types, no project request serializer.
        card = ParseDict((await http.get(peer["url"]+"/.well-known/agent-card.json")).json(), t.AgentCard())
        transport = JsonRpcTransport(http, card, peer["url"]+"/a2a")
        req = t.SendMessageRequest(message=t.Message(message_id=uid(), role=t.Role.ROLE_USER,
            parts=[ParseDict({"data": {"service": "requirements", "source": BRIEF}, "mediaType": "application/json"}, t.Part())]))
        response = await transport.send_message(req)
        assert response.task.status.state == t.TaskState.TASK_STATE_COMPLETED
        received = await transport.get_task(t.GetTaskRequest(id=response.task.id))
        assert received.id == response.task.id
        streamed = [e async for e in transport.send_message_streaming(req)]
        assert any(e.HasField("artifact_update") for e in streamed)
        assert streamed[-1].status_update.status.state == t.TaskState.TASK_STATE_COMPLETED
        write_json(DATA / "receipts" / "sdk-client-wire.json", {"records": records, "stream": [MessageToDict(e) for e in streamed]})


async def test_exchange_client_to_upstream_reference(c):
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    out = (DATA / "receipts" / "reference-server.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(ROOT / "tests/reference_peer.py"), str(port)], stdout=out, stderr=out)
    try:
        async with httpx.AsyncClient(trust_env=False) as http:
            for _ in range(100):
                try:
                    r = await http.get(f"http://127.0.0.1:{port}/.well-known/agent-card.json")
                    if r.status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
            else:
                pytest.fail("reference peer did not start")
        adapted = copy.deepcopy(c)
        adapted["peers"]["reference"] = {"url": f"http://127.0.0.1:{port}", "tokens": {"buyer": "fixture-unused"}}
        records = []
        client = PeerClient(adapted, recorder=records.append)
        response = await client.rpc("reference", "SendMessage", client.request({"service": "reference", "source": BRIEF}))
        assert response["message"]["parts"][0]["text"] == "Reference SDK received a structured message."
        write_json(DATA / "receipts" / "reference-server-wire.json", records)
    finally:
        proc.terminate(); proc.wait(timeout=5); out.close()


async def test_http_duplicate_and_principal_isolation(c):
    client = PeerClient(c)
    payload = {"service": "requirements", "source": BRIEF}
    params = client.request(payload)
    key = uid()
    results = await asyncio.gather(*[client.rpc("requirements", "SendMessage", params, key=key) for _ in range(12)])
    ids = {r["task"]["id"] for r in results}
    assert len(ids) == 1
    with pytest.raises(RuntimeError):
        await client.rpc("requirements", "SendMessage", client.request({**payload, "source": "changed"}), key=key)
    other = PeerClient(c, "test-other")
    task_id = next(iter(ids))
    with pytest.raises(RuntimeError):
        await other.rpc("requirements", "GetTask", {"id": task_id})
    with pytest.raises(RuntimeError):
        await other.rpc("requirements", "CancelTask", {"id": task_id})


async def test_version_capabilities_schema_auth_and_size(c):
    client = PeerClient(c)
    peer = c["peers"]["requirements"]
    for method, params, expected in [("GetTask", {"id": "unknown"}, -32009), ("CreateTaskPushNotificationConfig", {"taskId": "unknown"}, -32003)]:
        headers = {"A2A-Version": "0.3"} if expected == -32009 else {}
        r = await client.http("requirements", "POST", "/a2a", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        assert r.json()["error"]["code"] == expected
    r = await client.http("requirements", "POST", "/a2a", content=b"x"*262145)
    assert r.status_code == 413
    async with httpx.AsyncClient(trust_env=False) as http:
        r = await http.post(peer["url"]+"/a2a", json={})
        assert r.status_code == 401
        r = await http.get(peer["url"]+"/health", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403


async def test_malicious_cards(c):
    client = PeerClient(c)
    peer = c["peers"]["requirements"]
    r = await client.http("requirements", "GET", "/.well-known/agent-card.json")
    base = r.json()
    validate_card(base, peer["url"], "requirements")
    for patch in [{"name": "trusted-bank"}, {"supportedInterfaces": [{"url": "http://169.254.169.254/latest", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]}, {"surprise": "malicious"}]:
        with pytest.raises(Exception):
            validate_card({**base, **patch}, peer["url"], "requirements")


async def test_stream_disconnect_reconnect_and_replay(c):
    client = PeerClient(c)
    request = {"service": "requirements", "source": BRIEF}
    stream = client.stream("requirements", "SendStreamingMessage", client.request(request), key=uid())
    first = await anext(stream)
    task_id = first["task"]["id"]
    await stream.aclose()
    events = [e async for e in client.stream("requirements", "SubscribeToTask", {"id": task_id}, key=uid())]
    task = await client.rpc("requirements", "GetTask", {"id": task_id})
    assert checked_artifact(task, request)["accepted"]
    r = await client.http("requirements", "GET", f"/events/{task_id}")
    replay = r.json()["events"]
    assert len({e["event_id"] for e in replay}) == len(replay)
    r = await client.http("requirements", "GET", f"/events/{task_id}?after={replay[-1]['seq']}")
    assert r.json()["events"] == []


async def test_list_tasks_cursor_scoping_and_terminal_subscription(c):
    client = PeerClient(c)
    context = uid()
    expected = []
    for i in range(3):
        task = (await client.rpc('requirements','SendMessage',client.request({'service':'requirements','source':f'Must: {i}'},context_id=context)))['task']
        expected.append(task['id'])
    params = {'contextId':context,'pageSize':1,'status':'TASK_STATE_COMPLETED'}
    seen, token = [], None
    while True:
        page = await client.rpc('requirements','ListTasks',{**params,**({'pageToken':token} if token else {})})
        assert page['totalSize'] == 3 and 'nextPageToken' in page
        assert 'artifacts' not in page['tasks'][0]
        seen.append(page['tasks'][0]['id'])
        token = page['nextPageToken']
        if not token:
            break
        with pytest.raises(RuntimeError):
            await PeerClient(c,'test-other').rpc('requirements','ListTasks',{**params,'pageToken':token})
    assert seen == list(reversed(expected)) and len(set(seen)) == 3
    page = await client.rpc('requirements','ListTasks',{**params,'statusTimestampAfter':'2099-01-01T00:00:00Z'})
    assert page['tasks'] == [] and page['totalSize'] == 0 and page['nextPageToken'] == ''
    with pytest.raises(RuntimeError):
        _ = [e async for e in client.stream('requirements','SubscribeToTask',{'id':expected[0]},key=uid())]
