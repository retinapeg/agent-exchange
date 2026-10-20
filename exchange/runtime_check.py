"""Owned-process restart demonstration using one immutable paid operation."""
import asyncio
import json
import os
import signal
import time

from exchange.common import DATA, config, uid, write_json
from exchange.client import PeerClient
from exchange import processes


async def run_once(key):
    client = PeerClient(config(), 'operator')
    response = await client.http('buyer','POST','/run',json={'task':{'service':'requirements','source':'Must: Preserve this task across restart.'},'payment_mode':'simulator'},headers={'Idempotency-Key':key})
    response.raise_for_status()
    result = response.json()
    ledger = (await client.http('ledger','GET','/summary')).json()
    return result, ledger


def restart_check(crash=False):
    before = processes.status()
    if not before['manager_alive'] or not all(v.get('owned') for v in before['services'].values()):
        raise RuntimeError('all services must be owned and healthy before restart check')
    key = uid()
    first, ledger_before = asyncio.run(run_once(key))
    assert first['status'] == 'verified'
    injected = None
    if crash:
        record=json.loads((DATA/'processes.json').read_text())
        owned=record['children']['requirements']
        if not processes.process_matches(owned):
            raise RuntimeError('refuse to signal a process with mismatched ownership')
        os.kill(owned['pid'],signal.SIGKILL)
        injected={'service':'requirements','signal':'SIGKILL','owned_pid':owned['pid'],'created':owned['created']}
        # The supervisor intentionally fails closed when a child crashes.
        for _ in range(100):
            if not processes.process_matches(record['manager']): break
            time.sleep(.1)
    processes.stop()
    offline = processes.status()
    assert not offline['manager_alive'] and all(v['status'] == 'offline' for v in offline['services'].values())
    restarted = processes.start()
    assert all(v.get('owned') for v in restarted['services'].values())
    second, ledger_after = asyncio.run(run_once(key))
    assert first == second and ledger_before['accounts'] == ledger_after['accounts']
    assert ledger_after['conserved']
    result = {'key':key,'run_id':first['run_id'],'task_id':first['task']['id'],'verified':True,'same_cached_response':first == second,
              'balances_unchanged':ledger_before['accounts'] == ledger_after['accounts'],'shutdown_confirmed':offline,'restart_confirmed':restarted,
              'payment':first['payment'],'ledger_conserved':ledger_after['conserved'],'crash_injection':injected}
    # Also retrieve the provider's own durable task, not only the buyer cache.
    remote=asyncio.run(PeerClient(config()).rpc('requirements','GetTask',{'id':first['task']['id']}))
    assert remote == first['task']
    result['provider_task_unchanged']=True
    filename=('crash-restart-' if crash else 'restart-')+key+'.json'
    write_json(DATA/'receipts'/filename,result)
    return {k:v for k,v in result.items() if k not in ('shutdown_confirmed','restart_confirmed','payment')}
