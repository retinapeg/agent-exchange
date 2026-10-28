import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
from fastapi import HTTPException

from exchange.consumer import Engine, SHARE_FIELDS, create_app, score_pair, seed_demo


def profile(theme, goal, offer, seek, *, style='collaborative', timezone='Europe/London'):
    return {'interests': [theme], 'goals': [goal], 'offers': [offer], 'seeks': [seek],
            'style': style, 'timezone': timezone}


@pytest.fixture
def db(tmp_path):
    return Engine(tmp_path / 'consumer.sqlite', threshold=75, min_cohort=15, quiet_seconds=0)


def make_pool(engine, count=20):
    from exchange.consumer import seed_demo
    return seed_demo(engine)


def test_20_independent_users_exclusive_global_matching(db):
    result = make_pool(db)
    assert result['seeded'] == 20
    assert result['created'] == 10
    assert result['unmatched'] == 0
    with db.connect() as c:
        pairs = c.execute('SELECT a,b,score FROM matches WHERE state="proposed"').fetchall()
        members = c.execute('SELECT user_id,match_id FROM active_members').fetchall()
    assert len(pairs) == 10 and len(members) == 20
    assert len({m['user_id'] for m in members}) == 20
    assert all(r['score'] >= 75 for r in pairs)
    assert all(db.match_round(force=True)['created'] == 0 for _ in range(2))


def test_missing_consent_not_joined(db):
    u, _ = db.register('Test Owner', 'owner@example.org', 'not-a-real-password')
    p = profile('agent systems', 'ship tools', 'python', 'design')
    with pytest.raises(HTTPException) as err:
        db.submit(u, p, list(SHARE_FIELDS), False)
    assert err.value.status_code == 422
    assert db.status(u)['joined'] is False
    with pytest.raises(HTTPException):
        db.preview({**p, 'private_health': 'not allowed'}, list(SHARE_FIELDS))
    with pytest.raises(HTTPException):
        db.preview({**p, 'interests': ['contact: me@domain.com']}, list(SHARE_FIELDS))


def test_only_approved_fields_affect_matching(db):
    a, _ = db.register('One', 'one@example.org', 'a-strong-password')
    p = profile('agent systems', 'ship tools', 'python', 'product')
    db.submit(a, p, ['interests', 'goals'], True)
    s = db.status(a)
    assert s['profile'] == {'interests': ['agent systems'], 'goals': ['ship tools']}
    assert 'offers' not in s['profile'] and 'timezone' not in s['profile']
    assert score_pair(s['profile'], s['profile'])['score'] == 55


def test_threshold_filters_and_no_forced_match(db):
    for i in range(15):
        u, _ = db.register(f'Disjoint {i}', f'disjoint{i}@example.org', 'long-and-safe-pass')
        db.submit(u, profile(f'interest {i}', f'goal {i}', f'skill {i}', f'need {i}'), list(SHARE_FIELDS), True)
    result = db.match_round(force=True)
    assert result['created'] == 0 and result['unmatched'] == 15
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 0


def test_no_matching_before_minimum_cohort(db):
    for i in range(14):
        u, _ = db.register(f'Test {i}', f'test{i}@example.org', 'strong-test-password')
        db.submit(u, profile('shared interest', 'shared goal', 'python', 'design'), list(SHARE_FIELDS), True)
    result = db.match_round(force=True)
    assert result['created'] == 0 and result['reason'] == 'awaiting-cohort'


def test_both_must_accept_before_contact_released(db):
    make_pool(db)
    with db.connect() as c:
        match = c.execute('SELECT a,b FROM matches LIMIT 1').fetchone()
        a,b = match['a'],match['b']
    assert db.status(a)['match']['partner_email'] is None
    assert db.decide(a, 'accept')['state'] == 'waiting-for-partner'
    assert db.status(a)['match']['partner_email'] is None
    assert db.decide(b, 'accept')['state'] == 'accepted'
    assert db.status(a)['match']['partner_email'].endswith('@example.invalid')
    assert db.status(b)['match']['partner_email'].endswith('@example.invalid')


def test_decline_prevents_same_pair_and_requeues(db):
    make_pool(db)
    with db.connect() as c:
        m = c.execute('SELECT a,b FROM matches LIMIT 1').fetchone()
    a,b = m['a'],m['b']
    result = db.decide(a, 'decline')
    assert result['state'] == 'declined'
    assert db.status(a)['match'] is None
    assert db.status(b)['match'] is None
    db.match_round(force=True)
    assert db.status(a)['match'] is None  # unique theme; no substitute above threshold
    assert db.status(b)['match'] is None


def test_revoke_erases_profile_and_unassigns_partner(db):
    make_pool(db)
    with db.connect() as c:
        m = c.execute('SELECT a,b FROM matches LIMIT 1').fetchone()
    a,b = m['a'],m['b']
    db.revoke(a)
    assert db.status(b)['match'] is None
    assert db.status(a)['profile'] is None
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM api_tokens WHERE user_id=?',(a,)).fetchone()[0] == 0
        assert c.execute('SELECT email FROM users WHERE id=?',(a,)).fetchone()[0].endswith('@example.invalid')


def test_concurrent_rounds_never_assign_twice(db):
    make_pool(db)
    # The original matches exist. Create declined pair then allow one new compatible partner.
    with db.connect() as c:
        m = c.execute('SELECT a,b FROM matches LIMIT 1').fetchone()
    db.decide(m['a'], 'decline')
    p = db.status(m['a'])['profile']
    user, _ = db.register('New Alternative', 'alternative@example.org', 'another-strong-pass')
    db.submit(user, p, list(SHARE_FIELDS), True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: db.match_round(force=True), range(32)))
    assert sum(r['created'] for r in results) <= 1
    with db.connect() as c:
        members = [r['user_id'] for r in c.execute('SELECT user_id FROM active_members')]
    assert len(members) == len(set(members))


@pytest.mark.asyncio
async def test_real_web_end_to_end_and_isolation(tmp_path):
    app = create_app(path=tmp_path / 'web.sqlite', min_cohort=2, quiet_seconds=0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as a, \
               httpx.AsyncClient(transport=transport, base_url='http://testserver') as b:
        pa = profile('machine learning', 'build something', 'python', 'design')
        pb = profile('machine learning', 'build something', 'design', 'python')
        ra = await a.post('/api/register', json={'name':'Person A','email':'a@example.org','password':'password-alpha'})
        rb = await b.post('/api/register', json={'name':'Person B','email':'b@example.org','password':'password-bravo'})
        assert ra.status_code == 200 and rb.status_code == 200
        r = await a.post('/api/profile', json={'profile':pa,'approved_fields':list(SHARE_FIELDS),'consent':False})
        assert r.status_code == 422
        r = await a.post('/api/preview', json={'profile':pa,'approved_fields':list(SHARE_FIELDS)})
        assert r.status_code == 200 and r.json()['shared']['interests'] == ['machine learning']
        for client,p in ((a,pa),(b,pb)):
            r = await client.post('/api/profile', json={'profile':p,'approved_fields':list(SHARE_FIELDS),'consent':True})
            assert r.status_code == 200
        sa=(await a.get('/api/me')).json()
        sb=(await b.get('/api/me')).json()
        assert sa['match']['partner_name'] == 'Person B'
        assert sb['match']['partner_name'] == 'Person A'
        assert sa['match']['score'] == 100
        assert sa['match']['partner_email'] is None
        assert (await a.post('/api/decision',json={'decision':'accept'})).status_code==200
        assert (await a.get('/api/me')).json()['match']['partner_email'] is None
        await b.post('/api/decision',json={'decision':'accept'})
        assert (await a.get('/api/me')).json()['match']['partner_email']=='b@example.org'
        assert (await b.get('/api/me')).json()['match']['partner_email']=='a@example.org'
        assert (await a.get('/api/demo/overview')).status_code==404
        assert (await a.get('/')).status_code==200
        assert 'Find someone' in (await a.get('/')).text
        assert (await a.get('/consumer.js')).status_code==200


@pytest.mark.asyncio
async def test_mcp_token_draft_only_human_approval(tmp_path):
    app = create_app(path=tmp_path/'mcp.sqlite', min_cohort=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as web:
        await web.post('/api/register',json={'name':'Sample','email':'sample@example.org','password':'long-password-test'})
        token=(await web.post('/api/tokens')).json()['token']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',headers={'Authorization':'Bearer '+token}) as mcp:
            p=profile('open source','ship a product','python','design')
            r=await mcp.post('/api/drafts',json={'profile':p,'approved_fields':['interests','goals']})
            assert r.status_code==200
            assert r.json()['status']=='pending-owner-approval'
            assert (await mcp.post('/api/profile',json={'profile':p,'approved_fields':['interests','goals'],'consent':True})).status_code==403
            assert (await mcp.post('/api/decision',json={'decision':'accept'})).status_code==403
            assert (await mcp.delete('/api/account')).status_code==403
            assert not (await mcp.get('/api/me')).json()['joined']
        s=(await web.get('/api/me')).json()
        assert s['draft'] == p
        assert s['draft_fields']==['interests','goals']
        assert (await web.post('/api/profile',json={'profile':s['draft'],'approved_fields':s['draft_fields'],'consent':True})).status_code==200
        assert (await web.get('/api/me')).json()['joined']
        await web.delete('/api/tokens')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',headers={'Authorization':'Bearer '+token}) as mcp:
            assert (await mcp.get('/api/me')).status_code==401


@pytest.mark.asyncio
async def test_20_concurrent_web_signups_and_approval(tmp_path):
    app=create_app(path=tmp_path/'concurrent.sqlite',min_cohort=15,quiet_seconds=0)
    async def join(i):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
            r=await c.post('/api/register',json={'name':f'Participant {i}', 'email':f'p{i}@example.org','password':'long-test-password'})
            assert r.status_code==200, r.text
            # Exactly ten realistic matching themes, each with complementary offers/seeks.
            theme=f'project {i//2}'
            offer='backend' if i%2 else 'design'
            seek='design' if i%2 else 'backend'
            p=profile(theme, f'launch {i//2}',offer,seek)
            r=await c.post('/api/profile',json={'profile':p,'approved_fields':list(SHARE_FIELDS),'consent':True})
            assert r.status_code==200, r.text
            return (await c.get('/api/me')).status_code
    codes=await asyncio.gather(*(join(i) for i in range(20)))
    assert all(code==200 for code in codes)
    matches=app.state.engine.match_round(force=True)
    with app.state.engine.connect() as c:
        members=c.execute('SELECT user_id FROM active_members').fetchall()
        pairs=c.execute('SELECT * FROM matches WHERE state="proposed"').fetchall()
    assert len(members)==20 and len(pairs)==10
    assert len({m['user_id'] for m in members})==20
    assert matches['created'] in (0,10)  # Can already have been matched by a polling request.


def test_default_pool_starts_with_two_and_shows_project_ideas(tmp_path):
    engine = Engine(tmp_path / 'two.sqlite', quiet_seconds=0)
    assert engine.min_cohort == 2  # Fifteen was capacity, never a signup minimum.
    a, _ = engine.register('Person One', 'one@demo.test', 'password-not-real')
    b, _ = engine.register('Person Two', 'two@demo.test', 'password-not-real')
    engine.submit(a, profile('open source', 'ship a product', 'python', 'design'), list(SHARE_FIELDS), True)
    engine.submit(b, profile('open source', 'ship a product', 'design', 'python'), list(SHARE_FIELDS), True)
    assert engine.match_round(force=True)['created'] == 1
    sa, sb = engine.status(a)['match'], engine.status(b)['match']
    assert sa['score'] == sb['score'] == 100
    assert sa['explanation']['project_ideas']
    assert sa['partner_context']['interests'] == ['open source']
    assert sb['partner_context']['interests'] == ['open source']


def test_two_people_see_score_even_below_matching_threshold(tmp_path):
    engine = Engine(tmp_path / 'low.sqlite', quiet_seconds=0)
    a, _ = engine.register('Person One', 'one@demo.test', 'password-not-real')
    b, _ = engine.register('Person Two', 'two@demo.test', 'password-not-real')
    engine.submit(a, profile('neuroscience', 'study cognition', 'python', 'statistics'), list(SHARE_FIELDS), True)
    engine.submit(b, profile('community events', 'host local meetups', 'fundraising', 'operations'), list(SHARE_FIELDS), True)
    assert engine.match_round(force=True)['created'] == 0
    sa, sb = engine.status(a), engine.status(b)
    assert sa['match'] is None and sb['match'] is None
    assert sa['compatibility_preview']['score'] == sb['compatibility_preview']['score']
    assert sa['compatibility_preview']['score'] < 75
    assert sa['compatibility_preview']['qualified_match'] is False
    assert sa['compatibility_preview']['explanation']['project_ideas']
    assert sa['compatibility_preview'].get('partner_email') is None
    assert sb['compatibility_preview'].get('partner_linkedin') is None


def test_linkedin_contact_is_explicit_opt_in_and_can_be_revoked(tmp_path):
    engine = Engine(tmp_path / 'links.sqlite', quiet_seconds=0)
    a, _ = engine.register('Person One', 'one@demo.test', 'password-not-real')
    b, _ = engine.register('Person Two', 'two@demo.test', 'password-not-real')
    for user in (a, b):
        engine.submit(user, profile('agent design', 'ship apps', 'python', 'product design'), list(SHARE_FIELDS), True)
    with pytest.raises(HTTPException):
        engine.set_contact(a, 'https://linkedin.com.evil.invalid/in/leo', True)
    with pytest.raises(HTTPException):
        engine.set_contact(a, 'javascript:alert(1)', True)
    with pytest.raises(HTTPException):
        engine.set_contact(a, '', True)
    engine.set_contact(a, 'https://linkedin.com/in/alpha-person/', False)
    engine.set_contact(b, 'https://www.linkedin.com/in/beta-person/', True)
    engine.match_round(force=True)
    assert engine.status(b)['match']['partner_linkedin'] is None
    assert engine.status(a)['match']['partner_linkedin'] == 'https://www.linkedin.com/in/beta-person'
    assert engine.status(a)['match']['partner_email'] is None
    engine.set_contact(b, None, False)
    assert engine.status(a)['match']['partner_linkedin'] is None
    engine.set_contact(a, 'https://www.linkedin.com/in/alpha-person', True)
    assert engine.status(b)['match']['partner_linkedin'] == 'https://www.linkedin.com/in/alpha-person'
    engine.revoke(a)
    assert engine.status(b)['match'] is None
    with engine.connect() as c:
        assert c.execute('SELECT 1 FROM contact_preferences WHERE user_id=?', (a,)).fetchone() is None


@pytest.mark.asyncio
async def test_contact_endpoint_is_owner_scoped_and_forbids_mcp_changes(tmp_path):
    app = create_app(path=tmp_path / 'web-link.sqlite', quiet_seconds=0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as a, \
               httpx.AsyncClient(transport=transport, base_url='http://testserver') as b:
        await a.post('/api/register', json={'name':'Alpha Person','email':'alpha@demo.test','password':'long-password-test'})
        await b.post('/api/register', json={'name':'Beta Person','email':'beta@demo.test','password':'long-password-test'})
        r = await a.post('/api/contact',json={'linkedin_url':'https://www.linkedin.com/in/alpha-person','share_on_match':True})
        assert r.status_code == 200
        assert (await b.get('/api/me')).json()['contact']['linkedin_url'] is None
        assert (await a.get('/api/me')).json()['contact']['linkedin_url'].endswith('/alpha-person')
        token = (await a.post('/api/tokens')).json()['token']
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver', headers={'Authorization':'Bearer '+token}) as mcp:
            assert (await mcp.post('/api/contact', json={'linkedin_url':None,'share_on_match':False})).status_code == 403
        r = await a.post('/api/contact', json={'linkedin_url':'https://linkedin.com/in/abc','share_on_match':'yes'})
        assert r.status_code == 422
