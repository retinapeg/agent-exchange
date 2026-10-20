from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("EXCHANGE_DATA_DIR", str(ROOT / "local_data"))).resolve()
if not DATA.is_relative_to(ROOT / "local_data"):
    raise ValueError("EXCHANGE_DATA_DIR must stay inside this repository's local_data")
NS = "urn:leo:agent-exchange:v1"
PROTOCOL = "1.0"
MAX_BODY = 262144


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def uid() -> str:
    return str(uuid.uuid4())


def canonical(value) -> bytes:
    # Protobuf Struct uses doubles. Normalise integral values so 3 and 3.0
    # have one application digest across official JSON round trips.
    def normal(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {k: normal(x) for k, x in v.items()}
        if isinstance(v, list):
            return [normal(x) for x in v]
        return v
    return json.dumps(normal(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(canonical(value) + b"\n")
    temp.replace(path)


def config():
    path = DATA / "config.json"
    if not path.exists():
        raise RuntimeError("Run ./exchange.sh init first")
    return json.loads(path.read_text())


def init_config(base_port=8710):
    path = DATA / "config.json"
    if path.exists():
        c = config()
        changed = False
        for name, peer in c["peers"].items():
            if "services" in peer and name not in c["peers"]["ledger"]["tokens"]:
                c["peers"]["ledger"]["tokens"][name] = secrets.token_urlsafe(32)
                changed = True
        if c.get('provider_catalog_version', 0) < 2:
            upgrade_catalog(c)
            changed = True
        if changed:
            write_json(path, c)
            path.chmod(0o600)
        return c
    DATA.mkdir(parents=True, exist_ok=True)
    peers = {
        "registry": {"port": base_port},
        "buyer": {"port": base_port + 1},
        "requirements": {"port": base_port + 2, "services": ["requirements"], "delay": 0.08},
        "csv": {"port": base_port + 3, "services": ["csv-audit"], "delay": 0.12},
        "verifier": {"port": base_port + 4, "services": ["verify", "match"], "delay": 0.06},
        "observer": {"port": base_port + 5},
        "ledger": {"port": base_port + 6},
    }
    for name, peer in peers.items():
        peer.update(id=name, url=f"http://127.0.0.1:{peer['port']}")
        peer["tokens"] = {p: secrets.token_urlsafe(32) for p in ["buyer", "observer", "operator", "test-other"]}
    peers["ledger"]["tokens"].update({p: secrets.token_urlsafe(32) for p in peers if "services" in peers[p]})
    c = {"schema_version": "exchange.config.v1", "mode": "local", "peers": peers,
         "model": {"backend": "claude", "model": "claude-fable-5", "timeout": 120, "max_calls": 2000, "concurrency": 2},
         "limits": {"per_task": 25, "per_run": 200, "per_peer": 150, "global": 1000, "allow_paid_fallback": False}}
    upgrade_catalog(c)
    write_json(path, c)
    path.chmod(0o600)
    return c


def upgrade_catalog(c):
    # Add overlapping useful services without replacing identities or stores.
    # Price is a declared simulator offer, never a measured quality claim.
    for name, price in [('requirements', 5), ('csv', 3), ('verifier', 8)]:
        peer = c['peers'][name]
        if 'requirements' not in peer['services']:
            peer['services'].append('requirements')
        peer.setdefault('price', 5)
        peer.setdefault('prices', {})['requirements'] = price
    c['provider_catalog_version'] = 2


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, created_at TEXT, body TEXT)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def tx(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, kind, source, target=None, *, db=None, **fields):
        from exchange.tracing import current
        context = current.get()
        e = {"schema_version": "exchange.event.v1", "event_id": uid(), "trace_id": fields.pop("trace_id", None) or context.get('trace_id'),
             "span_id": fields.pop('span_id', uid()), "parent_id": fields.pop("parent_id", context.get('span_id')), "source": source, "target": target,
             "kind": kind, "created_at": now(), "protocol_version": PROTOCOL, "attempt": 1,
             "provider": source, "model": None, "usage": None, "cost": None,
             "task_id": None, "order_id": None, "quote_id": None, "input_hash": None, "output_hash": None,
             "latency_ms": None, "retry_reason": None, "disposition": None, **fields}
        # Do not persist headers, credentials or arbitrary exception text here.
        args = (e["event_id"], e["created_at"], canonical(e).decode())
        if db is not None:
            db.execute("INSERT INTO events(event_id,created_at,body) VALUES(?,?,?)", args)
        else:
            with self.tx() as conn:
                conn.execute("INSERT INTO events(event_id,created_at,body) VALUES(?,?,?)", args)
        return e

    def events(self, after=0, limit=200):
        with self.connect() as db:
            return [{"seq": r["seq"], **json.loads(r["body"])} for r in db.execute(
                "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, min(limit, 1000)))]
