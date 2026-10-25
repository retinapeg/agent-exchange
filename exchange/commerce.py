"""Bounded application negotiation and optional leo-sim-v1 admission over HTTP."""
import json

import httpx
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from x402.schemas import PaymentRequired, PaymentRequirements, PaymentPayload, ResourceInfo, SettleResponse
from x402.http.utils import (encode_payment_required_header, decode_payment_required_header,
    encode_payment_signature_header, decode_payment_signature_header, encode_payment_response_header)
from x402.extensions.payment_identifier import declare_payment_identifier_extension, append_payment_identifier_to_extensions

from exchange.common import canonical, config, digest
from exchange.client import PeerClient
from exchange.quotes import Quote, offer
from exchange.failures import ExchangeFailure
from exchange.contracts import task_schema


def requirements(q):
    return PaymentRequirements(scheme="leo-sim-v1", network=q.network, asset=q.asset, amount=str(q.amount),
                               pay_to=q.payee, max_timeout_seconds=600, extra={"quote_id": q.quote_id, "input_digest": q.input_digest})


def add_commerce(app, peer, store):
    with store.tx() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY, principal TEXT, task TEXT, quote TEXT, state TEXT, transcript TEXT);
        CREATE TABLE IF NOT EXISTS negotiations(principal TEXT, key TEXT, digest TEXT, result TEXT, PRIMARY KEY(principal,key));
        CREATE TABLE IF NOT EXISTS admissions(order_id TEXT PRIMARY KEY, principal TEXT, input_digest TEXT, receipt TEXT);
        CREATE TABLE IF NOT EXISTS payment_attempts(order_id TEXT PRIMARY KEY, state TEXT, quote_id TEXT);
        """)
    client = PeerClient(config(), peer["id"])

    @app.exception_handler(ExchangeFailure)
    async def failure(request, error):
        return JSONResponse({"category": error.category, "error": str(error)}, 409)

    def get_quote(qid, principal, db):
        row = db.execute("SELECT * FROM offers WHERE id=? AND principal=?", (qid, principal)).fetchone()
        if not row:
            raise HTTPException(404)
        return row, Quote.model_validate_json(row["quote"])

    @app.post("/negotiate")
    async def negotiate(request: Request):
        principal = request.state.principal
        if principal not in ("buyer", "operator"):
            raise HTTPException(403)
        value = await request.json()
        key = request.headers.get("idempotency-key")
        if not key or len(key) > 128:
            raise HTTPException(400, "idempotency-key required")
        if not isinstance(value, dict) or set(value) - {"action", "task", "mode", "quote_id", "amount"}:
            raise HTTPException(422)
        with store.tx() as db:
            old = db.execute("SELECT * FROM negotiations WHERE principal=? AND key=?", (principal, key)).fetchone()
            if old:
                if old["digest"] != digest(value):
                    raise ExchangeFailure("policy", "negotiation changed-content reuse")
                return json.loads(old["result"])
            action = value.get("action", "request")
            if action == "request":
                task = value.get("task", {})
                try:
                    task_schema(task, peer["services"])
                except ValueError:
                    raise ExchangeFailure("schema", "invalid task scope; no quote issued") from None
                if task["service"] == "csv-audit" and "ranges" not in task:
                    result = {"status": "input-required", "missing": ["ranges"], "instruction": "Send a new quote request after supplying ranges."}
                else:
                    q = offer(peer["id"], principal, task, value.get("mode", "free"), peer.get('prices', {}).get(task['service'], peer.get("price", 5)))
                    transcript = [{"action": "request", "input_digest": digest(task)}, {"action": "offer", "quote_id": q.quote_id}]
                    db.execute("INSERT INTO offers VALUES(?,?,?,?,?,?)", (q.quote_id, principal, canonical(task).decode(), canonical(q.model_dump()).decode(), "offered", canonical(transcript).decode()))
                    result = {"status": "offered", "quote": q.model_dump(), "transcript": transcript}
            elif action in ("accept", "reject", "counter"):
                row, q = get_quote(value.get("quote_id"), principal, db)
                if row["state"] != "offered":
                    raise ExchangeFailure("policy", "quote is no longer open")
                q.valid()
                transcript = json.loads(row["transcript"])
                transcript.append({"action": action, "quote_id": q.quote_id})
                state = {"accept": "accepted", "reject": "rejected", "counter": "superseded"}[action]
                db.execute("UPDATE offers SET state=?,transcript=? WHERE id=?", (state, canonical(transcript).decode(), q.quote_id))
                if action == "counter":
                    amount = value.get("amount")
                    if q.round >= 3 or type(amount) is not int or not 2 <= amount <= q.amount:
                        raise ExchangeFailure("policy", "counteroffer outside deterministic terms or round limit")
                    q = offer(peer["id"], principal, json.loads(row["task"]), q.mode, amount, q.round + 1)
                    transcript.append({"action": "offer", "quote_id": q.quote_id})
                    state = "offered"
                    db.execute("INSERT INTO offers VALUES(?,?,?,?,?,?)", (q.quote_id, principal, row["task"], canonical(q.model_dump()).decode(), state, canonical(transcript).decode()))
                result = {"status": state, "quote": q.model_dump(), "transcript": transcript}
            else:
                raise ExchangeFailure("policy", "unknown negotiation action")
            db.execute("INSERT INTO negotiations VALUES(?,?,?,?)", (principal, key, digest(value), canonical(result).decode()))
            store.event("quote." + result["status"], peer["id"], principal, db=db, quote_id=result.get("quote", {}).get("quote_id"))
        return result

    @app.post("/admissions/{order_id}")
    async def admission(order_id: str, request: Request):
        if request.state.principal != "buyer":
            raise HTTPException(403)
        value = await request.json()
        with store.connect() as db:
            row, q = get_quote(value.get("quote_id"), "buyer", db)
            prior = db.execute("SELECT receipt FROM admissions WHERE order_id=? AND principal='buyer'", (order_id,)).fetchone()
        if row["state"] != "accepted" or q.mode != "simulator":
            raise ExchangeFailure("payment", "accepted simulator quote required")
        reqs = requirements(q)
        header = request.headers.get("payment-signature")
        if not header:
            if not prior:
                q.valid()
                registered = await client.http("ledger", "POST", "/quotes", json=q.model_dump())
                registered.raise_for_status()
            challenge = PaymentRequired(accepts=[reqs], resource=ResourceInfo(url=peer["url"]+f"/admissions/{order_id}", mime_type="application/json"),
                                        extensions={"payment-identifier": declare_payment_identifier_extension()})
            return JSONResponse({"mode": "simulator", "scheme": "leo-sim-v1", "quote_id": q.quote_id}, 402,
                                headers={"PAYMENT-REQUIRED": encode_payment_required_header(challenge)})
        try:
            payment = decode_payment_signature_header(header)
            if not isinstance(payment, PaymentPayload) or payment.x402_version != 2 or payment.accepted != reqs or set(payment.payload) != {"order_id", "binding", "authorization"} or payment.payload["order_id"] != order_id:
                raise ValueError("binding")
        except Exception:
            raise ExchangeFailure("payment", "invalid simulated payment payload") from None
        # Reconcile authoritative state before any settlement attempt. Never accept client receipts.
        response = await client.http("ledger", "GET", f"/orders/{order_id}")
        response.raise_for_status()
        order = response.json()
        if order["quote_id"] != q.quote_id or order["binding"] != payment.payload["binding"] or order["principal"] != "buyer":
            raise ExchangeFailure("payment", "order quote mismatch")
        with store.tx() as db:
            old = db.execute("SELECT quote_id FROM payment_attempts WHERE order_id=?", (order_id,)).fetchone()
            if old and old[0] != q.quote_id:
                raise ExchangeFailure("payment", "order changed quote")
            db.execute("INSERT INTO payment_attempts VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET state=excluded.state", (order_id, "outcome-unknown", q.quote_id))
        # Idempotent settlement validates the original authorization even on retries.
        response = await client.http("ledger", "POST", f"/orders/{order_id}/settle", json={k: payment.payload[k] for k in ("binding", "authorization")})
        if response.status_code == 409:
            # A known refusal (e.g. expired terms) is not a transport outage.
            # Keep the original attempt for reconciliation; only the ledger owns effects.
            return JSONResponse(response.json(), 409)
        response.raise_for_status()
        receipt = response.json()
        with store.tx() as db:
            db.execute("INSERT OR IGNORE INTO admissions VALUES(?,?,?,?)", (order_id, "buyer", q.input_digest, canonical(receipt).decode()))
            db.execute("UPDATE payment_attempts SET state='settled' WHERE order_id=?", (order_id,))
            store.event("payment.admitted", peer["id"], "buyer", db=db, order_id=order_id, quote_id=q.quote_id, trace_id=order["run_id"])
        wire = SettleResponse(success=True, transaction=order_id, network="leo:local", payer="buyer")
        return JSONResponse({"ticket": order_id, "receipt": receipt, "mode": "simulator"}, headers={"PAYMENT-RESPONSE": encode_payment_response_header(wire)})

    @app.get("/quotes")
    async def quotes(request: Request):
        if request.state.principal not in ("observer", "operator"):
            raise HTTPException(403)
        with store.connect() as db:
            rows = db.execute("SELECT quote,state,transcript FROM offers ORDER BY rowid DESC LIMIT 50").fetchall()
            uncertain = [dict(r) for r in db.execute("SELECT * FROM payment_attempts WHERE state='outcome-unknown'")]
        return {"quotes": [{"quote": json.loads(r[0]), "state": r[1], "transcript": json.loads(r[2])} for r in rows], "unresolved": uncertain}


def validate_admission(store, order_id, principal, payload, key):
    with store.connect() as db:
        row = db.execute("SELECT * FROM admissions WHERE order_id=? AND principal=?", (order_id, principal)).fetchone()
    if not row or row["input_digest"] != digest(payload) or key != order_id:
        raise ExchangeFailure("payment", "admission does not authorise this task/principal/operation")


async def paid_exchange(client, store, c, provider, task, run_id, *, quote=None, dispatch=True):
    with store.tx() as db:
        db.execute("CREATE TABLE IF NOT EXISTS payments(run_id TEXT PRIMARY KEY, quote TEXT, state TEXT, receipt TEXT)")
    with store.connect() as db:
        saved = db.execute("SELECT * FROM payments WHERE run_id=?", (run_id,)).fetchone()
    async def checked(peer, path, **kw):
        r = await client.http(peer, "POST", path, **kw)
        if r.status_code == 409:
            body = r.json()
            raise ExchangeFailure(body.get("category", "payment"), body.get("error", "payment refused"))
        r.raise_for_status()
        return r.json()
    if saved:
        q = Quote.model_validate_json(saved["quote"])
    else:
        offered = {'status':'offered','quote':quote} if quote else await checked(provider, "/negotiate", json={"action": "request", "task": task, "mode": "simulator"}, headers={"Idempotency-Key": run_id + "-quote"})
        if offered["status"] == "input-required":
            raise ExchangeFailure("schema", "quote requires clarification before spending")
        q = Quote.model_validate(offered["quote"]).valid(provider=provider, principal="buyer", task=task)
        if q.amount > c["limits"]["per_task"]:
            raise ExchangeFailure("policy", "per-task budget exceeded")
        with store.tx() as db:
            db.execute("INSERT INTO payments VALUES(?,?,?,?)", (run_id, canonical(q.model_dump()).decode(), "quoted", None))
    # Stable acceptance/operation IDs permit restart without choosing a new order or nonce.
    await checked(provider, "/negotiate", json={"action": "accept", "quote_id": q.quote_id}, headers={"Idempotency-Key": run_id + "-accept"})
    order_response = await client.http("ledger", "GET", f"/orders/{run_id}")
    if order_response.status_code == 404:
        challenge = await client.http(provider, "POST", f"/admissions/{run_id}", json={"quote_id": q.quote_id})
        if challenge.status_code != 402 or decode_payment_required_header(challenge.headers["PAYMENT-REQUIRED"]).accepts != [requirements(q)]:
            raise ExchangeFailure("payment", "challenge changed accepted terms")
        store.event("payment.challenge", "buyer", provider, trace_id=run_id, order_id=run_id, quote_id=q.quote_id,
                    http_status=402, scheme="leo-sim-v1", challenge=decode_payment_required_header(challenge.headers["PAYMENT-REQUIRED"]).model_dump(by_alias=True))
        await checked("ledger", "/orders", json={"order_id": run_id, "quote_id": q.quote_id, "run_id": run_id})
    else:
        order_response.raise_for_status()
        order = order_response.json()
        if order["quote_id"] != q.quote_id:
            raise ExchangeFailure("payment", "persisted quote binding mismatch")
    authorised = await checked("ledger", f"/orders/{run_id}/authorise")
    with store.tx() as db:
        db.execute("UPDATE payments SET state='outcome-unknown' WHERE run_id=?", (run_id,))
    payment = PaymentPayload(accepted=requirements(q), payload={"order_id": run_id, "binding": authorised["binding"], "authorization": authorised["authorization"]},
                             extensions=append_payment_identifier_to_extensions({"payment-identifier": declare_payment_identifier_extension()}, run_id))
    admitted = await checked(provider, f"/admissions/{run_id}", json={"quote_id": q.quote_id}, headers={"PAYMENT-SIGNATURE": encode_payment_signature_header(payment)})
    store.event("payment.delivery_authorised", "buyer", provider, trace_id=run_id, order_id=run_id, quote_id=q.quote_id,
                http_status=200, receipt_hash=digest(admitted["receipt"]), retry_reason="reconcile_original_order" if saved else None)
    with store.tx() as db:
        db.execute("UPDATE payments SET state='settled',receipt=? WHERE run_id=?", (canonical(admitted["receipt"]).decode(), run_id))
    if not dispatch:
        return {"payment": {"mode": "simulator", "settled": q.amount, "asset": "CREDIT", "actual_money": 0, "receipt": admitted["receipt"]}}
    remote = await client.rpc(provider, "SendMessage", client.request(task, message_id=run_id), key=run_id, trace=run_id, headers={"X-Exchange-Order": run_id})
    return {"task": remote["task"], "payment": {"mode": "simulator", "settled": q.amount, "asset": "CREDIT", "actual_money": 0, "receipt": admitted["receipt"]}}
