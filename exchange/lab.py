"""Rendezvous lab scheduler, hosted by the observer.

It seeds private knowledge, grants turns, delivers queued messages, enforces budgets, pause and
deadlines, and keeps an append-only event log. It never writes message content and never edits an
agent's memory except through the explicit operator injection route. Ground truth is computed here
and is never sent to an agent.
"""
from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import HTTPException, Request

from exchange.client import PeerClient
from exchange.common import DATA, Database, canonical, digest, now, uid
from exchange.lab_protocol import (AGENTS, BRAINS, INPUTS, KEY, LIMITS, MODES, ORDER, TASK, TOLERANCE_C, mentions,
                                   private_facts, trial, truth)

ACTIVE = ('running', 'pausing', 'paused', 'stepping', 'stopping')
TERMINAL = ('completed', 'stopped', 'failed')
DEFAULT_MODEL = 'claude-sonnet-5-5'


def seconds_since(stamp):
    return (datetime.now().astimezone() - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()


class Control:
    def __init__(self):
        self.pause, self.stop, self.steps, self.reason = False, False, 0, None
        self.wake = asyncio.Event()


class Lab:
    def __init__(self, c, root=None):
        self.c = c
        self.agents = [a for a in ORDER if a in c['peers']]
        self.model = c.get('lab', {}).get('model', DEFAULT_MODEL)
        self.db = Database((root or DATA) / 'observer' / 'lab.sqlite')
        with self.db.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS lab_runs(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lab_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, kind TEXT NOT NULL,
              at TEXT NOT NULL, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS lab_events_run ON lab_events(run_id, seq);
            ''')
        self.client = PeerClient(c, 'operator')
        self.loops, self.controls = {}, {}

    # -- persistence ---------------------------------------------------------------------
    def load(self, run_id):
        with self.db.connect() as db:
            row = db.execute('SELECT body FROM lab_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'unknown lab run')
        return json.loads(row[0])

    def record(self, run, kind=None, body=None):
        """Persist run state and (optionally) one event in a single transaction."""
        with self.db.tx() as db:
            db.execute('UPDATE lab_runs SET status=?, body=? WHERE id=?', (run['status'], canonical(run).decode(), run['id']))
            if kind:
                db.execute('INSERT INTO lab_events(run_id,kind,at,body) VALUES(?,?,?,?)', (run['id'], kind, now(), canonical(body or {}).decode()))

    def events(self, run_id, after=0, limit=2000):
        with self.db.connect() as db:
            return [{'seq': r['seq'], 'kind': r['kind'], 'at': r['at'], **json.loads(r['body'])} for r in db.execute(
                'SELECT * FROM lab_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?', (run_id, after, limit))]

    def runs(self, limit=60):
        with self.db.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT body FROM lab_runs ORDER BY created_at DESC LIMIT ?', (limit,))]
        return [summary(r) for r in rows]

    def recover(self):
        # A restarted observer never silently continues inference; the operator resumes explicitly.
        with self.db.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM lab_runs WHERE status IN (%s)' % ','.join('?' * len(ACTIVE)), ACTIVE)]
        for run_id in ids:
            self.interrupt(run_id, 'observer restarted while the run was active')

    def interrupt(self, run_id, reason):
        run = self.load(run_id)
        if run['status'] in TERMINAL or run['status'] == 'interrupted':
            return
        self.account(run)
        run['status'], run['interruption'] = 'interrupted', reason
        self.record(run, 'run.interrupted', {'reason': reason})

    @asynccontextmanager
    async def lifespan(self, app):
        self.recover()
        yield
        tasks = list(self.loops.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- configuration and approval -------------------------------------------------------
    def limits(self, requested=None):
        limits = dict(LIMITS)
        for key, value in (requested or {}).items():
            if key not in LIMITS or type(value) is not int or value < 0:
                raise HTTPException(422, 'unknown or invalid limit ' + str(key)[:40])
            limits[key] = min(value, LIMITS[key])  # Never above the hard caps.
        return limits

    def binding(self, limits):
        return digest({'backend': 'claude', 'model': self.model, 'limits': limits, 'agents': self.agents})

    def config(self):
        from exchange.lab_protocol import FORMULA
        return {'agents': [{'id': a, **AGENTS[a], 'url': self.c['peers'][a]['url']} for a in self.agents], 'modes': MODES,
                'brains': {'claude': f'Live Claude CLI ({self.model}, subscription authentication)', 'fixture': 'Fixture: deterministic stand-in, no model'},
                'model': self.model, 'limits': LIMITS, 'approval_binding': self.binding(dict(LIMITS)), 'task': TASK, 'formula_owner': 'mathematics',
                'formula': FORMULA, 'inputs': {k: {'owner': o, 'unit': u} for k, (o, u) in INPUTS.items()}, 'tolerance_c': TOLERANCE_C,
                'fixed_trial': trial('fixed')['inputs']}

    def create(self, spec, principal):
        if not isinstance(spec, dict) or not set(spec) <= {'mode', 'backend', 'trial', 'limits', 'approval'}:
            raise HTTPException(422, 'unknown run fields')
        mode, backend = spec.get('mode'), spec.get('backend', 'fixture')
        if mode not in MODES or backend not in BRAINS:
            raise HTTPException(422, 'unknown mode or brain')
        if len(self.agents) != 3:
            raise HTTPException(409, 'three lab agents must be configured')
        with self.db.connect() as db:
            busy = db.execute('SELECT id FROM lab_runs WHERE status IN (%s)' % ','.join('?' * len(ACTIVE)), ACTIVE).fetchone()
        if busy:
            raise HTTPException(409, 'another lab run is active: ' + busy[0])
        requested = spec.get('trial') or {'kind': 'fixed'}
        if not isinstance(requested, dict) or not set(requested) <= {'kind', 'seed'}:
            raise HTTPException(422, 'trial must be {kind, seed}')
        kind, seed = requested.get('kind', 'fixed'), requested.get('seed')
        if kind == 'random' and seed is None:
            seed = secrets.randbits(48)  # Fresh inputs nobody, including the agents, has seen.
        try:
            plan = trial(kind, seed)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        limits = self.limits(spec.get('limits'))
        approval = None
        if backend == 'claude':
            given = spec.get('approval')
            if not isinstance(given, dict) or given.get('approve') is not True or given.get('binding') != self.binding(limits):
                raise HTTPException(403, 'live Claude runs need explicit operator approval of the current model and limits')
            approval = {'approved_by': principal, 'approved_at': now(), 'binding': given['binding'], 'model': self.model, 'limits': limits,
                        'authentication': 'existing Claude CLI subscription login; API-key variables are removed before launch'}
        run_id = uid()
        run = {'id': run_id, 'created_at': now(), 'status': 'running', 'mode': mode, 'backend': backend,
               'model': self.model if backend == 'claude' else None, 'trial': plan, 'trial_key': trial_key(plan), 'limits': limits,
               'approval': approval, 'principal': principal, 'seeded': False, 'auto_paused': False, 'queue': [], 'cursor': 0,
               'counters': {'turns': 0, 'model_calls': 0, 'failed_turns': 0, 'delivery_attempts': 0, 'delivered': 0, 'failed_deliveries': 0,
                            'suppressed': 0, 'dropped': 0, 'withheld': 0},
               'agents': {a: {'turns': 0, 'pending': 0, 'first': False, 'answer': None} for a in self.agents},
               'clock': {'active_ms': 0, 'running_since': time.time(), 'started_at': now(), 'finished_at': None},
               'truth': {'original_c': plan['truth_c'], 'current_c': plan['truth_c'], 'inputs': dict(plan['inputs'])},
               'injections': [], 'stop_reason': None, 'pause_reason': None, 'error': None, 'results': None}
        with self.db.tx() as db:
            db.execute('INSERT INTO lab_runs VALUES(?,?,?,?)', (run_id, run['created_at'], run['status'], canonical(run).decode()))
        self.record(run, 'run.created', {'mode': mode, 'backend': backend, 'model': run['model'], 'trial': {'kind': plan['kind'], 'seed': plan['seed']},
                                         'limits': limits, 'approval': approval, 'data_label': 'live' if backend == 'claude' else 'fixture'})
        self.start(run_id)
        return run

    def start(self, run_id, resync=False):
        control = self.controls.setdefault(run_id, Control())
        control.stop, control.steps = False, 0
        self.loops[run_id] = asyncio.get_running_loop().create_task(self.loop(run_id, control, resync))

    # -- operator controls -----------------------------------------------------------------
    def control(self, run_id):
        run = self.load(run_id)
        control = self.controls.get(run_id)
        return run, control

    def pause(self, run_id, reason='operator pause'):
        run, control = self.control(run_id)
        if run['status'] not in ('running', 'stepping') or not control:
            raise HTTPException(409, 'only a running run can be paused')
        control.pause, control.reason = True, reason
        run['status'], run['pause_reason'] = 'pausing', reason
        self.record(run, 'run.pause_requested', {'reason': reason, 'note': 'Takes effect at the next event boundary; an in-flight model call finishes first.'})
        return summary(run)

    def resume(self, run_id):
        run, control = self.control(run_id)
        if run['status'] == 'interrupted':
            run['status'], run['interruption'] = 'running', None
            run['clock']['running_since'] = time.time()
            self.record(run, 'run.resumed', {'after': 'interruption', 'resync': True})
            self.start(run_id, resync=True)
            return summary(run)
        if run['status'] not in ('paused', 'pausing') or not control:
            raise HTTPException(409, 'only a paused run can be resumed')
        control.pause = False
        control.wake.set()
        return summary(run)

    def step(self, run_id):
        run, control = self.control(run_id)
        if run['status'] != 'paused' or not control:
            raise HTTPException(409, 'step requires a paused run')
        control.steps += 1
        control.wake.set()
        return summary(run)

    def stop(self, run_id):
        run, control = self.control(run_id)
        if run['status'] == 'interrupted':
            run['status'], run['stopped_by_operator'] = 'stopping', True
            run['stop_reason'] = 'operator stop after interruption'
            self.record(run, 'run.stop_requested', {'reason': run['stop_reason']})
            self.start(run_id, resync=True)
            self.controls[run_id].stop = True
            return summary(run)
        if run['status'] not in ACTIVE or not control:
            raise HTTPException(409, 'run is not active')
        control.stop = True
        control.wake.set()
        run['status'], run['stop_reason'], run['stopped_by_operator'] = 'stopping', 'operator stop', True
        self.record(run, 'run.stop_requested', {'reason': 'operator stop', 'note': 'An in-flight model call finishes; queued messages are withheld.'})
        return summary(run)

    async def inject(self, run_id, value):
        if not isinstance(value, dict) or set(value) != {'agent', 'key', 'value', 'unit', 'note'}:
            raise HTTPException(422, 'expected agent, key, value, unit, note')
        run = self.load(run_id)
        if run['status'] != 'paused':
            raise HTTPException(409, 'pause the run before injecting a fact')
        if value['agent'] not in self.agents or not KEY.match(str(value['key'])):
            raise HTTPException(422, 'unknown agent or invalid key')
        response = await self.client.http(value['agent'], 'POST', '/lab/inject', json={'run_id': run_id, 'key': value['key'], 'value': value['value'],
                                                                                      'unit': value['unit'], 'note': value['note']})
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.json().get('detail', 'injection refused'))
        result = response.json()
        run = self.load(run_id)
        before_truth = run['truth']['current_c']
        numeric = isinstance(value['value'], (int, float)) and not isinstance(value['value'], bool)
        if value['key'] in INPUTS and numeric:
            run['truth']['inputs'][value['key']] = value['value']
            run['truth']['current_c'] = truth(run['truth']['inputs'])
        run['agents'][value['agent']]['pending'] += 1  # The notice gives that agent a turn.
        entry = {'agent': value['agent'], 'key': value['key'], 'value': value['value'], 'unit': value['unit'], 'note': value['note'],
                 'fact': result['fact'], 'replaced': result['replaced'], 'truth_before_c': before_truth, 'truth_after_c': run['truth']['current_c'],
                 'at': now()}
        run['injections'].append(entry)
        self.record(run, 'fact.injected', entry)
        return entry

    async def inspect(self, run_id, prompts=False):
        out = {}
        for agent in self.agents:
            response = await self.client.http(agent, 'GET', f'/lab/export?run_id={run_id}&prompts={str(prompts).lower()}', limit=4 * 1048576)
            response.raise_for_status()
            out[agent] = response.json()
        return out

    # -- the loop ----------------------------------------------------------------------------
    async def loop(self, run_id, control, resync):
        try:
            if resync:
                await self.resync(run_id)
            if not self.load(run_id)['seeded']:
                await self.seed(run_id)
            while await self.boundary(run_id, control):
                run = self.load(run_id)
                if run['queue'] and run['counters']['delivery_attempts'] >= run['limits']['max_deliveries'] and not run.get('delivery_budget_hit'):
                    # Messages beyond the cap stay queued and are withheld at the end; agents may still read what arrived.
                    run['delivery_budget_hit'] = True
                    reason = f'delivery budget of {run["limits"]["max_deliveries"]} reached; later messages are withheld'
                    run['stop_reason'] = run['stop_reason'] or reason
                    self.record(run, 'budget.exhausted', {'reason': reason, 'kind': 'deliveries'})
                action = self.next_action(self.load(run_id))
                if action is None:
                    break
                kind, arg = action
                if kind == 'limit':
                    run = self.load(run_id)
                    run['stop_reason'] = arg
                    self.record(run, 'budget.exhausted', {'reason': arg})
                    break
                if kind == 'deliver':
                    await self.deliver(run_id, arg)
                else:
                    await self.turn(run_id, arg)
                if control.steps:
                    control.steps -= 1
                self.auto_pause(run_id, control)
            await self.finish(run_id)
        except asyncio.CancelledError:
            self.interrupt(run_id, 'observer stopped while the run was active')
            raise
        except Exception as e:
            run = self.load(run_id)
            run['error'] = f'{type(e).__name__}: {str(e)[:200]}'
            self.record(run, 'run.error', {'error': run['error']})
            try:
                await self.finish(run_id, failed=True)
            except Exception as again:
                run = self.load(run_id)
                run['status'] = 'failed'
                self.record(run, 'run.failed', {'error': run['error'], 'finish_error': type(again).__name__})
        finally:
            self.loops.pop(run_id, None)

    def account(self, run):
        clock = run['clock']
        if clock.get('running_since'):
            clock['active_ms'] += round((time.time() - clock['running_since']) * 1000)
            clock['running_since'] = None

    def deadline(self, run):
        clock, limits = run['clock'], run['limits']
        active = clock['active_ms'] + ((time.time() - clock['running_since']) * 1000 if clock.get('running_since') else 0)
        if active > limits['active_seconds'] * 1000:
            return f'active wall-clock deadline of {limits["active_seconds"]} s reached'
        if seconds_since(run['created_at']) > limits['absolute_seconds']:
            return f'absolute deadline of {limits["absolute_seconds"]} s reached'
        return None

    async def gates(self, run_id, open_):
        for agent in self.agents:
            response = await self.client.http(agent, 'POST', '/lab/gate', json={'run_id': run_id, 'open': open_})
            response.raise_for_status()

    async def boundary(self, run_id, control):
        """Every turn and every delivery passes here first. Pause holds the run at this point."""
        while True:
            run = self.load(run_id)
            if control.stop:
                return False
            reason = self.deadline(run)
            if reason:
                run['stop_reason'] = reason
                self.record(run, 'run.deadline', {'reason': reason})
                return False
            if not control.pause or control.steps:
                if run.get('gates_closed'):
                    await self.gates(run_id, True)
                    run = self.load(run_id)
                    run['gates_closed'] = False
                stepping = bool(control.pause and control.steps)
                previous = run['status']
                if stepping and previous != 'stepping':
                    run['status'] = 'stepping'
                    run['clock']['running_since'] = run['clock'].get('running_since') or time.time()
                    self.record(run, 'run.step', {'boundary': self.position(run), 'note': 'exactly one turn or delivery, then paused again'})
                elif not stepping and previous != 'running':
                    run['status'] = 'running'
                    run['clock']['running_since'] = run['clock'].get('running_since') or time.time()
                    self.record(run, 'run.resumed', {'from': previous, 'boundary': self.position(run)})
                else:
                    self.record(run)
                return True
            if run['status'] != 'paused':
                await self.gates(run_id, False)
                memories = await self.inspect(run_id)
                run = self.load(run_id)
                run['gates_closed'] = True
                self.account(run)
                run['status'], run['pause_reason'] = 'paused', control.reason or 'operator pause'
                self.record(run, 'run.paused', {'reason': run['pause_reason'], 'boundary': self.position(run),
                                                'queued': list(run['queue']), 'memory': {a: m['facts'] for a, m in memories.items()},
                                                'gates': 'closed on all three agents: inference, delivery and inbound messages refused'})
            control.wake.clear()
            remaining = max(1.0, run['limits']['absolute_seconds'] - seconds_since(run['created_at']))
            try:
                await asyncio.wait_for(control.wake.wait(), timeout=remaining)
            except TimeoutError:
                pass

    def position(self, run):
        c = run['counters']
        return {'turns': c['turns'], 'delivery_attempts': c['delivery_attempts'], 'queued': len(run['queue'])}

    def auto_pause(self, run_id, control):
        run = self.load(run_id)
        if run['mode'] != 'intervention' or run['auto_paused']:
            return
        round_done = all(s['first'] for s in run['agents'].values()) and (not run['queue'] or run['counters']['delivery_attempts'] >= run['limits']['max_deliveries'])
        if round_done:
            control.pause = True
            control.reason = 'controlled boundary: end of round one (each agent took one turn; its messages were delivered)'
            run['auto_paused'] = True
            self.record(run)

    def next_action(self, run):
        limits, counters = run['limits'], run['counters']
        if run['mode'] != 'isolated' and run['queue'] and counters['delivery_attempts'] < limits['max_deliveries']:
            return ('deliver', run['queue'][0])
        start = run['cursor']
        order = [self.agents[(start + i) % len(self.agents)] for i in range(len(self.agents))]

        def needs(agent):
            state = run['agents'][agent]
            if state['turns'] >= limits['turns_per_agent']:
                return False
            if run['mode'] == 'isolated':
                return not state['first']
            return not state['first'] or state['pending'] > 0
        waiting = [a for a in order if needs(a)]
        if not waiting:
            return None
        if counters['turns'] >= limits['max_inferences']:
            return ('limit', f'inference budget of {limits["max_inferences"]} reached while {", ".join(waiting)} still had unread input')
        return ('turn', waiting[0])

    async def seed(self, run_id):
        run = self.load(run_id)
        for agent in self.agents:
            spec = {'mode': run['mode'], 'backend': run['backend'], 'model': run['model'], 'task': TASK,
                    'facts': private_facts(agent, run['trial']['inputs']), 'directory': [a for a in self.agents if a != agent]}
            response = await self.client.http(agent, 'POST', '/lab/seed', json={'run_id': run_id, 'spec': spec})
            response.raise_for_status()
            run = self.load(run_id)
            self.record(run, 'agent.seeded', {'agent': agent, 'facts': response.json()['facts'], 'directory': spec['directory'],
                                              'store': f'{agent} homebase (separate process and SQLite file)'})
        run = self.load(run_id)
        run['seeded'] = True
        self.record(run, 'run.started', {'order': self.agents, 'communication': run['mode'] != 'isolated'})

    async def turn(self, run_id, agent):
        run = self.load(run_id)
        state = run['agents'][agent]
        state['turns'] += 1
        state['first'] = True
        pending, state['pending'] = state['pending'], 0
        run['counters']['turns'] += 1
        if run['backend'] == 'claude':
            run['counters']['model_calls'] += 1
        run['cursor'] = (self.agents.index(agent) + 1) % len(self.agents)
        turn_id = f'{agent}-{state["turns"]}'
        limits = run['limits']
        budget = {'deliveries_remaining': max(0, limits['max_deliveries'] - run['counters']['delivery_attempts']),
                  'messages_per_turn': limits['messages_per_turn'], 'turns_per_agent': limits['turns_per_agent']}
        self.record(run, 'turn.started', {'agent': agent, 'turn_id': turn_id, 'turn_no': state['turns'], 'brain': run['backend'],
                                          'model': run['model'], 'unread_inputs': pending})
        try:
            response = await self.client.http(agent, 'POST', '/lab/turn', json={'run_id': run_id, 'turn_id': turn_id, 'turn_no': state['turns'],
                                                                                'budget': budget}, limit=1048576)
            if response.status_code != 200:
                raise RuntimeError(f'HTTP {response.status_code}: {str(response.json().get("detail"))[:160]}')
            result = response.json()
        except Exception as e:
            result = {'agent': agent, 'turn_id': turn_id, 'turn_no': state['turns'], 'status': 'failed', 'error': type(e).__name__,
                      'detail': str(e)[:200], 'queued': [], 'facts': [], 'decisions': [], 'answer': None, 'warnings': []}
        run = self.load(run_id)
        if result['status'] != 'ok':
            run['counters']['failed_turns'] += 1
        for message in result.get('queued', []):
            run['queue'].append({k: message[k] for k in ('message_id', 'sender', 'recipient', 'intent')})
        run['counters']['suppressed'] += len(result.get('suppressed', []))
        run['counters']['dropped'] += len(result.get('dropped', []))
        if result.get('answer'):
            run['agents'][agent]['answer'] = result['answer']
        self.record(run, 'turn.finished', result)

    async def deliver(self, run_id, item):
        run = self.load(run_id)
        run['counters']['delivery_attempts'] += 1
        self.record(run, 'delivery.started', {**item, 'transport': 'A2A SendMessage over HTTP, sender process → recipient process'})
        try:
            response = await self.client.http(item['sender'], 'POST', '/lab/deliver', json={'run_id': run_id, 'message_id': item['message_id']},
                                              limit=1048576)
            if response.status_code != 200:
                raise RuntimeError(f'HTTP {response.status_code}: {str(response.json().get("detail"))[:160]}')
            delivery = response.json()
        except Exception as e:
            run = self.load(run_id)
            run['queue'] = [q for q in run['queue'] if q['message_id'] != item['message_id']]
            run['counters']['failed_deliveries'] += 1
            self.record(run, 'message.failed', {**item, 'error': type(e).__name__, 'detail': str(e)[:200]})
            return
        run = self.load(run_id)
        run['queue'] = [q for q in run['queue'] if q['message_id'] != item['message_id']]
        run['counters']['delivered'] += 1
        run['agents'][item['recipient']]['pending'] += 1
        self.record(run, 'message.delivered', delivery)

    async def resync(self, run_id):
        """After an observer restart, rebuild queue and pending input from the agents' own stores."""
        run = self.load(run_id)
        if not run['seeded']:
            return
        memories = await self.inspect(run_id)
        events = self.events(run_id)
        finished = {e['turn_id'] for e in events if e['kind'] == 'turn.finished'}
        delivered = {e['message_id'] for e in events if e['kind'] == 'message.delivered'}
        for agent, memory in memories.items():
            for turn in memory['turns']:
                if turn['turn_id'] not in finished and turn['status'] != 'started':
                    body = turn['summary'] or {'agent': agent, 'turn_id': turn['turn_id'], 'status': turn['status'], 'error': turn['error'],
                                               'queued': [], 'facts': [], 'decisions': [], 'answer': None, 'warnings': []}
                    self.record(self.load(run_id), 'turn.finished', {**body, 'reconciled_after_restart': True})
            for row in memory['outbox']:
                if row['status'] == 'delivered' and row['message_id'] not in delivered:
                    self.record(self.load(run_id), 'message.delivered', {**row['delivery'], 'reconciled_after_restart': True})
        run = self.load(run_id)
        queued = sorted(((row['created_at'], row['seq'], agent, row) for agent, m in memories.items() for row in m['outbox'] if row['status'] == 'queued'))
        run['queue'] = [{'message_id': r['message_id'], 'sender': a, 'recipient': r['recipient'], 'intent': r['body']['intent']} for _, _, a, r in queued]
        for agent, memory in memories.items():
            state = run['agents'][agent]
            state['turns'] = max(state['turns'], len(memory['turns']))
            state['first'] = state['first'] or bool(memory['turns'])
            state['pending'] = sum(1 for r in memory['inbox'] if not r['consumed_turn']) + sum(1 for n in memory['notices'] if not n['consumed_turn'])
        run['gates_closed'] = True
        self.record(run, 'run.resynced', {'queue': run['queue'], 'pending': {a: s['pending'] for a, s in run['agents'].items()}})

    async def finish(self, run_id, failed=False):
        withheld = []
        for agent in self.agents:
            response = await self.client.http(agent, 'POST', '/lab/close', json={'run_id': run_id})
            if response.status_code == 200:
                withheld += response.json()['withheld']
        memories = await self.inspect(run_id, prompts=True)
        run = self.load(run_id)
        self.account(run)
        run['clock']['finished_at'] = now()
        run['counters']['withheld'] = len(withheld)
        run['queue'] = []
        results = evaluate(run, memories, self.events(run_id))
        run['results'] = results
        run['status'] = 'failed' if failed else 'stopped' if run.get('stopped_by_operator') else 'completed'
        self.record(run, 'run.' + run['status'], {'results': results, 'withheld': withheld, 'stop_reason': run['stop_reason']})


def trial_key(plan):
    return 'fixed' if plan['kind'] == 'fixed' else f'random:{plan["seed"]}'


def summary(run):
    results = run.get('results') or {}
    digest_ = None
    if results:
        digest_ = {'answers': {a: (v['final_answer'] or {}).get('value') if (v['final_answer'] or {}).get('status') == 'final' else None
                               for a, v in results['agents'].items()},
                   'answer_status': {a: (v['final_answer'] or {}).get('status') for a, v in results['agents'].items()},
                   'correct': {a: v['correct'] for a, v in results['agents'].items()},
                   'truth_c': results['truth']['current_c'], 'original_truth_c': results['truth']['original_c'],
                   'delivered': results['messages']['delivered'], 'withheld': results['messages']['withheld'],
                   'turns': results['inference']['turns'], 'model_calls': results['inference']['model_calls'],
                   'failed_turns': results['inference']['failed_turns'], 'observed_models': results['inference']['observed_models'],
                   'active_seconds': results['latency']['active_seconds'], 'facts_learned': results['information']['facts_learned'],
                   'claims': results['claims']['total'], 'audit_ok': results['event_audit']['ok'],
                   'propagation': results.get('propagation')}
    return {'id': run['id'], 'created_at': run['created_at'], 'status': run['status'], 'mode': run['mode'], 'backend': run['backend'],
            'model': run['model'], 'trial_key': run['trial_key'], 'trial': {'kind': run['trial']['kind'], 'seed': run['trial']['seed']},
            'counters': run['counters'], 'stop_reason': run['stop_reason'], 'pause_reason': run.get('pause_reason'),
            'correct_agents': results.get('correct_agents'), 'all_correct': results.get('all_correct'),
            'unverified_claims': (results.get('claims') or {}).get('unverified'), 'leakage': (results.get('leakage') or {}).get('count'),
            'results': digest_}


# -- independent evaluation ------------------------------------------------------------------
def evaluate(run, memories, events):
    """Deterministic checks against ground truth. Uses only stored records, never model output alone."""
    inputs_now, truth_now, truth_original = run['truth']['inputs'], run['truth']['current_c'], run['truth']['original_c']
    facts = {a: {f['fact_id']: f for f in m['facts']} for a, m in memories.items()}

    def trace(agent, fact_id, seen=frozenset()):
        fact = facts.get(agent, {}).get(fact_id)
        if not fact or (agent, fact_id) in seen:
            return {}
        seen = seen | {(agent, fact_id)}
        if fact['origin_kind'] in ('initial', 'operator'):
            return {fact['key']: {'value': fact['value'], 'agent': agent, 'fact_id': fact_id, 'kind': fact['origin_kind']}}
        if fact['origin_kind'] == 'received':
            return trace(fact['sender'], fact['via_fact'], seen)
        merged = {}
        for dep in fact['depends_on']:
            merged.update(trace(agent, dep, seen))
        return merged

    def check(agent, value, depends_on, final=False):
        """A claim is evidence-backed when it equals a quantity of the thermal model computable from
        the inputs its cited facts trace back to: the temperature rise P×R_th, or T_ambient + P×R_th.
        An answer must equal the steady-state temperature itself."""
        traced = {}
        for dep in depends_on:
            traced.update(trace(agent, dep))
        numbers = {k: v['value'] for k, v in traced.items() if k in INPUTS and isinstance(v['value'], (int, float))}
        candidates = {}
        if 'heat_load' in numbers and 'thermal_resistance' in numbers and not final:
            candidates['temperature rise P×R_th'] = truth({**numbers, 'ambient_temperature': 0})
        if len(numbers) == len(INPUTS):
            candidates['steady-state temperature'] = truth(numbers)
        for name, recomputed in candidates.items():
            if abs(value - recomputed) <= TOLERANCE_C:
                stale = [k for k in numbers if numbers[k] != inputs_now[k]]
                return {'verdict': 'evidence-backed', 'quantity': name, 'recomputed': recomputed, 'stale_inputs': stale, 'sources': traced}
        if not candidates:
            missing = [k for k in INPUTS if k not in numbers]
            return {'verdict': 'unverified', 'reason': 'cited evidence does not reach ' + ', '.join(missing), 'sources': traced}
        shown = ', '.join(f'{n} {v}' for n, v in candidates.items())
        return {'verdict': 'unverified', 'reason': f'value does not follow from cited evidence ({shown})', 'sources': traced}

    agents, claims = {}, []
    for agent, memory in memories.items():
        answers = memory['answers']
        final = answers[-1] if answers else None
        rows = list(facts[agent].values())
        learned = [{'fact_id': f['fact_id'], 'key': f['key'], 'value': f['value'], 'unit': f['unit'], 'from': f['sender'],
                    'origin': f'{f["origin_agent"]}:{f["origin_fact"]}', 'status': f['status'], 'superseded_by': f['superseded_by']}
                   for f in rows if f['origin_kind'] == 'received' and f['status'] in ('accepted', 'superseded')]
        current = {f['key']: f for f in rows if f['status'] == 'accepted' and not f['superseded_by']}
        known = {k: {'value': current[k]['value'], 'fact_id': current[k]['fact_id'], 'matches_current_truth': current[k]['value'] == inputs_now[k]}
                 for k in INPUTS if k in current}
        for f in rows:
            if f['origin_kind'] == 'derived' and isinstance(f['value'], (int, float)):
                claims.append({'agent': agent, 'kind': 'derived fact', 'id': f['fact_id'], 'key': f['key'], 'value': f['value'],
                               **check(agent, f['value'], f['depends_on'])})
        for a in answers:
            if a['value'] is not None:
                claims.append({'agent': agent, 'kind': f'{a["status"]} answer', 'id': a['turn_id'], 'key': 'answer', 'value': a['value'],
                               **check(agent, a['value'], a['depends_on'], final=True)})
        value = final['value'] if final and final['status'] == 'final' else None
        agents[agent] = {
            'final_answer': final, 'answered': value is not None,
            'correct': value is not None and abs(value - truth_now) <= TOLERANCE_C,
            'correct_vs_original': value is not None and abs(value - truth_original) <= TOLERANCE_C,
            'learned': learned, 'learned_count': sum(1 for f in learned),
            'derived': [{'fact_id': f['fact_id'], 'key': f['key'], 'value': f['value'], 'status': f['status']} for f in rows if f['origin_kind'] == 'derived'],
            'rejected': [{'fact_id': f['fact_id'], 'key': f['key'], 'value': f['value'], 'reason': f['reason']} for f in rows if f['status'] == 'rejected'],
            'uncertain': [{'fact_id': f['fact_id'], 'key': f['key'], 'value': f['value'], 'reason': f['reason']} for f in rows if f['status'] == 'uncertain'],
            'inputs_known': known, 'facts_before': len(memory['snapshots'].get('before', {}).get('facts', [])), 'facts_after': len(rows)}

    turns = [e for e in events if e['kind'] == 'turn.finished']
    calls = [t['call'] for t in turns if t.get('call')]
    usage = {}
    for call in calls:
        for k, v in (call.get('usage') or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                usage[k] = usage.get(k, 0) + v
    latencies = [c['latency_ms'] for c in calls if c.get('latency_ms') is not None]
    delivered = [e for e in events if e['kind'] == 'message.delivered']
    by_intent = {}
    for d in delivered:
        intent = d['envelope']['intent']
        by_intent[intent] = by_intent.get(intent, 0) + 1
    clock = run['clock']
    wall = seconds_since(run['created_at'])
    results = {
        'truth': {'original_c': truth_original, 'current_c': truth_now, 'inputs': inputs_now, 'tolerance_c': TOLERANCE_C,
                  'hidden_from_agents': True},
        'agents': agents,
        'correct_agents': sum(a['correct'] for a in agents.values()),
        'all_correct': all(a['correct'] for a in agents.values()),
        'answered_agents': sum(a['answered'] for a in agents.values()),
        'messages': {'delivered': len(delivered), 'attempted': run['counters']['delivery_attempts'], 'failed': run['counters']['failed_deliveries'],
                     'withheld': run['counters']['withheld'], 'suppressed_duplicates': run['counters']['suppressed'],
                     'dropped_over_limit': run['counters']['dropped'], 'by_intent': by_intent},
        'inference': {'turns': run['counters']['turns'], 'model_calls': len(calls), 'failed_turns': run['counters']['failed_turns'],
                      'brain': run['backend'], 'requested_model': run['model'],
                      'observed_models': sorted({c['observed_model'] for c in calls if c.get('observed_model')}),
                      'cli_internal_turns': sum(c.get('cli_internal_turns') or 0 for c in calls), 'reported_usage': usage or None,
                      'usage_basis': 'token counts as reported by the Claude CLI; no monetary cost is inferred',
                      'model_latency_ms': {'total': sum(latencies), 'mean': round(sum(latencies) / len(latencies)) if latencies else None,
                                           'max': max(latencies) if latencies else None}},
        'latency': {'active_seconds': round(clock['active_ms'] / 1000, 2), 'wall_seconds': round(wall, 2),
                    'paused_seconds': round(max(0.0, wall - clock['active_ms'] / 1000), 2)},
        'information': {'facts_learned': sum(a['learned_count'] for a in agents.values()),
                        'inputs_held_at_end': {a: sorted(v['inputs_known']) for a, v in agents.items()}},
        'claims': {'total': len(claims), 'unverified': sum(c['verdict'] != 'evidence-backed' for c in claims),
                   'stale': sum(bool(c.get('stale_inputs')) for c in claims), 'items': claims},
        'leakage': leakage(run, memories),
        'event_audit': audit(run, memories, events),
        'stop_reason': run['stop_reason'],
        'budget': {'turns_used': run['counters']['turns'], 'deliveries_used': run['counters']['delivery_attempts'], 'limits': run['limits']},
    }
    if run['injections']:
        results['propagation'] = propagation(run, memories, agents)
    return results


def derivation(value, numbers):
    """How a value can be back-calculated, at the precision shown, from numbers an agent legitimately held."""
    import itertools
    text = ('%.6f' % value).rstrip('0').rstrip('.')
    # Two digits tighter than the precision shown: genuine back-calculations agree almost exactly,
    # coincidences such as 21 / 120 = 0.175 ≈ 0.18 do not.
    tol = 0.5 * 10 ** (-(len(text.split('.')[1]) if '.' in text else 0) - 2) + 1e-12
    nums = sorted({n for n in numbers if isinstance(n, (int, float)) and not isinstance(n, bool)})
    for a, b in itertools.permutations(nums, 2):
        for x, how in ((a - b, f'{a} - {b}'), (a * b, f'{a} × {b}'), (a / b if b else None, f'{a} / {b}')):
            if x is not None and abs(x - value) <= tol:
                return how
    for a, b, c in itertools.permutations(nums, 3):
        for x, how in (((a - b) / c if c else None, f'({a} - {b}) / {c}'), (a - b * c, f'{a} - {b} × {c}')):
            if x is not None and abs(x - value) <= tol:
                return how
    return None


def leakage(run, memories):
    """Values private to another agent that appear in a prompt or output without having been delivered.

    v1.1 (added after campaign v1): a value the agent could back-calculate from numbers it legitimately held
    (for example R_th = (T - T_ambient) / P from a delivered answer) is reported as inference, not leakage."""
    private = {a: [] for a in memories}
    for key, (owner, _) in INPUTS.items():
        if owner in private:
            private[owner].append(run['trial']['inputs'][key])
    for entry in run['injections']:
        private[entry['agent']].append(entry['value'])
    findings, checked = [], 0
    for agent, memory in memories.items():
        for turn in memory['turns']:
            if not turn.get('prompt'):
                continue
            checked += 1
            own = [f['value'] for f in memory['facts'] if f['created_at'] <= (turn['finished_at'] or turn['started_at'])]
            received = [m for m in memory['inbox'] if m['received_at'] <= turn['started_at']]
            evidence = [e['value'] for m in received for e in m['body']['evidence']]
            content = ' '.join(m['body']['content'] for m in received)
            text = turn['prompt'] + ' ' + canonical(turn['output'] or {}).decode()
            for other, values in private.items():
                if other == agent:
                    continue
                for value in values:
                    if not mentions(text, value) or value in own or value in evidence:
                        continue
                    where = 'output' if not mentions(turn['prompt'], value) else 'prompt'
                    told = mentions(content, value)
                    inferred = None if told or where == 'prompt' else derivation(value, own + evidence)
                    findings.append({'agent': agent, 'turn_id': turn['turn_id'], 'value': value, 'owner': other, 'where': where,
                                     'communicated_as_text': told, 'inferred_from': inferred,
                                     'assessment': 'stated in delivered message text (not evidence)' if told
                                     else f'back-calculated by the agent: {inferred}' if inferred
                                     else 'not delivered to this agent: possible leakage or coincidence'})
    unexplained = [f for f in findings if not f['communicated_as_text'] and not f['inferred_from']]
    return {'checked_turns': checked, 'count': len(unexplained), 'inferred': sum(bool(f['inferred_from']) for f in findings),
            'findings': findings, 'detector': 'v1.1',
            'method': 'search each stored prompt and output for other agents\' private values not yet delivered as evidence; '
                      'values the agent could back-calculate from what it held are reported as inference'}


def audit(run, memories, events):
    """Every recorded delivery must match the sender's outbox and the recipient's inbox exactly."""
    problems = []
    delivered = {e['message_id']: e for e in events if e['kind'] == 'message.delivered'}
    inbox = {r['message_id']: (a, r) for a, m in memories.items() for r in m['inbox']}
    outbox = {r['message_id']: (a, r) for a, m in memories.items() for r in m['outbox']}
    for message_id, event in delivered.items():
        if message_id not in inbox:
            problems.append(f'{message_id}: recorded as delivered but absent from the recipient inbox')
            continue
        recipient, row = inbox[message_id]
        if recipient != event['recipient'] or row['sender'] != event['sender'] or row['digest'] != event['digest']:
            problems.append(f'{message_id}: recipient inbox differs from the recorded delivery')
        sender, sent = outbox.get(message_id, (None, None))
        if not sent or sender != event['sender'] or sent['status'] != 'delivered' or sent['digest'] != event['digest']:
            problems.append(f'{message_id}: sender outbox differs from the recorded delivery')
        if digest(event['envelope']) != event['digest']:
            problems.append(f'{message_id}: recorded envelope does not match its digest')
    for message_id in inbox:
        if message_id not in delivered:
            problems.append(f'{message_id}: present in an inbox without a recorded delivery')
    for message_id, (sender, row) in outbox.items():
        if row['status'] == 'delivered' and message_id not in delivered:
            problems.append(f'{message_id}: outbox says delivered without a recorded delivery')
    recorded_turns = {(e['agent'], e['turn_id']): e for e in events if e['kind'] == 'turn.finished'}
    stored_turns = {(a, t['turn_id']): t for a, m in memories.items() for t in m['turns']}
    for key, turn in stored_turns.items():
        event = recorded_turns.get(key)
        if not event:
            problems.append(f'{key[0]} {key[1]}: stored turn without a recorded event')
        elif event['status'] != turn['status'] and not (turn['status'] == 'interrupted'):
            problems.append(f'{key[0]} {key[1]}: status differs ({event["status"]} vs {turn["status"]})')
        elif (event.get('call') or {}).get('call_id') != (turn.get('call') or {}).get('call_id'):
            problems.append(f'{key[0]} {key[1]}: model call id differs')
    for key in recorded_turns:
        if key not in stored_turns:
            problems.append(f'{key[0]} {key[1]}: recorded turn missing from the agent store')
    receipts = 0
    for (agent, turn_id), turn in stored_turns.items():
        call = turn.get('call')
        if call and call.get('call_id'):
            path = DATA / 'models' / call['call_id'] / 'receipt.json'
            if not path.exists():
                problems.append(f'{agent} {turn_id}: model receipt {call["call_id"]} missing')
            else:
                receipt = json.loads(path.read_text())
                receipts += 1
                if receipt['output_hash'] != call['output_hash'] or receipt['status'] != call['status']:
                    problems.append(f'{agent} {turn_id}: model receipt differs from the turn record')
    return {'ok': not problems, 'deliveries_checked': len(delivered), 'turns_checked': len(stored_turns), 'model_receipts_checked': receipts,
            'problems': problems[:50]}


def propagation(run, memories, agents):
    out = []
    for entry in run['injections']:
        reached = {}
        for agent, memory in memories.items():
            holding = [f for f in memory['facts'] if f['key'] == entry['key'] and f['value'] == entry['value'] and f['status'] in ('accepted', 'duplicate', 'superseded')]
            reached[agent] = {'holds_revised_value': bool(holding),
                              'how': sorted({f['origin_kind'] for f in holding}),
                              'final_answer_matches_revised_truth': agents[agent]['correct']}
        replaced = entry.get('replaced') or {}
        stale = {agent: any(f['key'] == entry['key'] and replaced and f['value'] == replaced.get('value') and f['status'] == 'accepted'
                            and not f['superseded_by'] for f in memory['facts']) for agent, memory in memories.items()}
        out.append({'injection': {k: entry[k] for k in ('agent', 'key', 'value', 'unit', 'truth_before_c', 'truth_after_c')},
                    'original_value': replaced.get('value'), 'reached': reached, 'still_holding_original_value': stale})
    return out


def routes(app, lab, authenticated):
    """Operator routes on the observer. A dashboard session or the operator bearer credential is required."""
    def operator(request):
        if request.state.principal == 'operator':
            return 'operator-cli'
        authenticated(request)
        return 'operator-session'

    @app.get('/lab/config')
    async def config_route(request: Request):
        operator(request)
        return lab.config()

    @app.get('/lab/runs')
    async def list_runs(request: Request):
        operator(request)
        return {'runs': lab.runs()}

    @app.post('/lab/runs', status_code=201)
    async def create_run(request: Request):
        principal = operator(request)
        return summary(lab.create(await request.json(), principal))

    @app.get('/lab/runs/{run_id}')
    async def get_run(run_id: str, request: Request, after: int = 0):
        operator(request)
        run = lab.load(run_id)
        return {'run': run, 'events': lab.events(run_id, after)}

    @app.get('/lab/runs/{run_id}/memory')
    async def memory(run_id: str, request: Request):
        operator(request)
        lab.load(run_id)
        try:
            stores = await lab.inspect(run_id)
        except Exception as e:
            raise HTTPException(502, 'agent homebase unavailable: ' + type(e).__name__) from None
        return {'run_id': run_id, 'source': 'read over HTTP from each agent homebase', 'agents': stores}

    @app.post('/lab/runs/{run_id}/{action}')
    async def act(run_id: str, action: str, request: Request):
        operator(request)
        if action == 'pause':
            return lab.pause(run_id)
        if action == 'resume':
            return lab.resume(run_id)
        if action == 'step':
            return lab.step(run_id)
        if action == 'stop':
            return lab.stop(run_id)
        if action == 'inject':
            return await lab.inject(run_id, await request.json())
        raise HTTPException(404)

    @app.get('/lab/compare')
    async def compare(request: Request, trial_key: str):
        operator(request)
        return {'trial_key': trial_key, 'runs': [r for r in lab.runs(200) if r['trial_key'] == trial_key]}
