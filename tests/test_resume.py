import json
import httpx
import pytest

from exchange.common import canonical, config, digest, uid
from exchange import buyer, models, registry
from exchange.client import PeerClient
from exchange.provider import card
from exchange.services import execute
from google.protobuf.json_format import MessageToDict


async def test_buyer_restart_uses_checkpoint_without_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(buyer, "DATA", tmp_path)
    c = config()
    app = buyer.make_buyer(c)
    payload = {"task": {"service": "requirements", "source": "Must: Persist."}}
    from exchange.common import Database
    db = Database(tmp_path / "buyer/buyer.sqlite")
    run_id = uid()
    with db.tx() as conn:
        conn.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, "operator", "key", digest(payload), canonical(payload).decode(), None, "attempted"))
        conn.execute("INSERT INTO checkpoints VALUES(?,?)", (run_id, canonical({"task": payload["task"], "provider": "requirements", "decision": {}, "plan": None}).decode()))
    calls = []
    async def rpc(self, peer, method, params, **kw):
        calls.append(kw["key"])
        return {"task": {"id": "persisted-remote", "status": {"state": "TASK_STATE_FAILED"}}}
    async def no_http(*a, **kw):
        raise AssertionError("discovery must not repeat")
    monkeypatch.setattr(PeerClient, "rpc", rpc)
    monkeypatch.setattr(PeerClient, "http", no_http)
    for _ in range(2):
        app = buyer.make_buyer(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=c["peers"]["buyer"]["url"]) as http:
            r = await http.post("/run", json=payload, headers={"Authorization": "Bearer " + c["peers"]["buyer"]["tokens"]["operator"], "Idempotency-Key": "key"})
            assert r.json()["task"]["id"] == "persisted-remote"
    assert calls == [run_id]


async def test_uncertain_model_is_not_repeated(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DATA", tmp_path)
    monkeypatch.setattr(models.shutil, "which", lambda _: "/unused")
    settings = config()["model"]
    prompt, schema = "test", {"type": "object"}
    fingerprint = digest({"prompt": prompt, "schema": schema, "backend": settings["backend"], "model": settings["model"]})
    db = models.model_db()
    with db.tx() as conn:
        conn.execute("INSERT INTO operations VALUES(?,?,?,?,?,?)", ("trace", "inference", fingerprint, "call", "attempted", None))
    with pytest.raises(ValueError, match="outcome unknown"):
        await models.call_model(prompt, schema, "trace")
    with db.tx() as conn:
        conn.execute("UPDATE operations SET status='completed',result='{}'")
    assert await models.call_model(prompt, schema, "trace") == {}


async def test_registry_failed_refresh_does_not_reset_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "DATA", tmp_path)
    c = config()
    app = registry.make_registry(c)
    async def offline(*args, **kw):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(registry.NetworkPolicy, "request", offline)
    from exchange.common import Database
    db = Database(tmp_path / "registry/registry.sqlite")
    with db.tx() as conn:
        conn.execute("INSERT INTO cards VALUES(?,?,?,?,?,?)", ("requirements", canonical(MessageToDict(card(c["peers"]["requirements"]))).decode(), 1, "reachable", None, 1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=c["peers"]["registry"]["url"]) as http:
        r = await http.post("/refresh", headers={"Authorization": "Bearer " + c["peers"]["registry"]["tokens"]["operator"]})
    row = next(a for a in r.json()["agents"] if a["peer"] == "requirements")
    assert row["stale"] and row["health"] == "unavailable" and row["age_seconds"] > 60


async def test_repaired_prompt_is_explicit_and_verifier_unchanged(monkeypatch):
    async def model(prompt, schema, trace, **kw):
        assert "FIRST colon with leading/trailing whitespace removed" in prompt
        assert '"number":3' in prompt
        return execute({"service": "requirements", "source": "Title\n\nMust: trimmed"})
    monkeypatch.setattr(models, "call_model", model)
    payload = {"service": "requirements", "source": "Title\n\nMust: trimmed"}
    from exchange.verification import verify
    assert verify(payload, await models.model_artifact(payload, "trace"))["accepted"]
