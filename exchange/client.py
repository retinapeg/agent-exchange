from __future__ import annotations

import json

import httpx
from a2a import types as t
from google.protobuf.json_format import ParseDict

from exchange.common import NS, MAX_BODY, canonical, digest, uid
from exchange.security import NetworkPolicy
from exchange.failures import RpcFailure


class PeerClient:
    """Application client; explicit wire requests are independently checked with SDK types."""
    def __init__(self, c, principal="buyer", recorder=None):
        self.c, self.principal, self.recorder = c, principal, recorder
        self.net = NetworkPolicy([p["url"] for p in c["peers"].values()], c["mode"] == "local")

    async def http(self, peer, method, path, **kwargs):
        from exchange.tracing import headers
        p = self.c["peers"][peer]
        kwargs['headers'] = {**headers(), **kwargs.pop('headers', {})}
        return await self.net.request(method, p["url"] + path, token=p["tokens"][self.principal], **kwargs)

    def request(self, payload, *, task_id=None, context_id=None, immediate=False, message_id=None):
        msg = {"messageId": message_id or uid(), "role": "ROLE_USER", "parts": [{"data": payload, "mediaType": "application/json"}]}
        if task_id:
            msg["taskId"] = task_id
        if context_id:
            msg["contextId"] = context_id
        return {"message": msg, "configuration": {"returnImmediately": immediate}}

    async def rpc(self, peer, method, params, *, key=None, trace=None, headers=None):
        body = {"jsonrpc": "2.0", "id": uid(), "method": method, "params": params}
        from exchange.tracing import current
        extra = {"Idempotency-Key": key or uid(), "X-Trace-Id": trace or current.get().get('trace_id') or uid(), **(headers or {})}
        response = await self.http(peer, "POST", "/a2a", json=body, headers=extra)
        if self.recorder:
            self.recorder({"peer": peer, "request": body, "status": response.status_code, "response": response.json()})
        response.raise_for_status()
        wire = response.json()
        if "error" in wire:
            raise RpcFailure(wire["error"])
        result = wire["result"]
        cls = {"SendMessage": t.SendMessageResponse, "GetTask": t.Task, "CancelTask": t.Task, "ListTasks": t.ListTasksResponse}.get(method)
        if cls:
            ParseDict(result, cls())
        return result

    async def stream(self, peer, method, params, *, key, trace=None):
        p = self.c["peers"][peer]
        url = self.net.check(p["url"] + "/a2a")
        body = {"jsonrpc": "2.0", "id": uid(), "method": method, "params": params}
        from exchange.tracing import headers as trace_headers, current
        headers = {**trace_headers(), "Authorization": "Bearer " + p["tokens"][self.principal], "A2A-Version": "1.0", "Idempotency-Key": key, "X-Trace-Id": trace or current.get().get('trace_id') or uid()}
        seen = set()
        size = 0
        async with httpx.AsyncClient(timeout=150, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise ValueError("stream error response exceeds size limit")
                    wire = json.loads(raw)
                    if "error" in wire:
                        raise RpcFailure(wire["error"])
                    raise ValueError("peer did not return an SSE stream")
                async for line in response.aiter_lines():
                    size += len(line)
                    if size > 4 * MAX_BODY or len(line) > MAX_BODY:
                        raise ValueError("stream limit exceeded")
                    if not line.startswith("data: "):
                        continue
                    wire = json.loads(line[6:])
                    if self.recorder:
                        self.recorder({"peer": peer, "request": body, "status": response.status_code, "sse": wire})
                    if "error" in wire:
                        raise RpcFailure(wire["error"])
                    value = wire["result"]
                    ParseDict(value, t.StreamResponse())
                    stamp = digest(value)
                    if stamp not in seen:
                        seen.add(stamp)
                        yield value


def checked_artifact(task, request):
    from exchange.verification import verify
    if task["status"]["state"] != "TASK_STATE_COMPLETED":
        return {"accepted": False, "policy": "deterministic-evidence-v1", "errors": ["task_not_completed"]}
    try:
        artifact = task["artifacts"][0]
        value = artifact["parts"][0]["data"]
        meta = artifact["metadata"][NS]
        if digest(value) != meta["sha256"] or len(canonical(value)) != meta["size"] or meta["input_sha256"] != digest(request):
            return {"accepted": False, "errors": ["artifact_integrity_failure"]}
        return verify(request, value)
    except (KeyError, IndexError, TypeError):
        return {"accepted": False, "errors": ["artifact_schema_failure"]}
