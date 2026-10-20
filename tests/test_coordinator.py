import asyncio

import pytest

from exchange.common import config, uid
from exchange.client import PeerClient

TASK={'service':'requirements','source':'Must: Preserve the task.\nPreferred: Compare evidence.'}


async def finished(client,run_id,waiting=()):
    for _ in range(100):
        r=await client.http('buyer','GET','/runs/'+run_id)
        r.raise_for_status()
        value=r.json()
        if value['status'] not in ('queued','running') or value['status'] in waiting: return value
        await asyncio.sleep(.05)
    raise AssertionError('buyer did not finish')


async def test_real_quotes_selection_feedback_and_async_duplicate():
    c=PeerClient(config(),'operator')
    key=uid()
    request={'task':TASK,'policy':'cheapest','payment_mode':'simulator'}
    ids=[]
    for _ in range(3):
        r=await c.http('buyer','POST','/submit',json=request,headers={'Idempotency-Key':key})
        assert r.status_code==202
        ids.append(r.json()['run_id'])
    assert len(set(ids))==1
    run=await finished(c,ids[0]); result=run['result']
    assert run['status']=='verified' and result['provider']=='csv'
    assert {p['peer']:p['price'] for p in result['decision']['candidate_set']}=={'requirements':5,'csv':3,'verifier':8}
    assert result['payment']['settled']==3
    history=(await c.http('buyer','GET','/performance?service=requirements&backend=fixture')).json()['history']
    assert history['csv']['verified']>=1 and history['csv']['mean_latency_ms']>0
    assert result['decision']['version']=='v2'


async def test_approval_binds_exact_quote_and_cannot_be_granted_by_agent():
    c=PeerClient(config(),'operator')
    before=(await c.http('ledger','GET','/summary')).json()['accounts']
    r=await c.http('buyer','POST','/run',json={'task':TASK,'payment_mode':'simulator','policy':'cheapest','require_approval':True},headers={'Idempotency-Key':uid()})
    pending=r.json(); run_id=pending['run_id']
    assert pending['status']=='approval-required'
    assert (await c.http('ledger','GET','/summary')).json()['accounts']==before
    binding=pending['approval']['binding']
    body={'binding':binding,'approve':True}
    agent=PeerClient(config())
    assert (await agent.http('buyer','POST','/approvals/'+run_id,json=body)).status_code==403
    assert (await c.http('buyer','POST','/approvals/'+run_id,json={**body,'binding':'forged'})).status_code==409
    events=(await c.http('buyer','GET','/integration/events')).json()['events']
    approval=next(e['envelope'] for e in events if e['envelope']['kind']=='approval.requested' and e['envelope']['trace_id']==run_id)
    assert approval['payload']['binding']==binding
    for _ in range(2): assert (await c.http('buyer','POST','/approvals/'+run_id,json=body)).status_code==200
    result=await finished(c,run_id)
    assert result['status']=='verified'
    after=(await c.http('ledger','GET','/summary')).json()['accounts']
    assert before['buyer']-after['buyer']==3
    assert (await c.http('buyer','POST','/approvals/'+run_id,json={**body,'approve':False})).status_code==409


async def test_declined_quote_does_not_spend():
    c=PeerClient(config(),'operator')
    before=(await c.http('ledger','GET','/summary')).json()['accounts']
    request={'task':TASK,'payment_mode':'simulator','require_approval':True}
    r=await c.http('buyer','POST','/run',json=request,headers={'Idempotency-Key':uid()})
    pending=r.json(); run_id=pending['run_id']
    await c.http('buyer','POST','/approvals/'+run_id,json={'binding':pending['approval']['binding'],'approve':False})
    result=await finished(c,run_id)
    assert result['status']=='failed' and result['result']['failure_category']=='policy'
    assert (await c.http('ledger','GET','/summary')).json()['accounts']==before


async def test_http_spans_link_buyer_provider_and_ledger():
    c=PeerClient(config(),'operator')
    r=await c.http('buyer','POST','/run',json={'task':TASK,'payment_mode':'simulator'},headers={'Idempotency-Key':uid()})
    run=r.json(); assert run['status']=='verified'
    events=[]
    for peer in ('buyer','requirements','ledger'):
        after=0
        while True:
            page=(await c.http(peer,'GET',f'/observe?after={after}')).json()['events']
            if not page: break
            events.extend(e for e in page if e['trace_id']==run['run_id'])
            after=page[-1]['seq']
    ids={e['span_id'] for e in events}
    linked=[e for e in events if e['kind']=='http.received' and e['target'] in ('requirements','ledger')]
    assert {e['target'] for e in linked}=={'requirements','ledger'}
    assert all(e['parent_id'] in ids for e in linked)
    assert any(e['kind']=='payment.settled' and e['parent_id'] in ids for e in events)
    assert any(e['kind']=='artifact.created' and e['parent_id'] in ids for e in events)
