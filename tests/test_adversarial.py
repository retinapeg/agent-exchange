import asyncio
import json

import httpx
import pytest
from a2a import types as t
from a2a.server.context import ServerCallContext

from exchange.common import config, uid, Database
from exchange.client import PeerClient, checked_artifact
from exchange.provider import Provider
from exchange.tasks import TaskStore, proto
from exchange.services import execute
from exchange.security import NetworkPolicy
from exchange.failures import category, ExchangeFailure


async def test_cancellation_race_cannot_publish_late_artifact(tmp_path):
    store = TaskStore(tmp_path / 'task.sqlite', 'requirements')
    provider = Provider({'id':'requirements','services':['requirements'],'delay':.05}, store)
    ctx = ServerCallContext(state={'principal':'buyer','headers':{'idempotency-key':'cancel-race'}})
    params = proto(PeerClient(config()).request({'service':'requirements','source':'Must: retained'}, immediate=True), t.SendMessageRequest)
    task_id = await provider.start(params, ctx)
    await asyncio.sleep(.01)
    await provider.on_cancel_task(t.CancelTaskRequest(id=task_id), ctx)
    await asyncio.gather(*list(provider.workers.values()), return_exceptions=True)
    row = store.get(task_id, 'buyer')
    assert row['state'] == 'TASK_STATE_CANCELED'
    assert 'artifacts' not in json.loads(row['body'])


async def test_paid_seller_failure_retains_charge_and_no_poll_charge(tmp_path, monkeypatch):
    # Same paid_exchange code, real provider/ledger sockets; invalid CSV fails only after admission.
    client = PeerClient(config(), 'operator')
    key = uid()
    payload = {'task':{'service':'csv-audit','source':'a,a\n1,2\n','ranges':{}},'payment_mode':'simulator'}
    response = await client.http('buyer','POST','/run',json=payload,headers={'Idempotency-Key':key})
    result = response.json()
    assert result['task']['status']['state'] == 'TASK_STATE_FAILED'
    assert result['payment']['settled'] == 5 and not result['verifier']['accepted']
    before = (await client.http('ledger','GET','/summary')).json()['accounts']
    for _ in range(3):
        await PeerClient(config()).rpc('csv','GetTask',{'id':result['task']['id']})
    assert (await client.http('ledger','GET','/summary')).json()['accounts'] == before


async def test_no_silent_paid_fallback_and_cyclic_delegation():
    client = PeerClient(config(), 'operator')
    before = (await client.http('ledger','GET','/summary')).json()['accounts']
    r = await client.http('buyer','POST','/run',json={'task':{'service':'nonexistent','delegate_to':'buyer'}},headers={'Idempotency-Key':uid()})
    assert r.json()['status'] == 'failed'
    assert (await client.http('ledger','GET','/summary')).json()['accounts'] == before
    r = await client.http('buyer','POST','/run',json={'task':{'service':'requirements','source':'x'},'payment_mode':'mainnet'},headers={'Idempotency-Key':uid()})
    assert r.status_code == 422


async def test_redirect_and_oversize_responses(monkeypatch):
    original = httpx.AsyncClient
    for response in [httpx.Response(302, headers={'Location':'http://169.254.169.254:80/'}), httpx.Response(200,content=b'x'*100)]:
        transport = httpx.MockTransport(lambda request: response)
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
        with pytest.raises(ValueError):
            await NetworkPolicy(['http://127.0.0.1:9000']).request('GET','http://127.0.0.1:9000/a',limit=50)


def test_all_error_categories_are_distinct():
    from exchange.failures import CATEGORIES
    assert {category(ExchangeFailure(c, 'fixture')) for c in CATEGORIES} == CATEGORIES


async def test_observer_is_read_only_and_invalid_json_is_rejected():
    from exchange.common import config
    observer = PeerClient(config(),'observer')
    with pytest.raises(RuntimeError):
        await observer.rpc('requirements','SendMessage',observer.request({'service':'requirements','source':'Must: denied'}))
    assert (await observer.http('ledger','POST','/orders',json={'order_id':'x','quote_id':'q','run_id':'r'})).status_code == 409
    client = PeerClient(config())
    result = await client.http('buyer','POST','/run',content='{',headers={'Content-Type':'application/json','Idempotency-Key':uid()})
    assert result.status_code == 400
