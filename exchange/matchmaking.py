"""Synthetic developer introductions with explicit field disclosure and bilateral consent."""
import hmac
import json
import secrets
from itertools import combinations

from fastapi import Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from exchange.common import Database, canonical, digest, uid
from exchange.failures import ExchangeFailure

# Outward fields. employer and school are optional and shared only when the owner approves them.
FIELDS = {'interests', 'goals', 'availability', 'communication', 'timezone', 'employer', 'school'}
OPTIONAL = {'employer', 'school'}
# UK GDPR special-category data plus exact address: never outward fields (Profile forbids extras).
PROTECTED = ('health', 'sexuality', 'religion', 'politics', 'ethnicity', 'address')
PURPOSE = 'developer-introduction'

# Availability granularity (match-sim v3). Exact tags let a counterpart infer health a little
# (daytime availability is a proxy); coarser levels trade matching precision for privacy.
AVAILABILITY_LEVELS = ('exact', 'day-part', 'week-part', 'none')
DAY_PARTS = {'morning': ('morning', 'daytime'), 'afternoon': ('afternoon', 'daytime'), 'evening': ('evening', 'night')}


def coarsen_availability(tags, level):
    """Map availability tags to a granularity level. Returns None at 'none': the field is not shared.

    day-part: morning/afternoon/evening; a tag naming no time of day (e.g. 'weekend') covers all three.
    week-part: 'weekend' for tags that mention it, otherwise 'weekday'."""
    if level == 'exact':
        return sorted(tags)
    if level == 'none':
        return None
    if level == 'week-part':
        return sorted({'weekend' if 'weekend' in t else 'weekday' for t in tags})
    if level == 'day-part':
        parts = set()
        for t in tags:
            parts |= {part for part, words in DAY_PARTS.items() if any(w in t for w in words)} or set(DAY_PARTS)
        return sorted(parts)
    raise ValueError(f'unknown availability level {level!r}')


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    interests: list[str] = Field(max_length=20)
    goals: list[str] = Field(max_length=20)
    availability: list[str] = Field(max_length=20)
    communication: list[str] = Field(max_length=20)
    timezone: str = Field(max_length=50)
    employer: str | None = Field(default=None, max_length=80)
    school: str | None = Field(default=None, max_length=80)


def propose(profiles, limit=40):
    # The A2A service keeps the 40-profile bound; the offline simulation passes a larger limit.
    if not isinstance(profiles, list) or len(profiles) > limit:
        raise ValueError(f'up to {limit} approved outward-facing profiles required')
    ids = set()
    for p in profiles:
        if not isinstance(p, dict) or set(p) - (FIELDS | {'id'}) or not isinstance(p.get('id'), str) or p['id'] in ids:
            raise ValueError('invalid or duplicate outward profile')
        ids.add(p['id'])
        Profile.model_validate({k: p.get(k, None if k in OPTIONAL else '' if k == 'timezone' else []) for k in FIELDS})
    pairs = []
    for a, b in combinations(profiles, 2):
        overlap = sorted(set(a.get('interests', [])) & set(b.get('interests', [])))
        goals = sorted(set(a.get('goals', [])) & set(b.get('goals', [])))
        available = sorted(set(a.get('availability', [])) & set(b.get('availability', [])))
        communication = sorted(set(a.get('communication', [])) & set(b.get('communication', [])))
        # Availability is a hard constraint only when both cards state it (it may be withheld).
        stated = bool(a.get('availability')) and bool(b.get('availability'))
        if overlap and goals and (available or not stated) and communication:
            pairs.append({'participants': sorted([a['id'], b['id']]), 'shared_interests': overlap,
                          'shared_goals': goals, 'availability': available, 'communication': communication,
                          'status': 'proposal-only', 'contact_disclosed': False})
    return {'purpose': PURPOSE, 'proposals': sorted(pairs, key=lambda p: p['participants']), 'identity': 'synthetic pseudonymous; not anonymous',
            'consent': 'separate explicit consent from both profile owners required'}


def tag_overlap(profiles):
    """Baseline: every pair sharing at least one interest, scored by interest Jaccard overlap."""
    pairs = []
    for a, b in combinations(profiles, 2):
        left, right = set(a.get('interests', [])), set(b.get('interests', []))
        if left & right:
            pairs.append({'participants': sorted([a['id'], b['id']]), 'score': len(left & right) / len(left | right),
                          'shared_interests': sorted(left & right)})
    return pairs


# Panel matcher, ported in shape from the agent-match prototype: four independent specialists,
# then a director whose probability is kept alongside every dissent it cannot suppress.
SPECIALISTS = ('Compatibility', 'Friction', 'Timing', "Devil's Advocate")
FOCUS = ('shared interests and goals', 'working style and commitment differences',
         'availability and timezone overlap', 'unsupported collaboration assumptions')


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Vote(_Strict):
    specialist: str
    p: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(max_length=500)
    dissent: str = Field(max_length=1000)


class Synthesis(_Strict):
    p: float = Field(ge=0, le=1, allow_inf_nan=False)
    dissent: str = Field(max_length=2000)
    reasons: list[str] = Field(min_length=1, max_length=8)


def panel(meeting, provider, threshold=0.5):
    """meeting: what both sides may see (outward profiles and gated Q&A). Returns p, dissent and introduce."""
    votes = []
    for specialist, focus in zip(SPECIALISTS, FOCUS, strict=True):
        vote = Vote.model_validate(provider.complete('specialist', {'specialist': specialist, 'focus': focus, 'meeting': meeting}))
        if vote.specialist != specialist:
            raise ValueError('specialist identity mismatch')
        votes.append(vote)
    proposal = Synthesis.model_validate(provider.complete('director', {'meeting': meeting, 'votes': [v.model_dump() for v in votes]}))
    dissent = [f'{v.specialist}: {v.dissent}' for v in votes if v.dissent]
    if proposal.dissent:
        dissent.append(f'Director: {proposal.dissent}')
    return {'p': proposal.p, 'introduce': proposal.p >= threshold, 'reasons': proposal.reasons,
            'dissent': ' | '.join(dissent) or 'No dissent recorded.', 'votes': [v.model_dump() for v in votes]}


def hybrid(profiles, provider, meeting, threshold=0.5, limit=40):
    """Constrained filter first; the panel then scores only the surviving pairs, which are ranked by p.

    Every proposal satisfies the hard constraints by construction, and panel calls scale with the
    survivors rather than with all pairs. meeting(a, b) returns what both sides may see."""
    by_id = {p['id']: p for p in profiles}
    ranked = []
    for survivor in propose(profiles, limit)['proposals']:
        a, b = (by_id[i] for i in survivor['participants'])
        seen = meeting(a, b)
        result = panel(seen, provider, threshold)
        ranked.append({**survivor, 'p': result['p'], 'reasons': result['reasons'], 'dissent': result['dissent'], 'meeting': seen})
    return sorted(ranked, key=lambda r: (-r['p'], r['participants']))


class DisclosureStore(Database):
    def __init__(self, path):
        super().__init__(path)
        with self.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, fields TEXT, approved TEXT, contact TEXT, token_hash TEXT, revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS consents(pair TEXT, profile_id TEXT, approved INTEGER, PRIMARY KEY(pair,profile_id));
            ''')
        path.chmod(0o600)

    def create(self, profile, approved_fields, contact, purpose):
        Profile.model_validate(profile)
        if purpose != PURPOSE or not isinstance(approved_fields, list) or not set(approved_fields) <= FIELDS:
            raise ExchangeFailure('policy', 'invalid disclosure purpose or fields')
        if not isinstance(contact, str) or not contact.endswith('@example.invalid'):
            raise ExchangeFailure('policy', 'synthetic example.invalid contact required')
        identity, token = uid(), secrets.token_urlsafe(32)
        with self.tx() as db:
            db.execute('INSERT INTO profiles VALUES(?,?,?,?,?,0)', (identity, canonical(profile).decode(), canonical(approved_fields).decode(), contact, digest(token.encode())))
        return {'id': identity, 'owner_consent_token': token, 'disclosure_preview': {k: v for k, v in profile.items() if k in approved_fields}, 'purpose': PURPOSE}

    def outward(self, purpose=PURPOSE):
        if purpose != PURPOSE:
            raise ExchangeFailure('policy', 'purpose restriction')
        with self.connect() as db:
            rows = db.execute('SELECT * FROM profiles WHERE revoked=0').fetchall()
        return [{'id': r['id'], **{k: v for k, v in json.loads(r['fields']).items() if k in json.loads(r['approved'])}} for r in rows]

    def consent(self, identity, other, token, approved, purpose=PURPOSE):
        if purpose != PURPOSE or type(approved) is not bool or identity == other:
            raise ExchangeFailure('policy', 'invalid consent')
        pair = canonical(sorted([identity, other])).decode()
        with self.tx() as db:
            rows = db.execute('SELECT * FROM profiles WHERE id IN (?,?) AND revoked=0', (identity, other)).fetchall()
            owner = next((r for r in rows if r['id'] == identity), None)
            if len(rows) != 2 or not owner or not hmac.compare_digest(owner['token_hash'], digest(token.encode())):
                raise HTTPException(403, 'profile-owner authorization required')
            db.execute('INSERT INTO consents VALUES(?,?,?) ON CONFLICT(pair,profile_id) DO UPDATE SET approved=excluded.approved', (pair, identity, int(approved)))
        return {'consent_recorded': approved, 'profile_id': identity}

    def contacts(self, identity, other, token):
        pair = canonical(sorted([identity, other])).decode()
        with self.connect() as db:
            rows = db.execute('SELECT * FROM profiles WHERE id IN (?,?) AND revoked=0', (identity, other)).fetchall()
            owner = next((r for r in rows if r['id'] == identity), None)
            consent = db.execute('SELECT COUNT(*) FROM consents WHERE pair=? AND approved=1', (pair,)).fetchone()[0]
        if len(rows) != 2 or consent != 2 or not owner or not hmac.compare_digest(owner['token_hash'], digest(token.encode())):
            raise HTTPException(403, 'bilateral owner consent required')
        return {'purpose': PURPOSE, 'contacts': {r['id']: r['contact'] for r in rows}}

    def revoke(self, identity, token):
        with self.tx() as db:
            row = db.execute('SELECT token_hash FROM profiles WHERE id=?', (identity,)).fetchone()
            if not row or not hmac.compare_digest(row[0], digest(token.encode())):
                raise HTTPException(403)
            db.execute("UPDATE profiles SET revoked=1,fields='{}',approved='[]',contact='' WHERE id=?", (identity,))
            db.execute('DELETE FROM consents WHERE profile_id=?', (identity,))
        return {'revoked': identity, 'limitation': 'cannot retract copies previously received by another party'}


def add_disclosures(app, path):
    store = DisclosureStore(path)

    def operator(request):
        if request.state.principal != 'operator':
            raise HTTPException(403, 'agents cannot grant human consent')

    @app.post('/disclosures')
    async def create(request: Request):
        operator(request)
        value = await request.json()
        return store.create(value['profile'], value['approved_fields'], value['contact'], value['purpose'])

    @app.get('/disclosures')
    async def outward(request: Request):
        if request.state.principal not in ('operator', 'buyer'):
            raise HTTPException(403)
        return {'profiles': store.outward(), 'purpose': PURPOSE}

    @app.post('/disclosures/{identity}/{action}')
    async def update(identity: str, action: str, request: Request):
        operator(request)
        token = request.headers.get('x-profile-consent', '')
        value = await request.json()
        if action == 'revoke':
            return store.revoke(identity, token)
        if action == 'consent':
            return store.consent(identity, value['other'], token, value['approved'], value['purpose'])
        if action == 'contacts':
            return store.contacts(identity, value['other'], token)
        raise HTTPException(404)
