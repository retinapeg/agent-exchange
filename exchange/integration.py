"""Project-local adapter envelopes, explicitly distinct from A2A wire objects."""
import asyncio
import json
from datetime import datetime, timezone

import jsonschema

from exchange.common import ROOT, DATA, Database, canonical, digest, now, uid
from exchange.client import checked_artifact
from exchange.failures import ExchangeFailure

SCHEMA = json.loads((ROOT / 'integration/envelope.schema.json').read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


def envelope(kind, source, target, payload, *, trace=None, correlation=None, causation=None, key=None):
    identity = uid()
    value = dict(schema_version='leo.integration.v1', message_id=identity, trace_id=trace or uid(), correlation_id=correlation or identity,
                 causation_id=causation, source=source, target=target, kind=kind, created_at=now(), deadline_at=None,
                 idempotency_key=key or identity, payload=payload)
    VALIDATOR.validate(value)
    return value


class Adapter(Database):
    def __init__(self, path, client, sources=('continuum-stub',)):
        super().__init__(path)
        self.client, self.sources, self.locks = client, set(sources), {}
        with self.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS inbox(seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, message_id TEXT, key TEXT, digest TEXT, response TEXT,
              UNIQUE(source,message_id), UNIQUE(source,key));
            CREATE TABLE IF NOT EXISTS cursor(source TEXT PRIMARY KEY, seq INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS owned(source TEXT, provider TEXT, task_id TEXT, PRIMARY KEY(source,provider,task_id));
            ''')

    async def receive(self, value, authenticated_source):
        VALIDATOR.validate(value)
        if authenticated_source not in self.sources or value['source'] != authenticated_source or value['target'] != 'agent-exchange':
            raise ExchangeFailure('authentication', 'adapter source/target not authorised')
        if value['deadline_at'] and datetime.fromisoformat(value['deadline_at'].replace('Z','+00:00')) <= datetime.now(timezone.utc):
            raise ExchangeFailure('policy', 'expired integration request')
        source, message = value['source'], value['message_id']
        async with self.locks.setdefault((source, message), asyncio.Lock()):
            with self.tx() as db:
                old = db.execute('SELECT * FROM inbox WHERE source=? AND (message_id=? OR key=?)', (source, message, value['idempotency_key'])).fetchone()
                if old:
                    if old['digest'] != digest(value):
                        raise ExchangeFailure('policy', 'integration changed-content reuse')
                    if old['response']:
                        return json.loads(old['response'])
                else:
                    db.execute('INSERT INTO inbox(source,message_id,key,digest) VALUES(?,?,?,?)', (source, message, value['idempotency_key'], digest(value)))
            payload = value['payload']
            provider = payload.get('provider')
            if provider not in self.client.c['peers'] or 'services' not in self.client.c['peers'][provider]:
                raise ExchangeFailure('policy', 'unconfigured provider')
            key = digest([source, message])
            if value['kind'] == 'task.requested':
                task = (await self.client.rpc(provider, 'SendMessage', self.client.request(payload['task'], message_id=message), key=key, trace=value['trace_id']))['task']
                verdict = checked_artifact(task, payload['task'])
                kind = 'task.completed' if verdict['accepted'] else 'task.failed' if task['status']['state'] in ('TASK_STATE_FAILED','TASK_STATE_COMPLETED','TASK_STATE_REJECTED') else 'task.progress'
                with self.tx() as db:
                    db.execute('INSERT OR IGNORE INTO owned VALUES(?,?,?)', (source, provider, task['id']))
            elif value['kind'] == 'task.cancel.requested':
                with self.connect() as db:
                    owner = db.execute('SELECT 1 FROM owned WHERE source=? AND provider=? AND task_id=?', (source, provider, payload['task_id'])).fetchone()
                if not owner:
                    raise ExchangeFailure('authentication', 'source does not own this task')
                task = await self.client.rpc(provider, 'CancelTask', {'id':payload['task_id']}, key=key, trace=value['trace_id'])
                verdict, kind = None, 'task.cancelled'
            else:
                raise ExchangeFailure('policy', 'adapter only dispatches task.requested and task.cancel.requested')
            result = envelope(kind, 'agent-exchange', source, {'provider':provider,'task':task,'verifier':verdict},
                              trace=value['trace_id'], correlation=value['correlation_id'], causation=message, key=key)
            with self.tx() as db:
                db.execute('UPDATE inbox SET response=? WHERE source=? AND message_id=?', (canonical(result).decode(), source, message))
                # Cursor advances only over fully processed, contiguous messages for this source.
                pending = db.execute('SELECT MIN(seq) FROM inbox WHERE source=? AND response IS NULL', (source,)).fetchone()[0]
                seq = db.execute('SELECT MAX(seq) FROM inbox WHERE source=? AND response IS NOT NULL AND seq<?', (source, pending or 2**63-1)).fetchone()[0] or 0
                db.execute('INSERT INTO cursor VALUES(?,?) ON CONFLICT(source) DO UPDATE SET seq=MAX(cursor.seq,excluded.seq)', (source, seq))
            return result

    def observed(self, source, after=0):
        with self.connect() as db:
            return [{'seq':r['seq'], 'envelope':json.loads(r['response'])} for r in db.execute('SELECT seq,response FROM inbox WHERE source=? AND seq>? AND response IS NOT NULL ORDER BY seq LIMIT 100', (source, after))]


class ObserverAdapter(Database):
    """Project-local Leo OS stub: durable observations and exact approval previews.

    Authentication is supplied by the configured HTTP channel, never by an
    envelope's self-asserted source. No actual Leo OS endpoint is accessed.
    """
    def __init__(self, path):
        super().__init__(path)
        with self.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS notifications(seq INTEGER PRIMARY KEY,message_id TEXT UNIQUE,digest TEXT,body TEXT)')

    def cursor(self):
        with self.connect() as db:
            return db.execute('SELECT COALESCE(MAX(seq),0) FROM notifications').fetchone()[0]

    def receive(self, seq, value, authenticated_source):
        VALIDATOR.validate(value)
        if authenticated_source!='agent-exchange' or value['source']!=authenticated_source or value['target']!='leo-os-stub':
            raise ExchangeFailure('authentication','observer envelope source/target not authorised')
        if value['kind'] not in ('approval.requested','task.progress','task.completed','task.failed','task.cancelled'):
            raise ExchangeFailure('policy','unsupported observer notification')
        if value['kind']=='approval.requested':
            p=value['payload']
            if not {'approval_id','preview','binding'} <= set(p) or digest(p['preview'])!=p['binding']:
                raise ExchangeFailure('policy','approval preview binding mismatch')
        fingerprint=digest(value)
        with self.tx() as db:
            old=db.execute('SELECT * FROM notifications WHERE seq=? OR message_id=?',(seq,value['message_id'])).fetchone()
            if old:
                if old['seq']!=seq or old['digest']!=fingerprint: raise ExchangeFailure('policy','observer changed-content replay')
                return
            if type(seq) is not int or seq!=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM notifications').fetchone()[0]:
                raise ExchangeFailure('policy','observer cursor gap')
            db.execute('INSERT INTO notifications VALUES(?,?,?,?)',(seq,value['message_id'],fingerprint,canonical(value).decode()))

    async def decide(self, client, approval_id, binding, approve):
        # Only an explicit operator credential can reach the buyer's decision API.
        if client.principal!='operator' or type(approve) is not bool:
            raise ExchangeFailure('authentication','operator decision required')
        with self.connect() as db:
            known=any((p:=json.loads(r[0]))['kind']=='approval.requested' and p['payload']['approval_id']==approval_id and p['payload']['binding']==binding
                      for r in db.execute('SELECT body FROM notifications'))
        if not known: raise ExchangeFailure('policy','approval preview has not been received')
        response=await client.http('buyer','POST','/approvals/'+approval_id,json={'binding':binding,'approve':approve})
        response.raise_for_status()
        return response.json()
