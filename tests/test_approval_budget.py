"""Controlled-clock payment workflows through production ASGI handlers and SQLite.

Only the HTTP transport, quote clock and buyer worker scheduling are controlled.
No fake payment/selection/approval implementation, sockets, model calls or primary wallet.
The existing isolated runner supplies the outer validation lifecycle.
"""
import copy
import json
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from exchange import common, commerce, ledger, models, provider, quotes, registry
from exchange.client import PeerClient
from exchange.common import digest
from exchange.coordinator import Coordinator

TASK = {'service': 'requirements', 'source': 'Must: Preserve the exact approved terms.'}


@pytest.fixture
async def workflow(tmp_path, monkeypatch):
    directory = tmp_path / 'workflow'
    monkeypatch.setattr(common, 'DATA', directory)
    c = common.init_config()
    for module in (ledger, provider, registry):
        monkeypatch.setattr(module, 'DATA', directory)
    monkeypatch.setattr(commerce, 'config', lambda: c)

    class Clock(datetime):
        current = datetime(2030, 1, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(quotes, 'datetime', Clock)

    async def no_model(*args, **kwargs):
        raise AssertionError('This fixture workflow must not invoke a model')

    monkeypatch.setattr(models, 'call_model', no_model)
    buyer = Coordinator(c, directory)
    scheduled = []
    # Permit exact ordering between approval and execution; /run drives the saved run.
    monkeypatch.setattr(buyer, 'schedule', scheduled.append)
    apps = {'buyer': buyer.application(), 'registry': registry.make_registry(c),
            'ledger': ledger.make_ledger(c)}
    for name, peer in c['peers'].items():
        if 'services' in peer:
            apps[name] = provider.make_provider({**peer, 'delay': 0})
    origins = {c['peers'][name]['url']: app for name, app in apps.items()}

    class Workflow:
        config = c
        clock = Clock
        coordinator = buyer
        ledger = apps['ledger'].store
        before_request = None
        after_response = None

        def snapshot(self):
            with self.ledger.connect() as db:
                settlements = [tuple(r) for r in db.execute('SELECT * FROM settlements ORDER BY order_id')]
            tasks, admissions = {}, {}
            for name in ('requirements', 'csv', 'verifier'):
                with apps[name].store.connect() as db:
                    tasks[name] = [tuple(r) for r in db.execute('SELECT id,state,body FROM tasks ORDER BY id')]
                    admissions[name] = [tuple(r) for r in db.execute('SELECT * FROM admissions ORDER BY order_id')]
            return {'ledger': self.ledger.summary(), 'settlements': settlements,
                    'tasks': tasks, 'admissions': admissions}

        async def run(self, key, **changes):
            value = {'task': TASK, 'backend': 'fixture', 'payment_mode': 'simulator',
                     'policy': 'cheapest', 'require_approval': True, **changes}
            return await PeerClient(c, 'operator').http('buyer', 'POST', '/run',
                json=value, headers={'Idempotency-Key': key})

        async def decide(self, pending, binding=None):
            return await PeerClient(c, 'operator').http('buyer', 'POST', '/approvals/'+pending['run_id'],
                json={'binding': binding or pending['approval']['binding'], 'approve': True})

        def approval(self, run_id):
            with buyer.store.connect() as db:
                return dict(db.execute('SELECT * FROM approvals WHERE run_id=?', (run_id,)).fetchone())

    w = Workflow()
    original_client = httpx.AsyncClient

    async def route(request):
        origin = f'{request.url.scheme}://{request.url.netloc.decode()}'
        assert origin in origins, 'Unexpected destination; fixture transport has no network fallback'
        if w.before_request:
            w.before_request(request)
        response = await httpx.ASGITransport(app=origins[origin], raise_app_exceptions=False).handle_async_request(request)
        if w.after_response:
            w.after_response(request, response)
        return response

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(route), **kw))
    async with AsyncExitStack() as stack:
        for app in apps.values():
            await stack.enter_async_context(app.app.router.lifespan_context(app.app))
        yield w


def expiry(pending):
    return datetime.fromisoformat(pending['approval']['preview']['quote']['expires_at'])


def assert_no_delivery(snapshot):
    assert not snapshot['settlements']
    assert not any(snapshot['tasks'].values())
    assert not any(snapshot['admissions'].values())
    assert snapshot['ledger']['accounts'] == {'buyer': 1000}


@pytest.mark.parametrize('offset', [-1, 0, 1])
async def test_pending_approval_exact_expiry_boundary(workflow, offset):
    w = workflow
    pending = (await w.run('boundary')).json()
    assert pending['status'] == 'approval-required'
    original = w.approval(pending['run_id'])
    before = w.snapshot()
    w.clock.current = expiry(pending) + timedelta(microseconds=offset)
    response = await w.decide(pending)
    if offset < 0:
        assert response.status_code == 200
        result = (await w.run('boundary')).json()
        assert result['status'] == 'verified'
        assert result['payment']['settled'] == pending['approval']['preview']['quote']['amount']
    else:
        assert response.status_code == 409
        assert 'expired' in response.json()['detail'].lower()
        assert 'new request' in response.json()['detail'].lower()
        assert w.approval(pending['run_id']) == original
        assert (await w.run('boundary')).json() == pending
        assert w.snapshot() == before
        assert_no_delivery(w.snapshot())


async def test_replacement_requires_new_identity_and_exact_binding(workflow):
    w = workflow
    old = (await w.run('old')).json()
    w.clock.current = expiry(old)
    assert (await w.decide(old)).status_code == 409
    replacement = (await w.run('replacement')).json()
    assert replacement['run_id'] != old['run_id']
    assert replacement['approval']['preview']['quote']['quote_id'] != old['approval']['preview']['quote']['quote_id']
    assert (await w.decide(replacement, old['approval']['binding'])).status_code == 409
    preview = replacement['approval']['preview']
    # The HTTP endpoint must refuse a digest for any altered protected term.
    for field, value in [('run_id', 'other-run'), ('provider', 'other-provider'), ('task', {**TASK, 'source': 'changed'})]:
        changed = copy.deepcopy(preview); changed[field] = value
        assert (await w.decide(replacement, digest(changed))).status_code == 409
    for field, value in [('amount', preview['quote']['amount']+1), ('payee', 'other-payee'),
                         ('asset', 'OTHER'), ('network', 'other:network'), ('expires_at', old['approval']['preview']['quote']['expires_at'])]:
        changed = copy.deepcopy(preview); changed['quote'][field] = value
        assert (await w.decide(replacement, digest(changed))).status_code == 409
    assert_no_delivery(w.snapshot())
    assert (await w.decide(replacement)).status_code == 200
    assert (await w.run('replacement')).json()['status'] == 'verified'
    assert w.approval(old['run_id'])['state'] == 'pending'
    assert json.loads(w.approval(old['run_id'])['preview']) == old['approval']['preview']
    assert len(w.snapshot()['settlements']) == 1


@pytest.mark.parametrize('stage,held_state', [('after-approval', None), ('before-authorise', 'reserved'), ('before-settle', 'authorised')])
async def test_approved_quote_expiring_before_new_effects(workflow, stage, held_state):
    w = workflow
    pending = (await w.run('delayed')).json(); run_id = pending['run_id']
    amount = pending['approval']['preview']['quote']['amount']
    assert (await w.decide(pending)).status_code == 200
    if stage == 'after-approval':
        w.clock.current = expiry(pending)
    else:
        action = 'authorise' if stage == 'before-authorise' else 'settle'

        def expire(request):
            if request.url.path == f'/orders/{run_id}/{action}':
                w.clock.current = expiry(pending)

        w.before_request = expire
    result = (await w.run('delayed')).json()
    state = w.snapshot()
    assert_no_delivery(state)
    # A known ledger refusal must not become a generic transport failure.
    assert result['status'] == 'failed' and result['failure_category'] == 'payment', result
    assert 'expired' in result['detail'].lower()
    if held_state:
        order = w.ledger.read(run_id, 'buyer')
        assert order['state'] == held_state and order['receipt'] is None
        assert state['ledger']['amounts'][held_state] == amount
        assert state['ledger']['available'] == 1000-amount
        # Existing explicit pre-settlement release, not an automatic refund/reset.
        release = await PeerClient(w.config).http('ledger', 'POST', f'/orders/{run_id}/release')
        assert release.status_code == 200 and release.json()['state'] == 'released'
        assert w.ledger.summary()['available'] == 1000
    else:
        assert state['ledger']['orders'] == [] and state['ledger']['available'] == 1000
    after = w.snapshot()
    assert (await w.run('delayed')).json() == result
    assert w.snapshot() == after
    assert w.approval(run_id)['state'] == 'approved'


@pytest.mark.parametrize('lost_at', [None, 'admission', 'settlement'])
async def test_committed_receipt_reconciles_after_expiry(workflow, lost_at):
    w = workflow
    pending = (await w.run('committed')).json(); run_id = pending['run_id']
    assert (await w.decide(pending)).status_code == 200
    if lost_at:
        target = '/admissions/'+run_id if lost_at == 'admission' else f'/orders/{run_id}/settle'

        def lose_once(request, response):
            if request.url.path == target and response.status_code == 200:
                w.after_response = None
                raise httpx.ReadTimeout('injected lost response after commit')

        w.after_response = lose_once
    first = (await w.run('committed')).json()
    assert first['status'] == ('outcome-unknown' if lost_at else 'verified')
    committed = w.snapshot()
    original_order = w.ledger.read(run_id, 'buyer')
    authorization_hash = digest(original_order['token'])
    assert len(committed['settlements']) == 1
    assert original_order['state'] == 'settled'
    w.clock.current = expiry(pending) + timedelta(days=1)
    result = (await w.run('committed')).json()
    assert result['status'] == 'verified', result
    assert result['payment']['receipt'] == json.loads(original_order['receipt'])
    assert w.snapshot()['ledger'] == committed['ledger']
    assert w.snapshot()['settlements'] == committed['settlements']
    assert digest(w.ledger.read(run_id, 'buyer')['token']) == authorization_hash
    if not lost_at:
        assert result == first and w.snapshot() == committed
    before = w.snapshot()
    assert (await w.run('committed')).json() == result
    assert w.snapshot() == before


async def test_no_affordable_quote_replay_and_changed_budget(workflow):
    w = workflow
    # Discover real configured offers; never assume which provider is cheapest.
    probe = (await w.run('quote-probe')).json()
    prices = [p['price'] for p in probe['decision']['candidate_set']]
    cap = min(prices)-1
    before = w.snapshot()
    rejected = (await w.run('too-small', max_credits=cap)).json()
    assert (await w.run('too-small', max_credits=cap)).json() == rejected
    assert (await w.run('too-small', max_credits=min(prices))).status_code == 409
    assert w.snapshot() == before
    assert_no_delivery(w.snapshot())
    assert rejected['status'] == 'failed' and rejected['failure_category'] == 'policy'
    assert 'budget' in rejected['detail'].lower(), rejected
    assert str(cap) in rejected['detail']
    assert 'new request' in rejected['detail'].lower()


async def test_exact_task_budget_and_mixed_offer_selection(workflow):
    w = workflow
    pending = (await w.run('offers')).json()
    candidates = pending['decision']['candidate_set']
    ordered = sorted(candidates, key=lambda p: (p['price'], p['peer']))
    known = ordered[1]
    before = w.snapshot()
    rejected = (await w.run('below', provider=known['peer'], max_credits=known['price']-1)).json()
    assert rejected['status'] == 'failed'
    assert w.snapshot() == before
    exact = (await w.run('equal', provider=known['peer'], max_credits=known['price'])).json()
    assert exact['approval']['preview']['provider'] == known['peer']
    assert (await w.decide(exact)).status_code == 200
    assert (await w.run('equal', provider=known['peer'], max_credits=known['price'])).json()['status'] == 'verified'
    mixed = (await w.run('mixed', policy='cheapest', max_credits=known['price'])).json()
    affordable = {p['peer'] for p in candidates if p['price'] <= known['price']}
    assert len(affordable) < len(candidates)
    assert {p['peer'] for p in mixed['decision']['candidate_set']} == affordable
    assert mixed['provider'] == ordered[0]['peer']
    assert (await w.decide(mixed)).status_code == 200
    result = (await w.run('mixed', policy='cheapest', max_credits=known['price'])).json()
    assert result['status'] == 'verified' and result['payment']['settled'] == ordered[0]['price']
    assert len(w.snapshot()['settlements']) == 2
    assert 'budget' in rejected['detail'].lower(), rejected


@pytest.mark.parametrize('limit', ['per_run', 'per_peer', 'global'])
@pytest.mark.parametrize('state', ['reserved', 'authorised', 'settled'])
async def test_held_and_settled_exposure_enforce_each_cap(workflow, limit, state):
    w = workflow
    pending = (await w.run('cap-probe')).json()
    q = pending['approval']['preview']['quote']; seller = q['provider']; amount = q['amount']
    # Fresh fixture ledger: lower one cap, keeping task affordability and other caps intact.
    w.config['limits'][limit] = amount
    buyer_client = PeerClient(w.config)
    seller_client = PeerClient(w.config, seller)
    first = await seller_client.http('ledger', 'POST', '/quotes', json=q)
    assert first.status_code == 200
    assert (await buyer_client.http('ledger', 'POST', '/orders', json={'order_id':'first','quote_id':q['quote_id'],'run_id':'shared'})).status_code == 200
    if state in ('authorised', 'settled'):
        auth = (await buyer_client.http('ledger', 'POST', '/orders/first/authorise')).json()
    if state == 'settled':
        response = await seller_client.http('ledger', 'POST', '/orders/first/settle',
            json={k: auth[k] for k in ('authorization', 'binding')})
        assert response.status_code == 200
    other = quotes.offer(seller, 'buyer', TASK, 'simulator', amount)
    assert (await seller_client.http('ledger', 'POST', '/quotes', json=other.model_dump())).status_code == 200
    before = w.snapshot()
    for _ in range(2):
        refused = await buyer_client.http('ledger', 'POST', '/orders', json={
            'order_id':'second','quote_id':other.quote_id,'run_id':'shared' if limit=='per_run' else 'new-run'})
        assert refused.status_code == 409 and refused.json()['category'] == 'policy'
        assert limit in refused.json()['error']
    assert w.snapshot() == before
    assert not any(before['tasks'].values()) and not any(before['admissions'].values())
    assert before['ledger']['conserved']
