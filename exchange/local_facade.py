"""App-owned, payment-independent deterministic Exchange interface over private pipes."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import sys
from uuid import UUID

from a2a import types as t
from .client import PeerClient, checked_artifact
from .common import canonical, digest
from .contracts import task_schema
from .coordinator import Coordinator
from .services import execute
from .tasks import TaskStore, proto

VERSION = 'leo.exchange.v1'
LIMITS = {'source_chars': 12000, 'service': 'requirements', 'backend': 'fixture',
          'network': False, 'shell': False, 'paid_calls': False, 'wall_seconds': 5}


class DeterministicClient:
    """Same typed task store and verifier; no registry, ledger, HTTP or model path."""
    request = PeerClient.request

    def __init__(self, directory):
        self.store = TaskStore(directory / 'provider/tasks.sqlite', 'local-requirements')
        self.store.recover()

    async def rpc(self, peer, method, params, *, key=None, trace=None, headers=None):
        if peer != 'local-requirements' or headers:
            raise ValueError('unapproved provider or payment')
        if method == 'SendMessage':
            payload = params['message']['parts'][0]['data']
            validate_task(payload)
            task_id, created = self.store.submit(proto(params, t.SendMessageRequest), 'buyer', key, trace)
            if created:
                self.store.transition(task_id, 'TASK_STATE_WORKING')
                try:
                    artifact = execute(payload)
                    self.store.transition(task_id, 'TASK_STATE_COMPLETED', artifact=artifact)
                except Exception:
                    self.store.transition(task_id, 'TASK_STATE_FAILED', failure='provider')
            return {'task': json.loads(self.store.get(task_id, 'buyer')['body'])}
        if method not in ('GetTask', 'CancelTask'):
            raise ValueError('unsupported method')
        if method == 'CancelTask':
            self.store.cancel(params['id'], 'buyer')
        return json.loads(self.store.get(params['id'], 'buyer')['body'])


def validate_task(task):
    if not isinstance(task, dict) or set(task) != {'service', 'source', 'backend'} or task.get('service') != 'requirements' or task.get('backend') != 'fixture':
        raise ValueError('only deterministic requirements preparation is permitted')
    task_schema(task, ['requirements'])
    if not 1 <= len(task['source']) <= LIMITS['source_chars']:
        raise ValueError('source length exceeds approved limit')


class LocalExchange:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = (directory / 'exchange.lock').open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.lock.close()
            raise
        self.client = DeterministicClient(directory)
        config = {'limits': {'per_task': 0}, 'peers': {'local-requirements': {'services': ['requirements']}}}
        self.coordinator = Coordinator(config, directory, client=self.client)
        with self.coordinator.store.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS facade_requests(id TEXT PRIMARY KEY, hash TEXT NOT NULL, response TEXT)')

    def close(self):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    async def handle(self, request):
        if set(request) != {'version', 'request_id', 'op', 'args'} or request['version'] != VERSION:
            raise ValueError('unsupported envelope')
        UUID(request['request_id'])
        op, a = request['op'], request['args']
        fields = {'health': set(), 'snapshot': set(), 'submit': {'task'}, 'get': {'run_id'},
                  'decide': {'run_id', 'binding', 'approve'}, 'cancel': {'run_id'}, 'events': {'after'}}
        if op not in fields or not isinstance(a, dict) or set(a) != fields[op]:
            raise ValueError('unknown operation or fields')
        c = self.coordinator
        mutation = op in ('submit', 'decide', 'cancel')
        if mutation:
            with c.store.tx() as db:
                old = db.execute('SELECT * FROM facade_requests WHERE id=?', (request['request_id'],)).fetchone()
                if old:
                    if old['hash'] != digest(request):
                        raise ValueError('changed-content replay')
                    if old['response']:
                        return json.loads(old['response'])
                else:
                    db.execute('INSERT INTO facade_requests VALUES(?,?,NULL)', (request['request_id'], digest(request)))
        value = await self.perform(op, a, request['request_id'])
        result = {'version': VERSION, 'request_id': request['request_id'], 'result': value}
        if mutation:
            with c.store.tx() as db:
                db.execute('UPDATE facade_requests SET response=? WHERE id=?', (canonical(result).decode(), request['request_id']))
        return result

    async def perform(self, op, a, key):
        c = self.coordinator
        if op == 'health':
            return {'status': 'ok', 'mode': 'deterministic-only', 'limits': LIMITS, 'pid': os.getpid()}
        if op == 'submit':
            validate_task(a['task'])
            value = {'task': a['task'], 'provider': 'local-requirements', 'backend': 'fixture',
                     'payment_mode': 'free', 'require_approval': True, 'max_credits': 0}
            run_id = c.admit(value, 'operator', key)
            with c.store.connect() as db:
                saved = db.execute('SELECT body FROM checkpoints WHERE run_id=?', (run_id,)).fetchone()
            if not saved:
                c.checkpoint(run_id, {'task': a['task'], 'provider': 'local-requirements', 'plan': None, 'quote': None,
                                     'limits': LIMITS, 'decision': {'policy': 'fixed-local-deterministic-v1'}})
            return await c.execute(run_id)
        if op == 'decide':
            # Only the owning app has this private pipe; Leo records the human decision first.
            c.decide(a['run_id'], {'binding': a['binding'], 'approve': a['approve']}, 'operator')
            return await c.execute(a['run_id'])
        if op == 'cancel':
            run_id = a['run_id']
            row = c.saved(run_id)
            if row['status'] == 'cancelled':
                return json.loads(row['response'])
            if row['status'] not in ('approval-required', 'queued', 'interrupted', 'outcome-unknown'):
                raise ValueError('run is already terminal')
            with c.store.connect() as db:
                checkpoint = json.loads(db.execute('SELECT body FROM checkpoints WHERE run_id=?', (run_id,)).fetchone()[0])
            if checkpoint.get('task_id'):
                await self.client.rpc(checkpoint['provider'], 'CancelTask', {'id': checkpoint['task_id']})
            with c.store.tx() as db:
                db.execute("UPDATE approvals SET state='cancelled' WHERE run_id=?", (run_id,))
            return c.finish(run_id, {'run_id': run_id, 'status': 'cancelled'})
        if op == 'get':
            row = c.saved(a['run_id'])
            # Reconcile an interrupted approved request through the same task key/checkpoint.
            if row['status'] in ('queued', 'running', 'interrupted', 'outcome-unknown') and not row['response']:
                await c.execute(a['run_id'])
            view = c.view(a['run_id'])
            result = view.get('result') or {}
            if result.get('status') == 'verified':
                with c.store.connect() as db:
                    task = json.loads(db.execute('SELECT body FROM checkpoints WHERE run_id=?', (a['run_id'],)).fetchone()[0])['task']
                if not checked_artifact(result['task'], task)['accepted']:
                    raise ValueError('stored receipt failed verification')
            return view
        if op == 'snapshot':
            with c.store.connect() as db:
                ids = [r[0] for r in db.execute('SELECT id FROM runs ORDER BY rowid DESC LIMIT 10')]
            return {'runs': [await self.perform('get', {'run_id': i}, key) for i in ids]}
        if op == 'events':
            if type(a['after']) is not int or a['after'] < 0:
                raise ValueError('invalid cursor')
            with c.store.connect() as db:
                return {'events': [dict(r) for r in db.execute('SELECT seq,body FROM outbox WHERE seq>? ORDER BY seq LIMIT 10', (a['after'],))]}
        raise ValueError('unsupported operation')


async def main():
    os.umask(0o077)
    service = LocalExchange(Path(sys.argv[1]).resolve())
    try:
        while line := sys.stdin.buffer.readline(262145):
            try:
                if len(line) > 262144:
                    raise ValueError('message too large')
                result = await service.handle(json.loads(line))
            except Exception as error:
                result = {'error': str(error)[:240]}
            print(canonical(result).decode(), flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    asyncio.run(main())
