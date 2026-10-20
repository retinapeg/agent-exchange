"""Durable buyer workflow; HTTP owns dispatch and deterministic policy owns spending."""
import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from exchange.common import Database, canonical, digest, uid, now
from exchange.client import PeerClient, checked_artifact
from exchange.contracts import task_schema
from exchange.failures import category, ExchangeFailure
from exchange.quotes import Quote
from exchange.security import Guard
from exchange.tracing import trace_scope

WAITING = {'approval-required', 'input-required', 'outcome-unknown', 'interrupted'}


class Coordinator:
    def __init__(self, config, directory):
        self.c, self.directory = config, directory
        self.client = PeerClient(config)
        self.store = Database(directory / 'buyer/buyer.sqlite')
        self.locks, self.workers = {}, {}
        self.slots = asyncio.Semaphore(4)
        with self.store.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, principal TEXT, key TEXT, digest TEXT, request TEXT, response TEXT, status TEXT, UNIQUE(principal,key));
            CREATE TABLE IF NOT EXISTS checkpoints(run_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS progress(run_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback(run_id TEXT PRIMARY KEY, provider TEXT, service TEXT, backend TEXT,
              verified INTEGER, latency_ms INTEGER, cost INTEGER, failure TEXT);
            CREATE TABLE IF NOT EXISTS approvals(run_id TEXT PRIMARY KEY, binding TEXT, preview TEXT, state TEXT,
              requested_at TEXT, decided_at TEXT, decided_by TEXT);
            CREATE TABLE IF NOT EXISTS outbox(seq INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE, body TEXT);
            ''')

    def validate(self, value):
        fields = {'task','policy','seed','natural_request','backend','payment_mode','provider','require_approval','max_credits'}
        if not isinstance(value, dict) or set(value)-fields or ('task' in value)==('natural_request' in value):
            raise HTTPException(422, 'Supply one task or natural_request; unknown fields are refused')
        if value.get('payment_mode','free') not in ('free','simulator') or value.get('backend','fixture') not in ('fixture','live'):
            raise HTTPException(422, 'Only fixture/live and free/simulator are supported')
        if value.get('policy','fixed') not in ('fixed','random','cheapest','reliability','ucb'):
            raise HTTPException(422, 'Unknown selection policy')
        if type(value.get('seed',0)) is not int or type(value.get('require_approval',False)) is not bool:
            raise HTTPException(422, 'Invalid policy settings')
        if type(value.get('max_credits',25)) is not int or not 0 <= value.get('max_credits',25) <= self.c['limits']['per_task']:
            raise HTTPException(422, 'Invalid simulator task cap')
        if 'natural_request' in value:
            if not isinstance(value['natural_request'],str) or not 1 <= len(value['natural_request']) <= 64000 or value.get('backend')!='live':
                raise HTTPException(422, 'Natural-language planning requires explicit live mode and bounded text')
        elif not isinstance(value['task'],dict):
            raise HTTPException(422, 'task must be an object')
        if 'provider' in value and value['provider'] not in self.c['peers']:
            raise HTTPException(422, 'Unconfigured provider')

    def admit(self, value, principal, key):
        if principal not in ('operator','buyer'):
            raise HTTPException(403)
        self.validate(value)
        if not key or len(key)>128:
            raise HTTPException(400,'idempotency-key required')
        with self.store.tx() as db:
            row=db.execute('SELECT * FROM runs WHERE principal=? AND key=?',(principal,key)).fetchone()
            if row:
                if row['digest'] != digest(value):
                    raise HTTPException(409,'changed-content reuse')
                return row['id']
            if db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]>=32:
                raise HTTPException(429,'Buyer queue is full')
            run_id=uid()
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',(run_id,principal,key,digest(value),canonical(value).decode(),None,'queued'))
            return run_id

    def saved(self, run_id):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
            if not row: raise HTTPException(404)
            return dict(row)

    def view(self, run_id):
        row=self.saved(run_id)
        with self.store.connect() as db:
            progress=db.execute('SELECT body FROM progress WHERE run_id=?',(run_id,)).fetchone()
        return {'id':run_id,'status':row['status'],'result':json.loads(row['response']) if row['response'] else json.loads(progress[0]) if progress else None}

    def progress(self, run_id, body):
        with self.store.tx() as db:
            db.execute('INSERT INTO progress VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET body=excluded.body',(run_id,canonical(body).decode()))

    def checkpoint(self, run_id, body):
        with self.store.tx() as db:
            db.execute('INSERT INTO checkpoints VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET body=excluded.body',(run_id,canonical(body).decode()))

    def history(self, service, backend):
        with self.store.connect() as db:
            return {r['provider']:{'attempts':r['attempts'],'verified':r['verified'],'mean_latency_ms':r['latency'],
                    'total_credits':r['credits'],'basis':'measured local tasks; selection-biased, not causal superiority'}
                    for r in db.execute('SELECT provider,COUNT(*) attempts,SUM(verified) verified,AVG(latency_ms) latency,SUM(cost) credits FROM feedback WHERE service=? AND backend=? GROUP BY provider',(service,backend))}

    async def offers(self, task, listings, run_id, mode):
        candidates=[]
        for a in listings:
            if not a.get('card') or a['health']!='reachable' or a['stale'] or task['service'] not in [s['id'] for s in a['card']['skills']]:
                continue
            provider=a['peer']
            try:
                r=await self.client.http(provider,'POST','/negotiate',json={'task':task,'mode':mode},headers={'Idempotency-Key':run_id+'-offer-'+provider})
                r.raise_for_status()
                offered=r.json()
                if offered['status']=='input-required' and mode=='free':
                    quote=None
                else:
                    quote=Quote.model_validate(offered['quote']).valid(provider=provider,principal='buyer',task=task).model_dump()
                candidates.append({'peer':provider,'price':quote['amount'] if quote else 0,'quote':quote,
                    'skills':[s['id'] for s in a['card']['skills']], 'price_basis':'immutable HTTP quote',
                    'quality_basis':'buyer measured history or unknown'})
            except Exception as error:
                self.store.event('quote.unavailable','buyer',provider,trace_id=run_id,failure_category=category(error))
        return candidates

    def emit(self, kind, run_id, payload, db=None):
        from exchange.integration import envelope
        message=envelope(kind,'agent-exchange','leo-os-stub',payload,trace=run_id,correlation=run_id,causation=run_id)
        if db is None:
            with self.store.tx() as conn:
                conn.execute('INSERT INTO outbox(message_id,body) VALUES(?,?)',(message['message_id'],canonical(message).decode()))
        else:
            db.execute('INSERT INTO outbox(message_id,body) VALUES(?,?)',(message['message_id'],canonical(message).decode()))
        return message

    def approval(self, run_id, checkpoint):
        preview={'run_id':run_id,'provider':checkpoint['provider'],'task':checkpoint['task'],'quote':checkpoint['quote']}
        binding=digest(preview)
        with self.store.tx() as db:
            row=db.execute('SELECT * FROM approvals WHERE run_id=?',(run_id,)).fetchone()
            if row:
                if row['binding']!=binding: raise ExchangeFailure('policy','Approval terms changed')
                return dict(row)
            db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?)',(run_id,binding,canonical(preview).decode(),'pending',now(),None,None))
            self.emit('approval.requested',run_id,{'capability':'simulator-payment','reason':'Review the exact task and quoted credits before admission',
                'approval_id':run_id,'binding':binding,'preview':preview},db=db)
        self.store.event('approval.requested','buyer','operator',trace_id=run_id,order_id=run_id,quote_id=checkpoint['quote']['quote_id'])
        return {'state':'pending','binding':binding,'preview':canonical(preview).decode()}

    def schedule(self, run_id):
        if run_id not in self.workers:
            task=asyncio.create_task(self.execute(run_id))
            self.workers[run_id]=task
            def finished(t):
                self.workers.pop(run_id,None)
                if not t.cancelled(): t.exception()  # retrieve unexpected worker errors; durable state is retained
            task.add_done_callback(finished)

    async def dispatch(self, run_id, checkpoint):
        task,provider=checkpoint['task'],checkpoint['provider']
        if checkpoint.get('task_id'):
            remote=await self.client.rpc(provider,'GetTask',{'id':checkpoint['task_id']},trace=run_id)
        else:
            remote=(await self.client.rpc(provider,'SendMessage',self.client.request(task,message_id=run_id,immediate=True),
                key=run_id,trace=run_id,headers={'X-Exchange-Order':run_id} if checkpoint.get('payment',{}).get('mode')=='simulator' else None))['task']
            checkpoint['task_id']=remote['id']
            self.checkpoint(run_id,checkpoint)
        from exchange.tasks import INTERRUPTED
        async with asyncio.timeout(150):
            while True:
                self.progress(run_id,{'run_id':run_id,'provider':provider,'task':remote,'decision':checkpoint['decision'],'payment':checkpoint.get('payment')})
                if remote['status']['state'] in INTERRUPTED: break
                await asyncio.sleep(.25)
                remote=await self.client.rpc(provider,'GetTask',{'id':remote['id']},trace=run_id)
        return remote

    async def execute(self, run_id):
        async with self.slots, self.locks.setdefault(run_id,asyncio.Lock()):
            row=self.saved(run_id)
            if row['response']: return json.loads(row['response'])
            value=json.loads(row['request'])
            started=time.monotonic()
            checkpoint=None
            with trace_scope(run_id,run_id) as context:
                self.store.event('run.started','buyer',span_id=run_id,parent_id=None,trace_id=run_id,input_hash=digest(value))
                with self.store.tx() as db:
                    db.execute("UPDATE runs SET status='running' WHERE id=?",(run_id,))
                    saved=db.execute('SELECT body FROM checkpoints WHERE run_id=?',(run_id,)).fetchone()
                try:
                    if saved:
                        checkpoint=json.loads(saved[0])
                    else:
                        r=await self.client.http('registry','POST','/refresh'); r.raise_for_status()
                        listings=r.json()['agents']
                        interpretation=None
                        if value.get('natural_request'):
                            from exchange.models import plan_request
                            task,recommended,interpretation=await plan_request(value['natural_request'],listings,run_id)
                            if interpretation.get('missing_requirements'):
                                result={'run_id':run_id,'status':'input-required','clarification':interpretation['missing_requirements'],'plan':interpretation}
                                return self.finish(run_id,result)
                        else:
                            task=json.loads(canonical(value['task']))
                        if value.get('backend')=='live': task['backend']='live'
                        task_schema(task, sorted({s for p in self.c['peers'].values() for s in p.get('services',[])}))
                        candidates=await self.offers(task,listings,run_id,value.get('payment_mode','free'))
                        if value.get('provider'): candidates=[p for p in candidates if p['peer']==value['provider']]
                        if value.get('payment_mode')=='simulator':
                            candidates=[p for p in candidates if p['price']<=value.get('max_credits',self.c['limits']['per_task'])]
                        preferred={'requirements':'requirements','csv-audit':'csv','verify':'verifier','match':'verifier'}[task['service']]
                        history=self.history(task['service'],task.get('backend','fixture'))
                        for p in candidates:
                            p['fixed_preference']=p['peer']==preferred
                            p['mean_latency_ms']=history.get(p['peer'],{}).get('mean_latency_ms') or 0
                        from exchange.buyer import choose
                        selected,decision=choose(candidates,value.get('policy','fixed'),value.get('seed',int(digest(run_id)[:16],16)),history)
                        checkpoint={'task':task,'provider':selected['peer'],'decision':decision,'plan':interpretation,'quote':selected['quote']}
                        self.checkpoint(run_id,checkpoint)
                    task,provider,interpretation=checkpoint['task'],checkpoint['provider'],checkpoint['plan']
                    self.store.event('provider.selected','buyer',provider,trace_id=run_id,**checkpoint['decision'])
                    if value.get('payment_mode')=='simulator':
                        if value.get('require_approval'):
                            approval=self.approval(run_id,checkpoint)
                            if approval['state']=='pending':
                                return self.finish(run_id,{'run_id':run_id,'status':'approval-required','provider':provider,
                                    'approval':{'id':run_id,'binding':approval['binding'],'preview':json.loads(approval['preview'])},'decision':checkpoint['decision']})
                            if approval['state']!='approved': raise ExchangeFailure('policy','Operator declined the simulator payment')
                        if not checkpoint.get('payment'):
                            from exchange.commerce import paid_exchange
                            payment=await paid_exchange(self.client,self.store,self.c,provider,task,run_id,quote=checkpoint.get('quote'),dispatch=False)
                            checkpoint.update(payment); self.checkpoint(run_id,checkpoint)
                    else:
                        if checkpoint.get('quote') and not checkpoint.get('agreement'):
                            agreement=await self.client.http(provider,'POST','/negotiate',
                                json={'action':'accept','quote_id':checkpoint['quote']['quote_id']},
                                headers={'Idempotency-Key':run_id+'-accept'})
                            agreement.raise_for_status()
                            checkpoint['agreement']=agreement.json()
                        checkpoint['payment']={'mode':'free','settled':0,'actual_money':0}
                        self.checkpoint(run_id,checkpoint)
                    remote=await self.dispatch(run_id,checkpoint)
                    try:
                        verdict=checked_artifact(remote,task)
                    except Exception as error:
                        raise ExchangeFailure('verification','Independent verifier failed; artifact not accepted') from error
                    result={'run_id':run_id,'provider':provider,'task':remote,'verifier':verdict,'decision':checkpoint['decision'],
                        'plan':interpretation,'payment':checkpoint['payment'],'status':'verified' if verdict['accepted'] else remote['status']['state'],
                        'agreed_quote':checkpoint.get('quote'),
                        'latency_ms':round((time.monotonic()-started)*1000)}
                    if not verdict['accepted']: result['failure_category']='task-quality' if remote['status']['state']=='TASK_STATE_COMPLETED' else 'provider'
                    if interpretation and verdict['accepted']:
                        from exchange.models import interpret_result
                        try: result['interpretation']=await interpret_result(remote,run_id)
                        except Exception as error: result['interpretation_error']={'category':category(error),'type':type(error).__name__}
                except asyncio.CancelledError:
                    with self.store.tx() as db: db.execute("UPDATE runs SET status='interrupted',response=NULL WHERE id=?",(run_id,))
                    raise
                except Exception as error:
                    result={'run_id':run_id,'status':'failed','failure_category':category(error),'error_type':type(error).__name__,
                        'detail':str(error)[:240] if isinstance(error,ValueError) else None}
                    if checkpoint:
                        result.update(provider=checkpoint['provider'],decision=checkpoint['decision'])
                        if checkpoint.get('payment'): result['payment']=checkpoint['payment']
                    with self.store.connect() as db:
                        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='payments'").fetchone()
                        payment=db.execute('SELECT state,receipt FROM payments WHERE run_id=?',(run_id,)).fetchone() if exists else None
                    if payment: result['payment']={'mode':'simulator','state':payment['state'],'receipt':json.loads(payment['receipt']) if payment['receipt'] else None}
                    if checkpoint and category(error) in ('transport','storage'):
                        result['status']='outcome-unknown'
                if checkpoint and checkpoint.get('task_id') and result['status'] not in WAITING:
                    with self.store.tx() as db:
                        db.execute('INSERT OR IGNORE INTO feedback VALUES(?,?,?,?,?,?,?,?)',(run_id,checkpoint['provider'],checkpoint['task']['service'],checkpoint['task'].get('backend','fixture'),
                            int(result.get('verifier',{}).get('accepted',False)),result.get('latency_ms',round((time.monotonic()-started)*1000)),
                            result.get('payment',{}).get('settled',0),result.get('failure_category')))
                return self.finish(run_id,result)

    def finish(self, run_id, result):
        self.progress(run_id,result)
        with self.store.tx() as db:
            db.execute('UPDATE runs SET status=?,response=? WHERE id=?',(result['status'],None if result['status']=='outcome-unknown' else canonical(result).decode(),run_id))
            self.store.event('run.finished','buyer',result.get('provider'),db=db,trace_id=run_id,disposition=result['status'],
                output_hash=digest(result),task_id=result.get('task',{}).get('id'),latency_ms=result.get('latency_ms'))
            if result.get('task'):
                kind='task.completed' if result['status']=='verified' else 'task.progress' if result['task']['status']['state']=='TASK_STATE_INPUT_REQUIRED' else 'task.failed'
                self.emit(kind,run_id,{'provider':result['provider'],'task':result['task'],'verifier':result.get('verifier')},db=db)
        return result

    def application(self):
        @asynccontextmanager
        async def lifespan(app):
            with self.store.connect() as db:
                pending=[r[0] for r in db.execute("SELECT id FROM runs WHERE status IN ('queued','running','interrupted') AND response IS NULL LIMIT 32")]
            for run_id in pending: self.schedule(run_id)
            yield
            workers=list(self.workers.values())
            for task in workers: task.cancel()
            await asyncio.gather(*workers,return_exceptions=True)
        app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
        app.state.coordinator=self
        peer=self.c['peers']['buyer']
        @app.get('/health')
        async def health(): return {'status':'ok','peer':'buyer','instance':peer.get('instance')}
        @app.post('/run')
        async def run(request:Request):
            run_id=self.admit(await request.json(),request.state.principal,request.headers.get('idempotency-key'))
            return await self.execute(run_id)
        @app.post('/submit',status_code=202)
        async def submit(request:Request):
            run_id=self.admit(await request.json(),request.state.principal,request.headers.get('idempotency-key'))
            self.schedule(run_id)
            return {'run_id':run_id,'status':self.saved(run_id)['status']}
        def read_allowed(request):
            if request.state.principal not in ('observer','operator'): raise HTTPException(403)
        @app.get('/runs')
        async def runs(request:Request):
            read_allowed(request)
            with self.store.connect() as db: ids=[r[0] for r in db.execute('SELECT id FROM runs ORDER BY rowid DESC LIMIT 50')]
            return {'runs':[self.view(i) for i in ids]}
        @app.get('/runs/{run_id}')
        async def one(run_id:str,request:Request):
            read_allowed(request); return self.view(run_id)
        @app.post('/runs/{run_id}/resume',status_code=202)
        async def resume(run_id:str,request:Request):
            if request.state.principal!='operator': raise HTTPException(403)
            row=self.saved(run_id)
            if row['status'] not in ('outcome-unknown','interrupted'): raise HTTPException(409,'Only interrupted or uncertain runs can resume')
            self.schedule(run_id); return {'run_id':run_id,'status':'queued'}
        @app.get('/performance')
        async def performance(request:Request,service:str='requirements',backend:str='fixture'):
            read_allowed(request); return {'history':self.history(service,backend)}
        @app.get('/approvals')
        async def approvals(request:Request):
            read_allowed(request)
            with self.store.connect() as db: rows=[dict(r) for r in db.execute('SELECT * FROM approvals ORDER BY rowid DESC LIMIT 50')]
            return {'approvals':[{**r,'preview':json.loads(r['preview'])} for r in rows]}
        @app.post('/approvals/{run_id}')
        async def decide(run_id:str,request:Request):
            if request.state.principal!='operator': raise HTTPException(403)
            value=await request.json()
            if not isinstance(value,dict) or set(value)!={'binding','approve'} or type(value['approve']) is not bool: raise HTTPException(422)
            state='approved' if value['approve'] else 'denied'
            with self.store.tx() as db:
                row=db.execute('SELECT * FROM approvals WHERE run_id=?',(run_id,)).fetchone()
                if not row: raise HTTPException(404)
                if row['binding']!=value['binding'] or row['state'] not in ('pending',state): raise HTTPException(409,'Approval conflict')
                if row['state']=='pending':
                    if value['approve']:
                        try: Quote.model_validate(json.loads(row['preview'])['quote']).valid()
                        except ValueError: raise HTTPException(409,'Quote expired; submit a new request for renewed approval') from None
                    db.execute('UPDATE approvals SET state=?,decided_at=?,decided_by=? WHERE run_id=?',(state,now(),'operator',run_id))
                    db.execute("UPDATE runs SET response=NULL,status='queued' WHERE id=?",(run_id,))
                    self.store.event('approval.'+state,'operator','buyer',db=db,trace_id=run_id,order_id=run_id)
            self.schedule(run_id)
            return {'run_id':run_id,'state':state}
        @app.get('/integration/events')
        async def events(request:Request,after:int=0):
            read_allowed(request)
            with self.store.connect() as db: rows=db.execute('SELECT seq,body FROM outbox WHERE seq>? ORDER BY seq LIMIT 100',(after,)).fetchall()
            return {'events':[{'seq':r['seq'],'envelope':json.loads(r['body'])} for r in rows]}
        @app.get('/observe')
        async def observe(request:Request,after:int=0):
            read_allowed(request); return {'events':self.store.events(after)}
        return Guard(app,peer,store=self.store)
