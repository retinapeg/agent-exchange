"""Injected infrastructure faults; these tests never invoke a real model."""
import asyncio
import json
import sys

import httpx
import psutil
import pytest

from exchange import models
from exchange.common import config, DATA, uid, digest
from exchange.client import PeerClient
from exchange.coordinator import Coordinator
from exchange.integration import ObserverAdapter, envelope
from exchange.failures import ExchangeFailure


def isolated_model(monkeypatch, tmp_path, timeout=2):
    settings = {**config()['model'], 'timeout': timeout}
    monkeypatch.setattr(models, 'ROOT', tmp_path)
    monkeypatch.setattr(models, 'DATA', tmp_path/'local_data')
    monkeypatch.setattr(models, 'config', lambda: {'model': settings})
    monkeypatch.setattr(models.shutil, 'which', lambda _: sys.executable)
    return settings


async def test_failed_model_switch_requires_explicit_new_operation(tmp_path, monkeypatch):
    isolated_model(monkeypatch, tmp_path)
    monkeypatch.setattr(models, 'command', lambda *a: [sys.executable, '-c', 'import sys; sys.exit(9)'])
    trace = uid()
    with pytest.raises(RuntimeError, match='CLI exited 9'):
        await models.call_model('source', {'type':'object'}, trace)
    with pytest.raises(ValueError, match='changed-content reuse'):
        await models.call_model('source', {'type':'object'}, trace, backend='codex', model='injected-switch')
    with pytest.raises(ValueError, match='no automatic retry'):
        await models.call_model('source', {'type':'object'}, trace)
    with models.model_db().connect() as db:
        assert db.execute('SELECT COUNT(*) FROM calls').fetchone()[0] == 1
    receipt = json.loads(next((tmp_path/'local_data/models').glob('*/receipt.json')).read_text())
    assert receipt['status']=='failed' and receipt['actual_observed_charge'] is None


async def test_cli_timeout_cleans_its_owned_child_group(tmp_path, monkeypatch):
    isolated_model(monkeypatch, tmp_path, timeout=.4)
    child_path=tmp_path/'child.pid'
    script="import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    monkeypatch.setattr(models, 'command', lambda *a: [sys.executable,'-c',script,str(child_path)])
    with pytest.raises(TimeoutError):
        await models.call_model('source', {'type':'object'}, uid())
    child=int(child_path.read_text())
    for _ in range(30):
        if not psutil.pid_exists(child) or psutil.Process(child).status()==psutil.STATUS_ZOMBIE: break
        await asyncio.sleep(.02)
    else: raise AssertionError('owned CLI child survived timeout')


async def test_model_budget_is_shared_across_runtime_directories(tmp_path, monkeypatch):
    settings=isolated_model(monkeypatch,tmp_path)
    settings['max_calls']=1
    monkeypatch.setattr(models,'command',lambda *a:[sys.executable,'-c','print(\'{"type":"result","structured_output":{}}\')'])
    monkeypatch.setattr(models,'DATA',tmp_path/'local_data/one')
    assert await models.call_model('source',{'type':'object'},uid())=={}
    monkeypatch.setattr(models,'DATA',tmp_path/'local_data/two')
    with pytest.raises(ValueError,match='ceiling'):
        await models.call_model('source',{'type':'object'},uid())


async def test_model_cannot_silently_truncate_source(monkeypatch):
    async def truncated(*a, **kw):
        return {'service':'requirements','provider':'requirements','source':'Must: Keep A.', 'missing_requirements':[], 'reason':'injected'}
    monkeypatch.setattr(models, 'call_model', truncated)
    listings=[{'peer':'requirements','health':'reachable','stale':False,'card':{'skills':[{'id':'requirements'}]}}]
    with pytest.raises(ValueError, match='truncated'):
        await models.plan_request('Extract SOURCE:\nMust: Keep A.\nMust: Keep B.',listings,uid())


async def test_verifier_infrastructure_failure_preserves_paid_receipt(tmp_path, monkeypatch):
    from exchange import coordinator
    c=Coordinator(config(),tmp_path)
    def broken(*a): raise RuntimeError('injected verifier unavailable')
    monkeypatch.setattr(coordinator,'checked_artifact',broken)
    value={'task':{'service':'requirements','source':'Must: Retain payment evidence.'},'payment_mode':'simulator','policy':'cheapest'}
    identity=c.admit(value,'operator',uid())
    first=await c.execute(identity)
    assert first['status']=='failed' and first['failure_category']=='verification'
    assert first['payment']['receipt'] and first['payment']['state']=='settled'
    client=PeerClient(config(),'operator')
    before=(await client.http('ledger','GET','/summary')).json()['accounts']
    assert await Coordinator(config(),tmp_path).execute(identity)==first
    assert (await client.http('ledger','GET','/summary')).json()['accounts']==before


def test_observer_adapter_preview_replay_and_restart(tmp_path):
    path=tmp_path/'observer.sqlite'
    preview={'task':{'source':'synthetic'},'quote':{'amount':3}}
    value=envelope('approval.requested','agent-exchange','leo-os-stub',{
        'capability':'simulator-payment','reason':'test','approval_id':uid(),'preview':preview,'binding':digest(preview)})
    adapter=ObserverAdapter(path)
    adapter.receive(1,value,'agent-exchange')
    restarted=ObserverAdapter(path)
    restarted.receive(1,value,'agent-exchange')
    assert restarted.cursor()==1
    with pytest.raises(ExchangeFailure,match='source'):
        restarted.receive(1,value,'forged')
    with pytest.raises(ExchangeFailure,match='replay'):
        restarted.receive(1,{**value,'idempotency_key':'changed'},'agent-exchange')
    with pytest.raises(ExchangeFailure,match='gap'):
        restarted.receive(3,{**value,'message_id':uid()},'agent-exchange')


async def test_dashboard_mutations_require_same_origin_operator_session():
    c=config(); origin=c['peers']['observer']['url']
    async with httpx.AsyncClient(base_url=origin,trust_env=False) as client:
        for path in ('/submit','/approvals/'+uid(),'/runs/'+uid()+'/resume'):
            assert (await client.post(path,json={})).status_code==401
        assert (await client.post('/session',json={'token':c['peers']['observer']['tokens']['operator']})).status_code==200
        assert (await client.post('/submit',json={},headers={'Origin':'https://attacker.invalid'})).status_code==403
        assert (await client.post('/approvals/'+uid(),json={'binding':'forged','approve':True})).status_code==409


async def test_showcase_replays_verified_operations_without_another_charge():
    from exchange.showcase import showcase
    first=await showcase()
    assert first['verified']==2 and first['http_402_observed'] and first['three_candidate_quotes']
    client=PeerClient(config(),'operator')
    before=(await client.http('ledger','GET','/summary')).json()['accounts']
    second=await showcase()
    assert second['verified']==2
    assert (await client.http('ledger','GET','/summary')).json()['accounts']==before


async def test_free_collaboration_survives_ledger_process_outage():
    import os
    import signal
    from exchange import processes
    record=json.loads((DATA/'processes.json').read_text())
    owned=record['children']['ledger']
    assert processes.process_matches(owned)
    c=PeerClient(config(),'operator')
    before=(await c.http('ledger','GET','/summary')).json()['accounts']
    os.kill(owned['pid'],signal.SIGTERM)
    try:
        for _ in range(100):
            if not processes.process_matches(owned): break
            await asyncio.sleep(.05)
        assert not processes.process_matches(owned)
        assert processes.process_matches(record['manager'])
        payload={'task':{'service':'requirements','source':'Must: Work without payment infrastructure.'},'policy':'cheapest'}
        r=await c.http('buyer','POST','/run',json=payload,headers={'Idempotency-Key':uid()})
        free=r.json(); assert free['status']=='verified' and free['agreed_quote']['amount']==0
        quotes=(await c.http(free['provider'],'GET','/quotes')).json()['quotes']
        assert next(q for q in quotes if q['quote']['quote_id']==free['agreed_quote']['quote_id'])['state']=='accepted'
        key=uid()
        paid_request={**payload,'payment_mode':'simulator'}
        r=await c.http('buyer','POST','/run',json=paid_request,headers={'Idempotency-Key':key})
        uncertain=r.json(); assert uncertain['status']=='outcome-unknown'
    finally:
        await asyncio.to_thread(processes.stop)
        await asyncio.to_thread(processes.start)
    assert (await c.http('ledger','GET','/summary')).json()['accounts']==before
    r=await c.http('buyer','POST','/run',json=paid_request,headers={'Idempotency-Key':key})
    recovered=r.json(); assert recovered['status']=='verified' and recovered['run_id']==uncertain['run_id']
    after=(await c.http('ledger','GET','/summary')).json()['accounts']
    assert before['buyer']-after['buyer']==3
    assert (await c.http('buyer','POST','/run',json=paid_request,headers={'Idempotency-Key':key})).json()==recovered
    assert (await c.http('ledger','GET','/summary')).json()['accounts']==after


def test_port_reservation_refuses_existing_listener():
    import socket
    from exchange.processes import reserve_ports
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(('127.0.0.1',0)); listener.listen()
        port=listener.getsockname()[1]
        with pytest.raises(RuntimeError,match='already occupied'):
            reserve_ports({'unrelated':{'port':port}})
        assert listener.fileno()>=0
