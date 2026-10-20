"""Independent HTTP simulator ledger. Integer credits; no blockchain or real funds."""
import hmac
import json
import secrets

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from exchange.common import DATA, Database, canonical, digest, now
from exchange.failures import ExchangeFailure
from exchange.quotes import Quote
from exchange.security import Guard
from exchange.contracts import schema_errors

HELD = ("reserved", "authorised", "outcome-unknown")


class Ledger(Database):
    def __init__(self, path, limits):
        super().__init__(path)
        self.limits = limits
        with self.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, principal TEXT, run_id TEXT, provider TEXT,
              quote_id TEXT UNIQUE, binding TEXT, amount INTEGER CHECK(amount>=0), state TEXT, token TEXT, receipt TEXT);
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, balance INTEGER CHECK(balance>=0));
            INSERT OR IGNORE INTO accounts VALUES('buyer',1000);
            CREATE TABLE IF NOT EXISTS settlements(order_id TEXT PRIMARY KEY, receipt TEXT NOT NULL);
            """)
        path.chmod(0o600)

    def register(self, value, issuer):
        q = Quote.model_validate(value).valid(provider=issuer)
        if q.mode != "simulator" or q.principal != "buyer":
            raise ExchangeFailure("policy", "ledger accepts buyer simulator quotes only")
        body = canonical(q.model_dump()).decode()
        with self.tx() as db:
            previous = db.execute("SELECT body FROM quotes WHERE id=?", (q.quote_id,)).fetchone()
            if previous and previous[0] != body:
                raise ExchangeFailure("payment", "immutable quote conflict")
            db.execute("INSERT OR IGNORE INTO quotes VALUES(?,?)", (q.quote_id, body))
        return {"registered": q.quote_id}

    def read(self, order_id, principal, db=None):
        if db is None:
            with self.connect() as conn:
                return self.read(order_id, principal, conn)
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row or principal not in (row["principal"], row["provider"], "observer", "operator"):
            raise HTTPException(404, "order not found")
        return dict(row)

    @staticmethod
    def public(row):
        return {k: json.loads(v) if k == "receipt" and v else v for k, v in row.items() if k != "token"}

    def reserve(self, order_id, quote_id, run_id, principal):
        if principal != "buyer" or not order_id or not run_id or len(order_id) > 128:
            raise ExchangeFailure("policy", "buyer order identifiers required")
        with self.tx() as db:
            qrow = db.execute("SELECT body FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not qrow:
                raise ExchangeFailure("payment", "unregistered quote")
            q = Quote.model_validate_json(qrow[0])
            binding = digest({"quote": q.model_dump(), "run": run_id, "order": order_id, "principal": principal})
            old = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if old:
                if old["binding"] != binding or old["principal"] != principal:
                    raise ExchangeFailure("payment", "immutable order conflict")
                return self.public(dict(old))
            q.valid(principal=principal)
            if db.execute("SELECT 1 FROM orders WHERE quote_id=?", (quote_id,)).fetchone():
                raise ExchangeFailure("payment", "quote already bound to another order")
            exposures = db.execute("SELECT * FROM orders WHERE state NOT IN ('released','failed')").fetchall()
            for key, spent in (("per_task", 0), ("per_run", sum(r["amount"] for r in exposures if r["run_id"] == run_id)),
                               ("per_peer", sum(r["amount"] for r in exposures if r["provider"] == q.provider)),
                               ("global", sum(r["amount"] for r in exposures))):
                if spent + q.amount > self.limits[key]:
                    raise ExchangeFailure("policy", "budget exceeded: " + key)
            held = sum(r["amount"] for r in exposures if r["state"] in HELD)
            balance = db.execute("SELECT balance FROM accounts WHERE id='buyer'").fetchone()[0]
            if q.amount + held > balance:
                raise ExchangeFailure("policy", "insufficient available credits")
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)", (order_id, principal, run_id, q.provider, quote_id, binding, q.amount, "reserved", secrets.token_urlsafe(32), None))
            self.event("payment.reserved", "ledger", q.provider, db=db, order_id=order_id, quote_id=quote_id, trace_id=run_id, amount=q.amount, currency="CREDIT")
            return self.public(self.read(order_id, principal, db))

    def authorise(self, order_id, principal):
        with self.tx() as db:
            row = self.read(order_id, principal, db)
            if principal != row["principal"]:
                raise HTTPException(403)
            if row["state"] == "reserved":
                Quote.model_validate_json(db.execute("SELECT body FROM quotes WHERE id=?", (row["quote_id"],)).fetchone()[0]).valid()
                db.execute("UPDATE orders SET state='authorised' WHERE id=?", (order_id,))
                self.event("payment.authorised", "ledger", row["provider"], db=db, order_id=order_id, trace_id=row["run_id"])
            elif row["state"] not in ("authorised", "settled"):
                raise ExchangeFailure("payment", "order requires reconciliation or is closed")
            return {**self.public(self.read(order_id, principal, db)), "authorization": row["token"]}

    def settle(self, order_id, issuer, authorization, binding):
        with self.tx() as db:
            row = self.read(order_id, issuer, db)
            if issuer != row["provider"] or not hmac.compare_digest(row["token"], authorization) or binding != row["binding"]:
                raise ExchangeFailure("payment", "invalid authorization or binding")
            if row["state"] == "settled":
                return json.loads(row["receipt"])
            if row["state"] != "authorised":
                raise ExchangeFailure("payment", "order is not authorised")
            Quote.model_validate_json(db.execute("SELECT body FROM quotes WHERE id=?", (row["quote_id"],)).fetchone()[0]).valid()
            receipt = {"schema_version": "leo.sim.receipt.v1", "order_id": order_id, "quote_id": row["quote_id"], "binding": binding,
                       "principal": row["principal"], "payee": issuer, "amount": row["amount"], "asset": "CREDIT", "network": "leo:local",
                       "status": "settled", "settled_at": now(), "actual_money": 0}
            text = canonical(receipt).decode()
            db.execute("UPDATE accounts SET balance=balance-? WHERE id='buyer'", (row["amount"],))
            db.execute("INSERT INTO accounts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET balance=balance+excluded.balance", (issuer, row["amount"]))
            db.execute("INSERT INTO settlements VALUES(?,?)", (order_id, text))
            db.execute("UPDATE orders SET state='settled',receipt=? WHERE id=?", (text, order_id))
            self.event("payment.settled", "ledger", issuer, db=db, order_id=order_id, quote_id=row["quote_id"], trace_id=row["run_id"], amount=row["amount"], currency="CREDIT")
            return receipt

    def release(self, order_id, principal, failed=False):
        with self.tx() as db:
            row = self.read(order_id, principal, db)
            if principal != row["principal"]:
                raise HTTPException(403)
            if row["state"] in ("settled", "outcome-unknown"):
                raise ExchangeFailure("payment", "cannot release settled or unresolved order")
            state = "failed" if failed else "released"
            db.execute("UPDATE orders SET state=? WHERE id=?", (state, order_id))
            self.event("payment." + state, "ledger", row["provider"], db=db, order_id=order_id, trace_id=row["run_id"])
            return self.public(self.read(order_id, principal, db))

    def summary(self):
        with self.connect() as db:
            accounts = {r["id"]: r["balance"] for r in db.execute("SELECT * FROM accounts")}
            rows = [self.public(dict(r)) for r in db.execute("SELECT * FROM orders")]
        amounts = {state: sum(r["amount"] for r in rows if r["state"] == state) for state in (*HELD, "settled", "failed", "released")}
        return {"mode": "simulator", "currency": "CREDIT", "accounts": accounts, "amounts": amounts,
                "available": accounts["buyer"] - sum(amounts[s] for s in HELD), "conserved": sum(accounts.values()) == 1000,
                "orders": rows, "actual_service_expenditure": 0}


def make_ledger(c):
    peer = c["peers"]["ledger"]
    store = Ledger(DATA / "ledger/ledger.sqlite", c["limits"])
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    schema_errors(app)

    @app.exception_handler(ExchangeFailure)
    async def failure(request, error):
        return JSONResponse({"category": error.category, "error": str(error)}, 409)

    @app.get("/health")
    async def health():
        return {"status": "ok", "peer": "ledger", "instance": peer.get("instance"), "mode": "simulator"}

    @app.post("/quotes")
    async def register(request: Request):
        principal = request.state.principal
        if principal not in c["peers"] or "services" not in c["peers"][principal]:
            raise HTTPException(403)
        return store.register(await request.json(), principal)

    @app.post("/orders")
    async def reserve(request: Request):
        value = await request.json()
        if not isinstance(value, dict) or set(value) != {"order_id", "quote_id", "run_id"} or any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in value.values()):
            raise HTTPException(422, "invalid order schema")
        return store.reserve(value["order_id"], value["quote_id"], value["run_id"], request.state.principal)

    @app.get("/orders/{order_id}")
    async def read(order_id: str, request: Request):
        return store.public(store.read(order_id, request.state.principal))

    @app.post("/orders/{order_id}/{action}")
    async def update(order_id: str, action: str, request: Request):
        principal = request.state.principal
        if action == "authorise":
            return store.authorise(order_id, principal)
        if action in ("release", "fail"):
            return store.release(order_id, principal, failed=action == "fail")
        if action == "settle":
            value = await request.json()
            if not isinstance(value, dict) or set(value) != {"authorization", "binding"} or any(not isinstance(v, str) for v in value.values()):
                raise HTTPException(422, "invalid settlement schema")
            return store.settle(order_id, principal, value["authorization"], value["binding"])
        raise HTTPException(404)

    @app.get("/summary")
    async def summary(request: Request):
        if request.state.principal not in ("buyer", "observer", "operator"):
            raise HTTPException(403)
        return store.summary()

    @app.get("/observe")
    async def observe(request: Request, after: int = 0):
        if request.state.principal not in ("observer", "operator"):
            raise HTTPException(403)
        return {"events": store.events(after)}
    return Guard(app, peer, store=store)
