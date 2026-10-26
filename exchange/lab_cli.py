"""Terminal driver for the rendezvous lab. It uses the observer's HTTP API, exactly like the dashboard."""
from __future__ import annotations

import asyncio
import json
import secrets

from exchange.client import PeerClient
from exchange.common import DATA, ROOT, config, digest, now, write_json
from exchange.lab_protocol import ORDER

CAMPAIGN = DATA / 'experiments' / 'rendezvous-v1'
SOURCES = ['exchange/lab.py', 'exchange/lab_agent.py', 'exchange/lab_protocol.py', 'exchange/models.py', 'integration/lab-message.schema.json']


def source_digest():
    return digest({p: digest((ROOT / p).read_bytes()) for p in SOURCES})


def spec_for(mode, trial, backend, cfg, approve_live):
    spec = {'mode': mode, 'backend': backend, 'trial': trial}
    if backend == 'claude':
        if not approve_live:
            raise SystemExit('Live Claude runs need --approve-live (at most 12 CLI calls and 12 messages per run, no retries).')
        spec['approval'] = {'approve': True, 'binding': cfg['approval_binding']}
    return spec


async def drive(client, spec, inject=True):
    response = await client.http('observer', 'POST', '/lab/runs', json=spec)
    if response.status_code != 201:
        raise SystemExit(f'run refused ({response.status_code}): {response.text[:300]}')
    run_id = response.json()['id']
    while True:
        run = (await client.http('observer', 'GET', f'/lab/runs/{run_id}')).json()['run']
        if run['status'] == 'paused' and run['mode'] == 'intervention' and inject and not run['injections']:
            plan = run['trial']['intervention']
            for path, body in ((f'/lab/runs/{run_id}/inject', {k: plan[k] for k in ('agent', 'key', 'value', 'unit', 'note')}),
                               (f'/lab/runs/{run_id}/resume', None)):
                answer = await client.http('observer', 'POST', path, json=body)
                if answer.status_code != 200:
                    raise SystemExit(f'{path} refused ({answer.status_code}): {answer.text[:300]}')
        if run['status'] in ('completed', 'stopped', 'failed'):
            return run
        await asyncio.sleep(0.5)


def compact(run):
    r = run['results'] or {}
    out = {'run_id': run['id'], 'status': run['status'], 'mode': run['mode'], 'backend': run['backend'], 'model': run['model'],
           'trial': {'kind': run['trial']['kind'], 'seed': run['trial']['seed'], 'inputs': run['trial']['inputs']},
           'stop_reason': run['stop_reason'], 'error': run.get('error')}
    if r:
        out.update({'truth_c': r['truth']['current_c'], 'original_truth_c': r['truth']['original_c'],
                    'answers': {a: (v['final_answer'] or {}).get('value') if (v['final_answer'] or {}).get('status') == 'final' else None for a, v in r['agents'].items()},
                    'answer_status': {a: (v['final_answer'] or {}).get('status') for a, v in r['agents'].items()},
                    'correct': {a: v['correct'] for a, v in r['agents'].items()}, 'correct_agents': r['correct_agents'], 'all_correct': r['all_correct'],
                    'delivered': r['messages']['delivered'], 'withheld': r['messages']['withheld'], 'suppressed': r['messages']['suppressed_duplicates'],
                    'by_intent': r['messages']['by_intent'], 'turns': r['inference']['turns'], 'model_calls': r['inference']['model_calls'],
                    'failed_turns': r['inference']['failed_turns'], 'observed_models': r['inference']['observed_models'],
                    'cli_internal_turns': r['inference']['cli_internal_turns'], 'reported_usage': r['inference']['reported_usage'],
                    'model_latency_ms': r['inference']['model_latency_ms'], 'active_seconds': r['latency']['active_seconds'],
                    'wall_seconds': r['latency']['wall_seconds'], 'facts_learned': r['information']['facts_learned'],
                    'learned': {a: [f'{f["key"]}={f["value"]} from {f["from"]}' for f in v['learned']] for a, v in r['agents'].items()},
                    'inputs_held_at_end': r['information']['inputs_held_at_end'],
                    'claims': r['claims']['total'], 'unverified_claims': r['claims']['unverified'], 'stale_claims': r['claims']['stale'],
                    'unverified_items': [{k: c.get(k) for k in ('agent', 'kind', 'id', 'value', 'reason')} for c in r['claims']['items'] if c['verdict'] != 'evidence-backed'],
                    'leakage': r['leakage']['count'], 'leakage_findings': r['leakage']['findings'], 'event_audit_ok': r['event_audit']['ok'],
                    'audit_problems': r['event_audit']['problems'], 'propagation': r.get('propagation')})
    return out


def lab_run(mode, trial_kind, seed, backend, approve_live):
    async def main():
        client = PeerClient(config(), 'operator')
        cfg = (await client.http('observer', 'GET', '/lab/config')).json()
        trial = {'kind': trial_kind, **({'seed': seed} if seed is not None else {})}
        return compact(await drive(client, spec_for(mode, trial, backend, cfg, approve_live)))
    return asyncio.run(main())


def freeze():
    """Write the campaign plan once, with fresh seeds, before any scored run."""
    path = CAMPAIGN / 'plan.json'
    if path.exists():
        plan = json.loads(path.read_text())
        return {'plan': str(path.relative_to(ROOT)), 'plan_sha256': digest(plan), 'already_frozen': True}
    cfg = asyncio.run(PeerClient(config(), 'operator').http('observer', 'GET', '/lab/config')).json()
    plan = {'schema_version': 'agent-exchange.rendezvous-campaign.v1', 'frozen_at': now(), 'model': cfg['model'], 'limits': cfg['limits'],
            'brain': 'claude', 'conditions': ['isolated', 'communication', 'intervention'],
            'trials': [{'kind': 'fixed'}, {'kind': 'random', 'seed': secrets.randbits(40)}, {'kind': 'random', 'seed': secrets.randbits(40)}],
            'order': 'for each trial in order: isolated, then communication, then intervention; one run each; no repeats',
            'intervention_rule': 'auto-pause at the end of round one; inject the trial plan revision (physics heat_load x U(1.2,1.6), seeded) into physics only; resume',
            'primary_outcome': 'agents holding a correct final answer (|answer - ground truth| <= 0.05 C), per run',
            'secondary_outcomes': ['all three correct', 'delivered messages', 'model calls', 'active seconds', 'facts learned from others',
                                   'unverified claims', 'leakage findings', 'event audit', 'intervention propagation'],
            'source_sha256': source_digest(), 'sources': SOURCES,
            'notes': 'Descriptive pilot: one stochastic run per cell, no significance testing. Failed or interrupted runs are reported, never re-run.'}
    write_json(path, plan)
    return {'plan': str(path.relative_to(ROOT)), 'plan_sha256': digest(plan), 'already_frozen': False, 'trials': plan['trials']}


def campaign(approve_live):
    path = CAMPAIGN / 'plan.json'
    if not path.exists():
        raise SystemExit('Freeze the plan first: ./exchange.sh lab-campaign --freeze')
    plan = json.loads(path.read_text())
    if plan['source_sha256'] != source_digest():
        raise SystemExit('Lab source changed since the plan was frozen; a new plan (new folder) is required.')
    results_path = CAMPAIGN / 'results.json'
    results = json.loads(results_path.read_text()) if results_path.exists() else {'plan_sha256': digest(plan), 'runs': {}}

    async def main():
        client = PeerClient(config(), 'operator')
        cfg = (await client.http('observer', 'GET', '/lab/config')).json()
        if cfg['model'] != plan['model'] or cfg['limits'] != plan['limits']:
            raise SystemExit('Configured model or limits differ from the frozen plan.')
        for trial in plan['trials']:
            key = 'fixed' if trial['kind'] == 'fixed' else f'random:{trial["seed"]}'
            for mode in plan['conditions']:
                cell = f'{key}|{mode}'
                if cell in results['runs']:
                    continue  # Scored runs are never repeated.
                print(f'running {cell}', flush=True)
                run = await drive(client, spec_for(mode, trial, plan['brain'], cfg, approve_live))
                results['runs'][cell] = compact(run)
                write_json(results_path, results)
        return results
    asyncio.run(main())
    return report()


def report():
    results = json.loads((CAMPAIGN / 'results.json').read_text())
    plan = json.loads((CAMPAIGN / 'plan.json').read_text())
    runs = results['runs']
    lines = [f'Plan sha256 {digest(plan)} · frozen {plan["frozen_at"]} · model {plan["model"]}', '',
             '| Trial | Condition | Correct agents | Answers A · B · C | Truth °C | Delivered | Model calls | Active s | Facts learned | Unverified claims | Leakage | Audit |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    totals = {}
    order = ['fixed' if t['kind'] == 'fixed' else f'random:{t["seed"]}' for t in plan['trials']]
    cells = sorted(runs, key=lambda cell: (order.index(cell.split('|')[0]), plan['conditions'].index(cell.split('|')[1])))
    for cell in cells:
        r = runs[cell]
        key, mode = cell.split('|')
        if 'correct_agents' not in r:
            lines.append(f'| {key} | {mode} | {r["status"]} | — | — | — | — | — | — | — | — | — |')
            continue
        answers = ' · '.join('—' if r['answers'][a] is None else f'{r["answers"][a]:g}' for a in ORDER)
        truth = f'{r["truth_c"]:g}' + (f' (was {r["original_truth_c"]:g})' if r['truth_c'] != r['original_truth_c'] else '')
        lines.append(f'| {key} | {mode} | {r["correct_agents"]}/3 | {answers} | {truth} | {r["delivered"]} | {r["model_calls"]} | {r["active_seconds"]} | '
                     f'{r["facts_learned"]} | {r["unverified_claims"]}/{r["claims"]} | {r["leakage"]} | {"ok" if r["event_audit_ok"] else "PROBLEMS"} |')
        t = totals.setdefault(mode, {'runs': 0, 'correct': 0, 'all': 0, 'delivered': 0, 'calls': 0, 'seconds': 0.0, 'learned': 0, 'unverified': 0, 'claims': 0, 'leakage': 0})
        t['runs'] += 1; t['correct'] += r['correct_agents']; t['all'] += r['all_correct']; t['delivered'] += r['delivered']; t['calls'] += r['model_calls']
        t['seconds'] += r['active_seconds']; t['learned'] += r['facts_learned']; t['unverified'] += r['unverified_claims']; t['claims'] += r['claims']; t['leakage'] += r['leakage']
    lines += ['', '| Condition | Runs | Correct agents | Runs with all three correct | Delivered messages | Model calls | Mean active s | Facts learned | Unverified claims | Leakage |',
              '|---|---|---|---|---|---|---|---|---|---|']
    for mode in plan['conditions']:
        t = totals.get(mode)
        if t:
            lines.append(f'| {mode} | {t["runs"]} | {t["correct"]}/{3 * t["runs"]} | {t["all"]}/{t["runs"]} | {t["delivered"]} | {t["calls"]} | '
                         f'{t["seconds"] / t["runs"]:.1f} | {t["learned"]} | {t["unverified"]}/{t["claims"]} | {t["leakage"]} |')
    text = '\n'.join(lines) + '\n'
    (CAMPAIGN / 'summary.md').write_text(text)
    return {'summary': str((CAMPAIGN / 'summary.md').relative_to(ROOT)), 'cells': len(runs), 'table': text}
