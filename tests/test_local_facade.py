import asyncio
import copy
import uuid
import pytest
from exchange.local_facade import LocalExchange, VERSION


def request(op, **args):
    return {'version': VERSION, 'request_id': str(uuid.uuid4()), 'op': op, 'args': args}


def call(service, req):
    return asyncio.run(service.handle(req))['result']


def submit():
    return request('submit', task={'service': 'requirements', 'backend': 'fixture', 'source': 'Must: Explain one synthetic project.\nPreferred: Use three bullets.'})


def test_free_approval_replay_and_restart(tmp_path):
    f = LocalExchange(tmp_path)
    req = submit()
    pending = call(f, req)
    assert pending['status'] == 'approval-required'
    with f.client.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    decision = request('decide', run_id=pending['run_id'], binding=pending['approval']['binding'], approve=True)
    with pytest.raises(Exception):
        call(f, {**decision, 'request_id': str(uuid.uuid4()), 'args': {**decision['args'], 'binding': 'wrong'}})
    verified = call(f, decision)
    assert verified['status'] == 'verified', verified
    assert verified['verifier']['accepted'] and verified['payment']['actual_money'] == 0
    f.close()
    f = LocalExchange(tmp_path)
    try:
        assert call(f, decision) == verified
        assert call(f, req) == pending
        current = call(f, request('get', run_id=pending['run_id']))
        assert current['result']['task']['id'] == verified['task']['id']
        with f.client.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
        changed = copy.deepcopy(req)
        changed['args']['task']['source'] = 'Must: Something else.'
        with pytest.raises(ValueError, match='changed-content'):
            call(f, changed)
        with pytest.raises(Exception):
            call(f, request('decide', **{**decision['args'], 'approve': False}))
    finally:
        f.close()


def test_cancel_denial_and_no_permission_expansion(tmp_path):
    f = LocalExchange(tmp_path)
    try:
        p = call(f, submit())
        cancelled = call(f, request('cancel', run_id=p['run_id']))
        assert cancelled['status'] == 'cancelled'
        with pytest.raises(Exception):
            call(f, request('decide', run_id=p['run_id'], binding=p['approval']['binding'], approve=True))
        p = call(f, submit())
        result = call(f, request('decide', run_id=p['run_id'], binding=p['approval']['binding'], approve=False))
        assert result['status'] == 'failed'
        with f.client.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
        req = submit(); req['args']['task']['backend'] = 'live'
        with pytest.raises(ValueError):
            call(f, req)
    finally:
        f.close()


def test_crash_after_artifact_before_checkpoint_reconciles_once(tmp_path):
    f = LocalExchange(tmp_path)
    pending = call(f, submit())
    decision = request('decide', run_id=pending['run_id'], binding=pending['approval']['binding'], approve=True)
    checkpoint = f.coordinator.checkpoint
    def crash(run_id, body):
        if body.get('task_id'):
            raise asyncio.CancelledError()
        return checkpoint(run_id, body)
    f.coordinator.checkpoint = crash
    with pytest.raises(asyncio.CancelledError):
        call(f, decision)
    with f.client.store.connect() as db:
        before = db.execute('SELECT id FROM tasks').fetchone()[0]
    f.close()
    f = LocalExchange(tmp_path)
    try:
        receipt = call(f, decision)
        assert receipt['status'] == 'verified'
        assert receipt['task']['id'] == before
        with f.client.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
    finally:
        f.close()
