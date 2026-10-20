import json
import time

from a2a import types as t
from a2a.utils.proto_utils import validate_proto_required_fields
from fastapi import FastAPI, Request, HTTPException
from google.protobuf.json_format import ParseDict

from exchange.common import DATA, Database, canonical, now
from exchange.security import Guard, NetworkPolicy


def validate_card(value, origin, expected_identity):
    parsed = ParseDict(value, t.AgentCard())
    validate_proto_required_fields(parsed)
    if parsed.name != expected_identity:
        raise ValueError("configured peer identity differs from card claim")
    if not any(i.protocol_version in ["1.0", "1.0.0"] and i.protocol_binding == "JSONRPC" and i.url == origin + "/a2a" for i in parsed.supported_interfaces):
        raise ValueError("No compatible pinned A2A interface")
    if any(i.url != origin + "/a2a" for i in parsed.supported_interfaces):
        raise ValueError("card redirects to an unconfigured endpoint")
    if any(e.required for e in parsed.capabilities.extensions):
        raise ValueError("Required peer extensions are not automatically trusted")
    return parsed


def make_registry(c):
    peer = c["peers"]["registry"]
    db = Database(DATA / "registry" / "registry.sqlite")
    with db.tx() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS cards(peer TEXT PRIMARY KEY, body TEXT, checked REAL, health TEXT, error TEXT)")
        if "fetched" not in {r[1] for r in conn.execute("PRAGMA table_info(cards)")}:
            conn.execute("ALTER TABLE cards ADD COLUMN fetched REAL")
    net = NetworkPolicy([p["url"] for p in c["peers"].values()])
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok", "peer": "registry", "instance": peer.get("instance")}

    @app.post("/refresh")
    async def refresh(request: Request):
        if request.state.principal not in ["buyer", "operator"]:
            raise HTTPException(403)
        for name, p in c["peers"].items():
            if "services" not in p:
                continue
            try:
                response = await net.request("GET", p["url"] + "/.well-known/agent-card.json", limit=65536)
                response.raise_for_status()
                value = response.json()
                validate_card(value, p["url"], name)
                health_response = await net.request("GET", p["url"] + "/health", limit=4096)
                health_response.raise_for_status()
                state, error = "reachable", None
                body = canonical(value).decode()
            except Exception as e:
                state, error, body = "unavailable", type(e).__name__, None
            with db.tx() as conn:
                conn.execute("INSERT INTO cards VALUES(?,?,?,?,?,?) ON CONFLICT(peer) DO UPDATE SET body=COALESCE(excluded.body,cards.body),checked=excluded.checked,health=excluded.health,error=excluded.error,fetched=COALESCE(excluded.fetched,cards.fetched)", (name, body, time.time(), state, error, time.time() if body else None))
            db.event("discovery.checked", "registry", name, disposition=state, failure_category=error)
        return await search()

    @app.get("/agents")
    async def search(capability: str = ""):
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM cards ORDER BY peer").fetchall()
        results = []
        for row in rows:
            value = json.loads(row["body"]) if row["body"] else None
            if capability and (not value or capability not in [s["id"] for s in value["skills"]]):
                continue
            age = time.time() - row["fetched"] if row["fetched"] else None
            results.append({"peer": row["peer"], "card": value, "health": row["health"], "age_seconds": round(age, 2) if age is not None else None, "stale": age is None or age > 60, "last_health_check": row["checked"],
                            "provenance": "configured local identity; unsigned card", "quality": "unknown", "capabilities": "declared", "health_basis": "measured HTTP reachability", "error": row["error"]})
        return {"agents": results, "as_of": now()}

    @app.get("/observe")
    async def observe(request: Request, after: int = 0):
        if request.state.principal not in ["observer", "operator"]:
            raise HTTPException(403)
        return {"events": db.events(after)}
    return Guard(app, peer, store=db)
