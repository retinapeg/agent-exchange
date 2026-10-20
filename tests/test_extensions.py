import asyncio
import copy
import json

import pytest
from fastapi import HTTPException

from exchange.matchmaking import DisclosureStore, propose, PURPOSE, FIELDS
from exchange.verification import verify
from exchange.integration import Adapter, envelope, VALIDATOR
from exchange.common import config, DATA, write_json, uid
from exchange.client import PeerClient
from exchange.failures import ExchangeFailure

PROFILE = dict(interests=['python','physics'], goals=['reproduce'], availability=['evening'], communication=['async'], timezone='Europe/London')


def test_disclosure_consent_revocation_and_withheld_fields(tmp_path):
    store = DisclosureStore(tmp_path / 'profiles.sqlite')
    a = store.create(PROFILE, sorted(FIELDS-{'timezone'}), 'a@example.invalid', PURPOSE)
    b = store.create(PROFILE, sorted(FIELDS), 'b@example.invalid', PURPOSE)
    outward = store.outward()
    assert 'timezone' not in next(p for p in outward if p['id'] == a['id'])
    assert 'contact' not in json.dumps(outward)
    result = propose(outward)
    assert verify({'service':'match','profiles':outward}, result)['accepted']
    assert len(result['proposals']) == 1
    with pytest.raises(HTTPException):
        store.contacts(a['id'], b['id'], a['owner_consent_token'])
    store.consent(a['id'], b['id'], a['owner_consent_token'], True)
    with pytest.raises(HTTPException):
        store.contacts(a['id'], b['id'], a['owner_consent_token'])
    with pytest.raises(HTTPException):
        store.consent(b['id'], a['id'], a['owner_consent_token'], True)
    store.consent(b['id'], a['id'], b['owner_consent_token'], True)
    assert len(store.contacts(a['id'], b['id'], a['owner_consent_token'])['contacts']) == 2
    store.revoke(b['id'], b['owner_consent_token'])
    assert len(store.outward()) == 1
    with pytest.raises(HTTPException):
        store.contacts(a['id'], b['id'], a['owner_consent_token'])
    with pytest.raises(ExchangeFailure):
        store.outward('dating')


async def test_match_real_a2a_and_agents_cannot_consent():
    client = PeerClient(config())
    profiles = [{'id':uid(), **PROFILE} for _ in range(2)]
    payload = {'service':'match','profiles':profiles}
    task = (await client.rpc('verifier','SendMessage',client.request(payload)))['task']
    from exchange.client import checked_artifact
    assert checked_artifact(task, payload)['accepted']
    r = await client.http('verifier','POST','/disclosures',json={})
    assert r.status_code == 403


async def test_adapter_stub_contract_restart_dedup_and_cursor(tmp_path):
    # Stub source; destination uses actual local A2A sockets. No other project accessed.
    client = PeerClient(config())
    path = tmp_path / 'adapter.sqlite'
    adapter = Adapter(path, client)
    value = envelope('task.requested','continuum-stub','agent-exchange',{'provider':'requirements','task':{'service':'requirements','source':'Must: Contract evidence.'}})
    replies = await asyncio.gather(*[adapter.receive(value,'continuum-stub') for _ in range(4)])
    assert all(r == replies[0] for r in replies)
    VALIDATOR.validate(replies[0])
    assert replies[0]['kind'] == 'task.completed'
    restarted = Adapter(path, client)
    assert await restarted.receive(value, 'continuum-stub') == replies[0]
    assert len(restarted.observed('continuum-stub')) == 1
    assert restarted.observed('continuum-stub',1) == []
    changed = copy.deepcopy(value); changed['payload']['task']['source'] = 'changed'
    with pytest.raises(ExchangeFailure):
        await restarted.receive(changed, 'continuum-stub')
    with pytest.raises(ExchangeFailure):
        await restarted.receive(value, 'leo-os-stub')
    with pytest.raises(Exception):
        VALIDATOR.validate({**value,'extra':'forbidden'})
    write_json(DATA/'receipts'/('integration-stub-'+uid()+'.json'), {'request':value,'response':replies[0],'dedup_verified':True,'actual_cross_project':False})


def test_predeclared_synthetic_comparison_and_contract_fixture():
    from exchange.match_evaluation import evaluate
    from exchange.common import ROOT
    value = evaluate()
    assert value['results']['constrained']['constraint_violations'] == 0
    assert value['results']['constrained']['simulated_mutual_acceptance'] == 2
    assert value['results']['tag-overlap']['constraint_violations'] == 3
    VALIDATOR.validate(json.loads((ROOT/'integration/envelope.example.json').read_text()))
