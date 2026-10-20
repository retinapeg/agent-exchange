"""Checkpointed two-trial demonstration; live mode is explicit and bounded."""
import asyncio
import json
import time

from exchange.common import DATA, ROOT, config, digest, now, write_json
from exchange.client import PeerClient, checked_artifact
from exchange.evidence import receipt

DOCUMENT = '''Fictional brief: Coastal Data Commons
Purpose: prepare reproducible public climate datasets for research collaborators.
This is a fictional hiring brief. No real applicant or customer is involved.

Required: Parse station observations from CSV files.
Must: Preserve missing values without silently imputing them.
Essential: Check timestamps against the supplied UTC convention.
Must: Reject duplicate station identifiers within one observation batch.
Preferred: Explain uncertainty with a small reproducible example.
Team context: two researchers review every release.

Required: Record the input dataset version and checksum.
Must: Keep validation rules separate from generated narrative.
Nice to have: Experience with geospatial indexing.
Required: Report rejected records with quoted source evidence.
Must: Document assumptions: units, coordinate system, and time interval.
Preferred: Use SQL for transparent aggregation.
Delivery: a reviewed requirements artifact; there is no production deployment.

Essential: Leave unverified claims visibly marked as unknown.
Must: Provide a short handover explaining how to reproduce the results.'''


async def showcase(live=False):
    c=config(); mode='live' if live else 'fixture'
    folder=DATA/'showcases'/('v1-'+mode)
    frozen={'schema_version':'exchange.showcase.v1','mode':mode,'planned':2,'maximum_model_calls':6 if live else 0,
        'maximum_seconds':600,'acceptance':'deterministic-evidence-v1; exact complete source and line count',
        'model':c['model'] if live else None,
        'trials':[{'policy':'fixed','payment_mode':'free','source':DOCUMENT},
                  {'policy':'cheapest','payment_mode':'simulator','source':DOCUMENT+'\nRequired: Retain an auditable payment receipt.'}]}
    plan=folder/'plan.json'
    if plan.exists() and json.loads(plan.read_text())!=frozen:
        raise ValueError('showcase frozen plan changed; preserve it and introduce an explicit new version')
    if not plan.exists(): write_json(plan,frozen)
    raw=[]
    client=PeerClient(c,'operator',recorder=raw.append)
    r=await client.http('registry','POST','/refresh'); r.raise_for_status()
    cards=r.json()['agents']
    eligible=[a for a in cards if a['health']=='reachable' and not a['stale']]
    if len(eligible)!=3: raise ValueError('three healthy configured providers are required')
    results=[]; started=time.monotonic()
    for index,trial in enumerate(frozen['trials']):
        value={k:trial[k] for k in ('policy','payment_mode')}
        if live:
            value.update(backend='live',natural_request='Extract all explicit requirements and exact evidence from this fictional brief. SOURCE:\n'+trial['source'])
        else: value['task']={'service':'requirements','source':trial['source']}
        key=f'showcase-v1-{mode}-{index}'
        submitted=await client.http('buyer','POST','/submit',json=value,headers={'Idempotency-Key':key})
        submitted.raise_for_status(); identity=submitted.json()['run_id']
        while True:
            r=await client.http('buyer','GET','/runs/'+identity); r.raise_for_status()
            run=r.json()
            if run['status'] not in ('queued','running'): break
            if time.monotonic()-started>frozen['maximum_seconds']:
                raise TimeoutError('showcase budget reached; rerun to resume the same operations')
            await asyncio.sleep(.5)
        result=run['result']
        if result.get('task'):
            request=result['task']['history'][0]['parts'][0]['data']
            if checked_artifact(result['task'],request)['accepted'] != result.get('verifier',{}).get('accepted',False):
                raise ValueError('retained showcase verification mismatch')
        results.append(result)
        write_json(folder/'results.json',{'planned':2,'finished':len(results),'verified':sum(r.get('verifier',{}).get('accepted',False) for r in results),'results':results})
        write_json(folder/'wire.json',raw)
    traces={r['run_id'] for r in results}
    events=[]
    for peer in ('buyer','requirements','csv','verifier','ledger'):
        after=0
        while True:
            r=await client.http(peer,'GET',f'/observe?after={after}');r.raise_for_status()
            page=r.json()['events']
            if not page: break
            events.extend(e for e in page if e['trace_id'] in traces)
            after=page[-1]['seq']
    write_json(folder/'events.json',events)
    summary={'created_at':now(),'mode':mode,'planned':2,'finished':len(results),'verified':sum(r.get('verifier',{}).get('accepted',False) for r in results),
        'healthy_cards':3,'providers':[r.get('provider') for r in results],
        'simulated_credits':sum(r.get('payment',{}).get('settled',0) for r in results),'actual_money':0,
        'http_402_observed':any(e['kind']=='payment.challenge' and e.get('http_status')==402 for e in events),
        'three_candidate_quotes':all(len(r.get('decision',{}).get('candidate_set',[]))==3 for r in results),
        'directory':str(folder.relative_to(ROOT)),'plan_digest':digest(frozen)}
    write_json(folder/'summary.json',summary)
    summary['receipt']=receipt('showcase-'+mode,summary,[str(folder.relative_to(ROOT))])
    return summary
