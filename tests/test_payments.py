import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from exchange.common import config, uid, DATA, write_json
from exchange.client import PeerClient, checked_artifact
from exchange.failures import ExchangeFailure
from exchange.ledger import Ledger
from exchange.quotes import offer, Quote

LIMITS = {"per_task": 25, "per_run": 40, "per_peer": 50, "global": 70}
TASK = {"service": "requirements", "source": "Must: Retain evidence.\nPreferred: Clear logs."}


def setup_order(tmp_path, amount=5):
    ledger = Ledger(tmp_path / "ledger.sqlite", LIMITS)
    q = offer("seller", "buyer", TASK, "simulator", amount)
    ledger.register(q.model_dump(), "seller")
    order = ledger.reserve("order", q.quote_id, "run", "buyer")
    return ledger, q, order


def test_concurrent_retries_and_crash_after_authorisation(tmp_path):
    ledger, q, order = setup_order(tmp_path)
    auth = ledger.authorise("order", "buyer")
    restored = Ledger(tmp_path / "ledger.sqlite", LIMITS)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: restored.settle("order", "seller", auth["authorization"], order["binding"]), range(30)))
    assert all(r == results[0] for r in results)
    summary = restored.summary()
    assert summary["conserved"] and summary["accounts"] == {"buyer": 995, "seller": 5}
    assert summary["amounts"]["settled"] == 5
    # Lost settlement response / process crash before the provider commits delivery.
    again = Ledger(tmp_path / "ledger.sqlite", LIMITS)
    assert again.reserve("order", q.quote_id, "run", "buyer")["receipt"] == results[0]
    assert again.settle("order", "seller", auth["authorization"], order["binding"]) == results[0]
    with pytest.raises(ExchangeFailure):
        again.release("order", "buyer")


def test_wrong_payee_forgery_replay_and_principal(tmp_path):
    ledger, q, order = setup_order(tmp_path)
    auth = ledger.authorise("order", "buyer")
    for token, binding in [("forged", order["binding"]), (auth["authorization"], "other-task")]:
        with pytest.raises(ExchangeFailure):
            ledger.settle("order", "seller", token, binding)
    with pytest.raises(HTTPException):
        ledger.read("order", "mallory")
    with pytest.raises(ExchangeFailure):
        ledger.settle("order", "buyer", auth["authorization"], order["binding"])
    with pytest.raises(ExchangeFailure):
        ledger.reserve("new-order", q.quote_id, "run", "buyer")
    with pytest.raises(ExchangeFailure):
        ledger.register({**q.model_dump(), "payee": "mallory"}, "seller")
    assert ledger.summary()["accounts"]["buyer"] == 1000


def test_expiry_budget_release_and_storage_rollback(tmp_path):
    ledger, q, order = setup_order(tmp_path, 25)
    q2 = offer("seller", "buyer", TASK, "simulator", 20)
    ledger.register(q2.model_dump(), "seller")
    with pytest.raises(ExchangeFailure, match="per_run"):
        ledger.reserve("two", q2.quote_id, "run", "buyer")
    ledger.release("order", "buyer")
    ledger.reserve("two", q2.quote_id, "run", "buyer")
    assert ledger.summary()["available"] == 980
    expired = offer("seller", "buyer", TASK, "simulator").model_dump()
    expired["expires_at"] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    with pytest.raises(ExchangeFailure, match="expired"):
        ledger.register(expired, "seller")
    # Simulated storage failure inside transaction rolls back balance updates.
    auth = ledger.authorise("two", "buyer")
    original = ledger.event
    def disk_failure(*a, **kw):
        import sqlite3
        raise sqlite3.OperationalError("injected disk full")
    ledger.event = disk_failure
    with pytest.raises(Exception, match="disk full"):
        ledger.settle("two", "seller", auth["authorization"], auth["binding"])
    ledger.event = original
    assert ledger.summary()["accounts"] == {"buyer": 1000}
    assert ledger.read("two", "buyer")["state"] == "authorised"
    ledger.release("two", "buyer", failed=True)
    assert ledger.summary()["available"] == 1000


@pytest.mark.parametrize("amount", [1.5, True, -1, "2"])
def test_no_float_or_coerced_balances(amount):
    with pytest.raises(ValidationError):
        offer("seller", "buyer", TASK, "simulator", amount)


async def test_real_http_payment_delivery_and_duplicate():
    client = PeerClient(config(), "operator")
    key = uid()
    results = []
    for _ in range(2):
        response = await client.http("buyer", "POST", "/run", json={"task": TASK, "payment_mode": "simulator"}, headers={"Idempotency-Key": key})
        response.raise_for_status()
        results.append(response.json())
    assert results[0] == results[1]
    assert results[0]["status"] == "verified", results[0]
    assert results[0]["payment"]["settled"] == 5
    ledger = (await client.http("ledger", "GET", "/summary")).json()
    order = [o for o in ledger["orders"] if o["id"] == results[0]["run_id"]]
    assert len(order) == 1 and ledger["conserved"]
    buyer = PeerClient(config())
    original = results[0]["task"]
    task = await buyer.rpc("requirements", "GetTask", {"id": original["id"]})
    assert checked_artifact(task, TASK)["accepted"]
    with pytest.raises(RuntimeError):
        await buyer.rpc("requirements", "SendMessage", buyer.request({**TASK, "source": "different"}), key=results[0]["run_id"], headers={"X-Exchange-Order": results[0]["run_id"]})
    other = PeerClient(config(), "test-other")
    assert (await other.http("ledger", "GET", "/orders/" + results[0]["run_id"])).status_code == 404
    write_json(DATA / "receipts" / ("payment-http-" + key + ".json"), {"result": results[0], "duplicate_same": True, "ledger_conserved": ledger["conserved"]})


async def test_bounded_negotiation_and_renewed_acceptance():
    client = PeerClient(config())
    async def negotiate(value):
        return await client.http("requirements", "POST", "/negotiate", json=value, headers={"Idempotency-Key": uid()})
    first = (await negotiate({"task": TASK, "mode": "simulator"})).json()
    qid = first["quote"]["quote_id"]
    counter = (await negotiate({"action": "counter", "quote_id": qid, "amount": 3})).json()
    assert counter["quote"]["quote_id"] != qid
    assert (await negotiate({"action": "accept", "quote_id": qid})).status_code == 409
    final = (await negotiate({"action": "counter", "quote_id": counter["quote"]["quote_id"], "amount": 2})).json()
    assert (await negotiate({"action": "counter", "quote_id": final["quote"]["quote_id"], "amount": 2})).status_code == 409
    accepted = await negotiate({"action": "accept", "quote_id": final["quote"]["quote_id"]})
    assert accepted.json()["status"] == "accepted"
    assert len(accepted.json()["transcript"]) == 7


async def test_lost_admission_response_reconciles_before_retry(tmp_path):
    import httpx
    from exchange.commerce import paid_exchange
    from exchange.common import Database
    client = PeerClient(config())
    store = Database(tmp_path / 'buyer.sqlite')
    run = uid()
    original = client.http
    lost = False
    async def lose_once(peer, method, path, **kw):
        nonlocal lost
        response = await original(peer, method, path, **kw)
        if path == '/admissions/' + run and response.status_code == 200 and not lost:
            lost = True
            raise httpx.ReadTimeout('injected response lost after provider committed admission')
        return response
    client.http = lose_once
    with pytest.raises(httpx.ReadTimeout):
        await paid_exchange(client, store, config(), 'requirements', TASK, run)
    with store.connect() as db:
        assert db.execute('SELECT state FROM payments WHERE run_id=?',(run,)).fetchone()[0] == 'outcome-unknown'
    before = (await original('ledger','GET','/summary')).json()['accounts']
    client.http = original
    restored = Database(tmp_path / 'buyer.sqlite')
    result = await paid_exchange(client, restored, config(), 'requirements', TASK, run)
    assert checked_artifact(result['task'],TASK)['accepted']
    assert (await original('ledger','GET','/summary')).json()['accounts'] == before
    again = await paid_exchange(client, restored, config(), 'requirements', TASK, run)
    assert again['task']['id'] == result['task']['id']


async def test_invalid_scope_and_types_rejected_before_quote_or_payment():
    client = PeerClient(config())
    for payload in ({'task':{**TASK,'delegate_to':'buyer'},'mode':'simulator'}, {'task':TASK,'mode':'mainnet'}):
        response = await client.http('requirements','POST','/negotiate',json=payload,headers={'Idempotency-Key':uid()})
        assert response.status_code in (409,422)
    response = await client.http('ledger','POST','/orders',json={'order_id':False})
    assert response.status_code == 422
