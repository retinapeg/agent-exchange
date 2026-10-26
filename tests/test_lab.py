"""Rendezvous lab: three agent processes, real local A2A HTTP, fixture brains (no model calls)."""
import asyncio
import json
import shutil
import sqlite3

import pytest

from exchange.client import PeerClient
from exchange.common import DATA, canonical, config, digest, uid
from exchange.failures import RpcFailure
from exchange.lab import audit, evaluate
from exchange.lab_protocol import (AGENTS, LIMITS, MESSAGE_VALIDATOR, ORDER, evidence_digest, evidence_item, mentions,
                                   private_facts, trial, truth)

DONE = ('completed', 'stopped', 'failed')


@pytest.fixture
def op():
    return PeerClient(config(), 'operator')


async def start(op, **spec):
    response = await op.http('observer', 'POST', '/lab/runs', json=spec)
    assert response.status_code == 201, response.text
    return response.json()['id']


async def wait(op, run_id, statuses=DONE, timeout=60):
    for _ in range(timeout * 20):
        body = (await op.http('observer', 'GET', f'/lab/runs/{run_id}')).json()
        if body['run']['status'] in statuses:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f'run {run_id} did not reach {statuses}: {body["run"]["status"]}')


async def stores(op, run_id):
    out = {}
    for agent in ORDER:
        response = await op.http(agent, 'GET', f'/lab/export?run_id={run_id}&prompts=true', limit=4 * 1048576)
        assert response.status_code == 200
        out[agent] = response.json()
    return out


async def act(op, run_id, action, body=None):
    return await op.http('observer', 'POST', f'/lab/runs/{run_id}/{action}', json=body)


# -- protocol units --------------------------------------------------------------------------
def test_trials_are_seeded_and_ground_truth_is_exact():
    fixed = trial('fixed')
    assert fixed['inputs'] == {'heat_load': 120, 'ambient_temperature': 21, 'thermal_resistance': 0.18}
    assert fixed['truth_c'] == 42.6
    assert trial('random', 7) == trial('random', 7) and trial('random', 7) != trial('random', 8)
    assert [f['key'] for f in private_facts('mathematics', fixed['inputs'])] == ['thermal_resistance', 'steady_state_formula']
    assert [f['key'] for f in private_facts('physics', fixed['inputs'])] == ['heat_load']
    # Leak detection matches whole numbers, not fragments of other numbers.
    assert mentions('ambient is 21 °C', 21) and mentions('21.0', 21) and not mentions('42.6 is 21.6 + 21.0x', 2)
    assert not mentions('temperature rise 21.6', 21) and not mentions('A21B', 1) and mentions('R = 0.180 K/W', 0.18)


def test_leak_scan_separates_back_calculation_from_coincidence():
    from exchange.lab import derivation
    # Campaign v1: agents back-solved R_th from a delivered answer. That is inference, not leakage.
    assert derivation(0.481, [198.3, 27.6, 122.9823]) == '(122.9823 - 27.6) / 198.3'
    assert derivation(0.18, [120, 21]) is None  # 21 / 120 = 0.175 matches only at the shown precision
    assert derivation(0.128, [174.1, 23.2, 45.48]) is None  # rounded inputs stay unexplained


def test_homebase_refuses_another_agents_store(tmp_path):
    from exchange.lab_agent import Homebase
    Homebase('physics', root=tmp_path)
    (tmp_path / 'environment').mkdir()
    shutil.copy(tmp_path / 'physics' / 'memory.sqlite', tmp_path / 'environment' / 'memory.sqlite')
    with pytest.raises(ValueError, match='another agent'):
        Homebase('environment', root=tmp_path)
    with pytest.raises(ValueError):
        Homebase('stranger', root=tmp_path)


def test_turn_output_cannot_exceed_limits_or_alter_evidence(tmp_path):
    from exchange.lab_agent import Homebase, LabAgent
    home = Homebase('physics', root=tmp_path)
    agent = LabAgent(config(), home)
    run_id = uid()
    home.seed(run_id, {'mode': 'communication', 'backend': 'fixture', 'model': None, 'task': 't',
                       'facts': private_facts('physics', trial('fixed')['inputs']), 'directory': ['environment', 'mathematics']})
    run, ctx = home.run(run_id), agent.context(run_id)
    output = {'evidence_decisions': [{'evidence_id': 'E9', 'decision': 'accept', 'reason': 'not delivered'}], 'derived_facts': [],
              'answer': {'status': 'final', 'value_celsius': None, 'depends_on': ['A1', 'X5'], 'justification': 'x'}, 'note_to_self': '',
              'messages': [{'to': 'mathematics', 'intent': 'inform', 'content': 'one', 'evidence_fact_ids': ['A1']},
                           {'to': 'environment', 'intent': 'inform', 'content': 'two', 'evidence_fact_ids': ['A1', 'ZZ']},
                           {'to': 'environment', 'intent': 'request', 'content': 'three', 'evidence_fact_ids': []}]}
    summary = agent.apply(run, 'physics-1', 1, output, ctx, True, {'messages_per_turn': 2, 'deliveries_remaining': 12, 'turns_per_agent': 5})
    assert len(summary['queued']) == 2 and summary['dropped'][0]['reason'] == 'over the per-turn message limit'
    assert summary['answer']['status'] == 'provisional' and summary['answer']['depends_on'] == ['A1']
    assert any('unknown fact id ZZ' in w for w in summary['warnings']) and any('E9' in w for w in summary['warnings'])
    sent = summary['queued'][0]['evidence'][0]
    assert (sent['key'], sent['value'], sent['unit']) == ('heat_load', 120, 'W') and evidence_digest(sent) == sent['digest']
    # An identical message in a later turn is suppressed, not sent again.
    again = agent.apply(run, 'physics-2', 2, {**output, 'messages': output['messages'][:1]}, agent.context(run_id), True,
                        {'messages_per_turn': 2, 'deliveries_remaining': 10, 'turns_per_agent': 5})
    assert not again['queued'] and again['suppressed']


# -- live HTTP runtime, fixture brains ----------------------------------------------------------
async def test_memory_isolation_and_authenticated_messaging(op):
    c = config()
    run_id = await start(op, mode='communication', backend='fixture', trial={'kind': 'random', 'seed': 4242})
    body = await wait(op, run_id)
    results = body['run']['results']
    assert body['run']['status'] == 'completed' and results['all_correct']
    # Each agent owns a separate store, and it holds that agent's identity only.
    paths = {a: DATA / a / 'memory.sqlite' for a in ORDER}
    assert len({p.resolve() for p in paths.values()}) == 3
    for agent, path in paths.items():
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT agent_id FROM identity').fetchall() == [(agent,)]
            initial = {r[0] for r in db.execute("SELECT key FROM facts WHERE run_id=? AND origin_kind='initial'", (run_id,))}
        assert initial == {f['key'] for f in private_facts(agent, body['run']['trial']['inputs'])}
    # Another agent, the read-only observer and unknown callers cannot read or drive a homebase.
    for principal in ('physics', 'observer', 'test-other'):
        client = PeerClient(c, principal)
        for path in (f'/lab/export?run_id={run_id}',):
            assert (await client.http('environment', 'GET', path)).status_code == 403
        for route in ('/lab/turn', '/lab/inject', '/lab/gate', '/lab/deliver'):
            assert (await client.http('environment', 'POST', route, json={})).status_code == 403
    from exchange.security import NetworkPolicy
    anonymous = await NetworkPolicy([p['url'] for p in c['peers'].values()]).request('GET', c['peers']['physics']['url'] + f'/lab/export?run_id={run_id}')
    assert anonymous.status_code == 401
    # Authenticated A2A: the envelope sender must be the authenticated principal.
    data = await stores(op, run_id)
    delivered = next(r['body'] for r in data['mathematics']['inbox'] if r['sender'] == 'physics')
    forged = {**delivered, 'message_id': uid(), 'sender': 'environment'}
    physics = PeerClient(c, 'physics')
    with pytest.raises(RpcFailure):
        await physics.rpc('mathematics', 'SendMessage', physics.request(forged))
    outsider = PeerClient(c, 'test-other')
    with pytest.raises(RpcFailure):
        await outsider.rpc('mathematics', 'SendMessage', outsider.request({**delivered, 'message_id': uid(), 'sender': 'test-other'}))
    tampered = {**delivered, 'message_id': uid(), 'evidence': [{**delivered['evidence'][0], 'value': 999}]}
    with pytest.raises(RpcFailure, match='digest'):
        await physics.rpc('mathematics', 'SendMessage', physics.request(tampered))
    # A sender may read only the messages it exchanged with an agent.
    view = (await physics.http('mathematics', 'GET', f'/lab/messages?run_id={run_id}')).json()
    assert view['sent_by_you'] and all(m['sender'] == 'physics' for m in view['sent_by_you'])
    assert all(m['recipient'] == 'physics' for m in view['replies_to_you'])
    assert results['leakage']['count'] == 0 and results['leakage']['checked_turns'] == results['inference']['turns']


async def test_isolated_baseline_forbids_messages_and_prompts_hold_only_private_values(op):
    run_id = await start(op, mode='isolated', backend='fixture', trial={'kind': 'random', 'seed': 4242})
    body = await wait(op, run_id)
    results, inputs = body['run']['results'], body['run']['trial']['inputs']
    assert results['messages']['delivered'] == 0 and results['inference']['turns'] == 3 and results['correct_agents'] == 0
    data = await stores(op, run_id)
    for agent, store in data.items():
        own = {f['key'] for f in private_facts(agent, inputs)}
        for turn in store['turns']:
            for key, value in inputs.items():
                assert mentions(turn['prompt'], value) == (key in own), (agent, key)
            assert 'messages' not in turn['output']
    # Transport refuses messages for an isolated run even from a genuine peer.
    physics = PeerClient(config(), 'physics')
    env = {'schema_version': 'agent-exchange.lab-message.v1', 'message_id': uid(), 'run_id': run_id, 'sender': 'physics', 'recipient': 'mathematics',
           'intent': 'inform', 'content': 'x', 'evidence': [], 'in_reply_to': None, 'created_at': '2026-10-26T00:00:00.000Z',
           'causation': {'turn_id': 't', 'call_id': None, 'brain': 'fixture'}}
    MESSAGE_VALIDATOR.validate(env)
    with pytest.raises(RpcFailure, match='disabled'):
        await physics.rpc('mathematics', 'SendMessage', physics.request(env))


async def test_event_log_matches_every_agent_store(op):
    run_id = await start(op, mode='communication', backend='fixture', trial={'kind': 'fixed'})
    body = await wait(op, run_id)
    events = body['events']
    data = await stores(op, run_id)
    delivered = [e for e in events if e['kind'] == 'message.delivered']
    inbox = {r['message_id']: (a, r) for a, s in data.items() for r in s['inbox']}
    outbox = {r['message_id']: (a, r) for a, s in data.items() for r in s['outbox']}
    assert delivered and len(delivered) == len(inbox) == body['run']['results']['messages']['delivered']
    for e in delivered:
        recipient, row = inbox[e['message_id']]
        sender, sent = outbox[e['message_id']]
        assert (recipient, sender, row['sender']) == (e['recipient'], e['sender'], e['sender'])
        assert row['digest'] == sent['digest'] == e['digest'] == digest(e['envelope']) == digest(row['body'])
        assert sent['status'] == 'delivered' and e['transport']['method'] == 'SendMessage'
        assert e['queued_at'] <= e['sent_at'] <= e['received_at'] <= e['delivered_at']
    turns = {(e['agent'], e['turn_id']) for e in events if e['kind'] == 'turn.finished'}
    assert turns == {(a, t['turn_id']) for a, s in data.items() for t in s['turns']}
    assert len([e for e in events if e['kind'] == 'turn.started']) == len(turns)
    assert body['run']['results']['event_audit']['ok']
    # The audit is not vacuous: a changed inbox row is reported.
    broken = json.loads(json.dumps(data))
    broken['mathematics']['inbox'][0]['digest'] = '0' * 64
    assert not audit(body['run'], broken, events)['ok']


async def test_pause_blocks_inference_and_delivery_then_injection_propagates(op):
    run_id = await start(op, mode='intervention', backend='fixture', trial={'kind': 'random', 'seed': 99})
    body = await wait(op, run_id, ('paused',))
    plan = body['run']['trial']
    assert 'end of round one' in body['run']['pause_reason']
    inject = {k: plan['intervention'][k] for k in ('agent', 'key', 'value', 'unit', 'note')}
    assert (await act(op, run_id, 'inject', {**inject, 'agent': 'nobody'})).status_code == 422
    assert (await act(op, run_id, 'inject', inject)).status_code == 200
    # One step: physics takes a turn and queues a correction. It is queued, not delivered.
    assert (await act(op, run_id, 'step')).status_code == 200
    for _ in range(200):
        body = (await op.http('observer', 'GET', f'/lab/runs/{run_id}')).json()
        if body['run']['status'] == 'paused' and any(e['kind'] == 'run.step' for e in body['events']) and body['events'][-1]['kind'] == 'run.paused':
            break
        await asyncio.sleep(0.05)
    run = body['run']
    assert run['status'] == 'paused' and len(run['queue']) == 1
    queued = run['queue'][0]
    frozen = (len(body['events']), json.dumps(run['counters']))
    await asyncio.sleep(1.5)
    body = (await op.http('observer', 'GET', f'/lab/runs/{run_id}')).json()
    assert (len(body['events']), json.dumps(body['run']['counters'])) == frozen
    data = await stores(op, run_id)
    assert [r['status'] for r in data[queued['sender']]['outbox'] if r['message_id'] == queued['message_id']] == ['queued']
    assert queued['message_id'] not in {r['message_id'] for r in data[queued['recipient']]['inbox']}
    # The gates refuse direct attempts too, not just the scheduler.
    deliver = await op.http(queued['sender'], 'POST', '/lab/deliver', json={'run_id': run_id, 'message_id': queued['message_id']})
    turn = await op.http('environment', 'POST', '/lab/turn', json={'run_id': run_id, 'turn_id': 'manual', 'turn_no': 9,
                                                                   'budget': {'deliveries_remaining': 1, 'messages_per_turn': 1, 'turns_per_agent': 5}})
    assert deliver.status_code == 409 and turn.status_code == 409
    assert (await act(op, run_id, 'resume')).status_code == 200
    body = await wait(op, run_id)
    results = body['run']['results']
    assert (await act(op, run_id, 'inject', inject)).status_code == 409
    assert results['truth']['current_c'] == truth({**plan['inputs'], 'heat_load': inject['value']}) != results['truth']['original_c']
    assert results['all_correct'] and not any(results['agents'][a]['correct_vs_original'] for a in ORDER)
    propagation = results['propagation'][0]
    assert propagation['reached']['mathematics']['holds_revised_value'] and propagation['reached']['mathematics']['how'] == ['received']
    # Original fact and revision history are preserved.
    facts = (await stores(op, run_id))['physics']['facts']
    original = next(f for f in facts if f['origin_kind'] == 'initial' and f['key'] == 'heat_load')
    revised = next(f for f in facts if f['origin_kind'] == 'operator')
    assert original['value'] == plan['inputs']['heat_load'] and original['status'] == 'superseded' and original['superseded_by'] == revised['fact_id']
    assert revised['supersedes'] == original['fact_id'] and revised['revision'] == 2 and revised['value'] == inject['value']


async def test_budgets_stop_an_endless_conversation(op):
    response = await op.http('observer', 'POST', '/lab/runs', json={'mode': 'communication', 'backend': 'fixture', 'limits': {'max_inferences': -1}})
    assert response.status_code == 422
    run_id = await start(op, mode='communication', backend='fixture-chatty', limits={'max_inferences': 50, 'max_deliveries': 99})
    body = await wait(op, run_id)
    run, results = body['run'], body['run']['results']
    assert run['limits']['max_inferences'] == LIMITS['max_inferences'] and run['limits']['max_deliveries'] == LIMITS['max_deliveries']
    assert results['inference']['turns'] <= 12 and results['messages']['attempted'] <= 12 and results['messages']['delivered'] <= 12
    assert results['messages']['withheld'] > 0 and run['stop_reason']
    assert max(len([e for e in body['events'] if e['kind'] == 'turn.started' and e['agent'] == a]) for a in ORDER) <= LIMITS['turns_per_agent']
    run_id = await start(op, mode='communication', backend='fixture', limits={'active_seconds': 0})
    body = await wait(op, run_id)
    assert 'deadline' in body['run']['stop_reason'] and body['run']['results']['inference']['turns'] == 0


async def test_live_runs_need_explicit_operator_approval(op):
    cfg = (await op.http('observer', 'GET', '/lab/config')).json()
    assert cfg['limits']['max_inferences'] == 12 and cfg['limits']['max_deliveries'] == 12
    for approval in (None, {'approve': False, 'binding': cfg['approval_binding']}, {'approve': True, 'binding': 'f' * 64}):
        spec = {'mode': 'isolated', 'backend': 'claude', **({'approval': approval} if approval else {})}
        assert (await op.http('observer', 'POST', '/lab/runs', json=spec)).status_code == 403
    observer = PeerClient(config(), 'observer')
    assert (await observer.http('observer', 'POST', '/lab/runs', json={'mode': 'isolated', 'backend': 'fixture'})).status_code == 401
    runs = (await op.http('observer', 'GET', '/lab/runs')).json()['runs']
    assert not any(r['backend'] == 'claude' for r in runs)


async def test_cards_and_envelopes_follow_the_published_schema(op):
    from exchange.registry import validate_card
    from exchange.security import NetworkPolicy
    c = config()
    net = NetworkPolicy([p['url'] for p in c['peers'].values()])
    for agent in ORDER:
        card = (await net.request('GET', c['peers'][agent]['url'] + '/.well-known/agent-card.json')).json()
        validate_card(card, c['peers'][agent]['url'], agent)
        assert AGENTS[agent]['domain'] in card['skills'][0]['description']
    fact = {'fact_id': 'A1', 'key': 'heat_load', 'value': 120, 'unit': 'W', 'origin_kind': 'initial', 'origin_agent': 'physics', 'origin_fact': 'A1',
            'lineage': [{'agent': 'physics', 'fact_id': 'A1', 'kind': 'initial', 'at': '2026-10-26T00:00:00.000Z'}]}
    item = evidence_item(fact)
    assert item['origin']['kind'] == 'initial' and item['digest'] == evidence_digest(item)
    from exchange.lab_protocol import envelope
    env = envelope(run_id=uid(), sender='physics', recipient='mathematics', intent='inform', content='x', evidence=[item],
                   turn_id='physics-1', call_id=None, brain='fixture')
    MESSAGE_VALIDATOR.validate(env)
    for bad in ({**env, 'intent': 'command'}, {**env, 'extra': 1}, {**env, 'content': 'x' * 601}, {**env, 'sender': 'Not An Id'}):
        assert not MESSAGE_VALIDATOR.is_valid(bad)


async def test_restart_preserves_memories_events_and_resumes_interrupted_run(op):
    from exchange import processes
    done = await start(op, mode='communication', backend='fixture', trial={'kind': 'random', 'seed': 77})
    finished = await wait(op, done)
    paused = await start(op, mode='intervention', backend='fixture', trial={'kind': 'random', 'seed': 78})
    await wait(op, paused, ('paused',))
    before = await stores(op, done)
    await asyncio.to_thread(processes.stop)
    await asyncio.to_thread(processes.start)
    after = await stores(op, done)
    for agent in ORDER:
        for key in ('facts', 'inbox', 'outbox', 'answers', 'snapshots', 'notices'):
            assert canonical(after[agent][key]) == canonical(before[agent][key]), (agent, key)
        assert [t['prompt_hash'] for t in after[agent]['turns']] == [t['prompt_hash'] for t in before[agent]['turns']]
    again = (await op.http('observer', 'GET', f'/lab/runs/{done}')).json()
    assert again['run'] == finished['run'] and again['events'] == finished['events']
    interrupted = (await op.http('observer', 'GET', f'/lab/runs/{paused}')).json()
    assert interrupted['run']['status'] == 'interrupted' and interrupted['events'][-1]['kind'] == 'run.interrupted'
    assert (await act(op, paused, 'resume')).status_code == 200
    body = await wait(op, paused)
    assert body['run']['status'] == 'completed' and body['run']['results']['event_audit']['ok']
    assert any(e['kind'] == 'run.resynced' for e in body['events'])
