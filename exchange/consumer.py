"""Agent Exchange consumer alpha: consent-first, exclusive human matchmaking.

Independent of the experimental A2A/observer stack. Run with:
    python -m exchange.consumer serve
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from networkx import Graph
from networkx.algorithms.matching import max_weight_matching

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('EXCHANGE_DATA_DIR', str(ROOT.parent / 'local_data')))
SHARE_FIELDS = ('interests', 'goals', 'offers', 'seeks', 'style', 'timezone')
STYLE = ('flexible', 'async', 'structured', 'collaborative', 'exploratory')
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
PII = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+|(?:\+?\d[\d\s()\-]{8,}\d)', re.I)
ALLOWED_TAG = re.compile(r'^[a-z0-9][a-z0-9 +.#/\-]{0,39}$')
COOKIE = 'ae_session'


def now() -> float:
    return time.time()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, maxmem=64 * 1024 * 1024).hex()


def validate_profile(value: Any) -> dict:
    """Strict outward data contract: no raw conversations, biographies or undisclosed fields."""
    if not isinstance(value, dict) or set(value) != set(SHARE_FIELDS):
        raise HTTPException(422, 'Profile must contain only the six defined fields')
    p = {}
    for field in ('interests', 'goals', 'offers', 'seeks'):
        tags = value[field]
        if not isinstance(tags, list) or len(tags) > 8 or any(not isinstance(x, str) for x in tags):
            raise HTTPException(422, f'{field} must be a list of at most eight short tags')
        cleaned = []
        for x in tags:
            tag = ' '.join(x.strip().lower().split())
            if not ALLOWED_TAG.fullmatch(tag) or PII.search(tag):
                raise HTTPException(422, f'{field} contains an invalid or identifying tag')
            if tag not in cleaned:
                cleaned.append(tag)
        p[field] = cleaned
    if not p['interests'] or not p['goals']:
        raise HTTPException(422, 'At least one interest and one goal are required')
    if value['style'] not in STYLE:
        raise HTTPException(422, 'Choose a valid working style')
    tz = value['timezone']
    if not isinstance(tz, str) or len(tz) > 50:
        raise HTTPException(422, 'Invalid timezone')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, 'Use an IANA timezone such as Europe/London') from None
    p['style'], p['timezone'] = value['style'], tz
    return p


def validate_approval(fields: Any) -> list[str]:
    if (not isinstance(fields, list) or not all(isinstance(f, str) for f in fields)
            or len(set(fields)) != len(fields) or not set(fields).issubset(SHARE_FIELDS)
            or not {'interests', 'goals'}.issubset(fields)):
        raise HTTPException(422, 'Interests and goals must be approved; other fields are optional')
    return [f for f in SHARE_FIELDS if f in fields]


def visible(profile: dict, fields: list[str]) -> dict:
    return {f: profile[f] for f in fields}


def similarity(a: list[str], b: list[str]) -> float:
    left, right = set(a), set(b)
    return 2 * len(left & right) / (len(left) + len(right)) if left and right else 0.0


def score_pair(a: dict, b: dict) -> dict:
    """Deterministic, explainable 0..100 heuristic, NOT a calibrated probability."""
    interests = similarity(a['interests'], b['interests'])
    goals = similarity(a['goals'], b['goals'])
    # Both directions count: a can help b AND b can help a.
    complement = (similarity(a.get('offers', []), b.get('seeks', [])) +
                  similarity(b.get('offers', []), a.get('seeks', []))) / 2
    style = (1.0 if a.get('style') and b.get('style') and a['style'] == b['style']
             else 0.6 if a.get('style') and b.get('style') and 'flexible' in (a['style'], b['style'])
             else 0.0)
    tz = 0.0
    if a.get('timezone') and b.get('timezone'):
        instant = datetime.now().astimezone()
        offset_a = instant.astimezone(ZoneInfo(a['timezone'])).utcoffset()
        offset_b = instant.astimezone(ZoneInfo(b['timezone'])).utcoffset()
        hours = abs((offset_a - offset_b).total_seconds()) / 3600
        tz = 1.0 if hours <= 2 else 0.6 if hours <= 5 else 0.0
    points = {'interests': round(25 * interests, 2), 'goals': round(30 * goals, 2),
              'complementary_skills': round(25 * complement, 2),
              'working_style': round(10 * style, 2), 'timezones': round(10 * tz, 2)}
    score = round(sum(points.values()))
    reasons = []
    for label, field in (('Shared interests', 'interests'), ('Shared goals', 'goals')):
        shared = sorted(set(a[field]) & set(b[field]))
        if shared:
            reasons.append(f'{label}: {", ".join(shared[:3])}')
    helped_a = sorted(set(a.get('seeks', [])) & set(b.get('offers', [])))
    helped_b = sorted(set(b.get('seeks', [])) & set(a.get('offers', [])))
    if helped_a or helped_b:
        reasons.append('Complementary skills: ' + ', '.join(sorted(set(helped_a + helped_b))[:4]))
    if style == 1.0:
        reasons.append('Compatible collaboration style')
    if tz >= 0.6:
        reasons.append('Reasonable timezone overlap')
    return {'score': score, 'components': points, 'reasons': reasons[:5],
            'disclaimer': 'Heuristic compatibility score, not a probability or guarantee.'}


class Engine:
    def __init__(self, path: Path, *, threshold: int = 75, min_cohort: int = 15, quiet_seconds: float = 3):
        if not 0 <= threshold <= 100 or not 2 <= min_cohort <= 10000 or quiet_seconds < 0:
            raise ValueError('Invalid match settings')
        self.path = Path(path)
        self.threshold = threshold
        self.min_cohort = min_cohort
        self.quiet_seconds = quiet_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    salt TEXT NOT NULL, password_hash TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS api_tokens (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    profile TEXT NOT NULL, shared TEXT NOT NULL, joined REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    profile TEXT NOT NULL, shared TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS matches (
                    id TEXT PRIMARY KEY, a TEXT NOT NULL REFERENCES users(id),
                    b TEXT NOT NULL REFERENCES users(id), score INTEGER NOT NULL,
                    rationale TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                    accepted_a INTEGER NOT NULL DEFAULT 0, accepted_b INTEGER NOT NULL DEFAULT 0,
                    CHECK(a < b));
                CREATE TABLE IF NOT EXISTS active_members (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    match_id TEXT NOT NULL REFERENCES matches(id));
                CREATE TABLE IF NOT EXISTS declines (
                    a TEXT NOT NULL, b TEXT NOT NULL, PRIMARY KEY(a,b));
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_profiles_joined ON profiles(joined);
            ''')

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=20000')
        return db

    def register(self, name: str, email: str, password: str) -> tuple[str, str]:
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 48 or PII.search(name):
            raise HTTPException(422, 'Use a display name between 2 and 48 characters')
        if not isinstance(email, str) or not EMAIL.fullmatch(email) or len(email) > 254:
            raise HTTPException(422, 'Enter a valid email address')
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise HTTPException(422, 'Password must contain at least 10 characters')
        user, salt = uuid4().hex, secrets.token_bytes(16)
        with self.connect() as db:
            try:
                db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',
                           (user, name.strip(), email.strip().lower(), salt.hex(), password_hash(password, salt), now()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'This email already has an account. Sign in instead.') from None
        return user, self.create_session(user)

    def login(self, email: str, password: str) -> tuple[str, str]:
        if not isinstance(email, str) or not isinstance(password, str):
            raise HTTPException(401, 'Invalid credentials')
        with self.connect() as db:
            row = db.execute('SELECT * FROM users WHERE email=?', (email.strip().lower(),)).fetchone()
        dummy_salt = bytes.fromhex('00' * 16)
        actual_salt = bytes.fromhex(row['salt']) if row else dummy_salt
        checked = password_hash(password[:129], actual_salt)
        if not row or not hmac.compare_digest(checked, row['password_hash']):
            raise HTTPException(401, 'Invalid credentials')
        return row['id'], self.create_session(row['id'])

    def create_session(self, user: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (token_hash(token), user, now() + 30 * 86400))
        return token

    def identity(self, token: str | None, bearer: bool = False) -> str:
        if not token:
            raise HTTPException(401, 'Sign in to continue')
        table = 'api_tokens' if bearer else 'sessions'
        with self.connect() as db:
            row = db.execute(f'SELECT user_id{", expires" if not bearer else ""} FROM {table} WHERE hash=?',
                             (token_hash(token),)).fetchone()
        if not row or (not bearer and row['expires'] < now()):
            raise HTTPException(401, 'Session expired. Sign in again.')
        return row['user_id']

    def logout(self, token: str):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (token_hash(token),))

    def create_token(self, user: str) -> str:
        token = secrets.token_urlsafe(40)
        with self.connect() as db:
            db.execute('INSERT INTO api_tokens VALUES (?,?)', (token_hash(token), user))
        return token

    def revoke_tokens(self, user: str):
        with self.connect() as db:
            db.execute('DELETE FROM api_tokens WHERE user_id=?', (user,))

    def preview(self, profile: Any, fields: Any) -> dict:
        p = validate_profile(profile)
        approved = validate_approval(fields)
        return {'shared': visible(p, approved), 'not_shared': [f for f in SHARE_FIELDS if f not in approved],
                'warning': 'Only these approved profile fields are stored. Do not enter raw chats or sensitive information.'}

    def draft(self, user: str, profile: Any, fields: Any) -> dict:
        result = self.preview(profile, fields)
        with self.connect() as db:
            db.execute('INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET profile=excluded.profile, shared=excluded.shared',
                       (user, json.dumps(validate_profile(profile)), json.dumps(validate_approval(fields))))
        return {**result, 'status': 'pending-owner-approval', 'message': 'Open Agent Exchange in your browser to review and approve this draft.'}

    def submit(self, user: str, profile: Any, fields: Any, consent: bool):
        if consent is not True:
            raise HTTPException(422, 'Explicit human approval is required')
        result = self.preview(profile, fields)
        shared = result['shared']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM active_members WHERE user_id=?', (user,)).fetchone():
                raise HTTPException(409, 'Decline or complete your current match before changing your profile')
            db.execute('INSERT INTO profiles VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET profile=excluded.profile, shared=excluded.shared, joined=excluded.joined',
                       (user, json.dumps(shared), json.dumps(list(shared)), now()))
            db.execute('DELETE FROM drafts WHERE user_id=?', (user,))
            db.execute("INSERT INTO meta VALUES('last_join',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now()),))
        return {'joined': True, 'shared': shared, 'threshold': self.threshold}

    def status(self, user: str) -> dict:
        with self.connect() as db:
            owner = db.execute('SELECT id,name,email FROM users WHERE id=?', (user,)).fetchone()
            if not owner:
                raise HTTPException(401, 'Invalid account')
            profile = db.execute('SELECT profile,shared FROM profiles WHERE user_id=?', (user,)).fetchone()
            draft = db.execute('SELECT profile,shared FROM drafts WHERE user_id=?', (user,)).fetchone()
            waiting = db.execute('''SELECT COUNT(*) FROM profiles p
                                    WHERE NOT EXISTS (SELECT 1 FROM active_members m WHERE m.user_id=p.user_id)''').fetchone()[0]
            membership = db.execute('''SELECT mt.*,u.name as partner_name,u.email as partner_email
                FROM active_members mm JOIN matches mt ON mt.id=mm.match_id
                JOIN users u ON u.id=(CASE WHEN mt.a=? THEN mt.b ELSE mt.a END)
                WHERE mm.user_id=?''', (user, user)).fetchone()
        payload = {'id': owner['id'], 'name': owner['name'], 'email': owner['email'],
                   'joined': profile is not None, 'profile': json.loads(profile['profile']) if profile else None,
                   'draft': json.loads(draft['profile']) if draft else None,
                   'draft_fields': json.loads(draft['shared']) if draft else None,
                   'waiting_count': waiting, 'minimum_cohort': self.min_cohort, 'threshold': self.threshold,
                   'match': None}
        if membership:
            accepted = bool(membership['accepted_a'] and membership['accepted_b'])
            payload['match'] = {'id': membership['id'], 'partner_name': membership['partner_name'],
                                'score': membership['score'], 'explanation': json.loads(membership['rationale']),
                                'state': 'accepted' if accepted else 'pending-mutual-acceptance',
                                'my_accepted': bool(membership['accepted_a'] if user == membership['a'] else membership['accepted_b']),
                                'partner_email': membership['partner_email'] if accepted else None}
        return payload

    def match_round(self, *, force: bool = False) -> dict:
        """Atomic DB write transaction prevents duplicate allocation across concurrent workers."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('''SELECT p.user_id,p.profile,u.name FROM profiles p
                                 JOIN users u ON u.id=p.user_id
                                 WHERE NOT EXISTS(SELECT 1 FROM active_members m WHERE m.user_id=p.user_id)
                                 ORDER BY p.joined,p.user_id''').fetchall()
            if len(rows) < 2:
                return {'participants': len(rows), 'created': 0, 'reason': 'insufficient-participants'}
            total = db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]
            if total < self.min_cohort:
                return {'participants': len(rows), 'created': 0, 'reason': 'awaiting-cohort'}
            last = db.execute("SELECT value FROM meta WHERE key='last_join'").fetchone()
            if not force and last and now() - float(last['value']) < self.quiet_seconds:
                return {'participants': len(rows), 'created': 0, 'reason': 'collecting-participants'}
            decline_set = {(r['a'], r['b']) for r in db.execute('SELECT * FROM declines')}
            profiles = {r['user_id']: json.loads(r['profile']) for r in rows}
            ids = sorted(profiles)
            graph = Graph()
            graph.add_nodes_from(ids)
            rationale = {}
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    if (a, b) in decline_set:
                        continue
                    # Fields withheld by either owner contribute no points.
                    s = score_pair(profiles[a], profiles[b])
                    if s['score'] >= self.threshold:
                        graph.add_edge(a, b, weight=s['score'])
                        rationale[a, b] = s
            pairs = max_weight_matching(graph, maxcardinality=True, weight='weight')
            for unordered in pairs:
                a, b = sorted(unordered)
                match_id = uuid4().hex
                score = rationale[a, b]
                db.execute('INSERT INTO matches(id,a,b,score,rationale,state,created) VALUES (?,?,?,?,?,?,?)',
                           (match_id, a, b, score['score'], json.dumps(score), 'proposed', now()))
                db.executemany('INSERT INTO active_members VALUES (?,?)', ((a, match_id), (b, match_id)))
            return {'participants': len(rows), 'created': len(pairs),
                    'unmatched': len(rows) - 2 * len(pairs), 'threshold': self.threshold}

    def decide(self, user: str, decision: str) -> dict:
        if decision not in ('accept', 'decline'):
            raise HTTPException(422, 'Choose accept or decline')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT mt.* FROM active_members mm JOIN matches mt ON mt.id=mm.match_id
                                WHERE mm.user_id=?''', (user,)).fetchone()
            if not row:
                raise HTTPException(404, 'No current match')
            if decision == 'decline':
                db.execute('INSERT OR IGNORE INTO declines VALUES (?,?)', (row['a'], row['b']))
                db.execute('DELETE FROM active_members WHERE match_id=?', (row['id'],))
                db.execute("UPDATE matches SET state='declined' WHERE id=?", (row['id'],))
                db.execute("INSERT INTO meta VALUES('last_join',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now()),))
                return {'state': 'declined', 'requeued': True}
            field = 'accepted_a' if user == row['a'] else 'accepted_b'
            db.execute(f'UPDATE matches SET {field}=1 WHERE id=?', (row['id'],))
            accepted = bool(row['accepted_b'] if user == row['a'] else row['accepted_a'])
            if accepted:
                db.execute("UPDATE matches SET state='accepted' WHERE id=?", (row['id'],))
            return {'state': 'accepted' if accepted else 'waiting-for-partner', 'contact_shared': accepted}

    def revoke(self, user: str):
        """Erase the owner's profile, tokens and sign-in data; free their partner to rematch."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT match_id FROM active_members WHERE user_id=?', (user,)).fetchone()
            if row:
                db.execute('DELETE FROM active_members WHERE match_id=?', (row['match_id'],))
                db.execute("UPDATE matches SET state='revoked',rationale='{}' WHERE id=?", (row['match_id'],))
            # Matches from a deleted account retain only anonymous internal IDs and no rationale.
            db.execute("UPDATE matches SET rationale='{}' WHERE a=? OR b=?", (user, user))
            db.execute('DELETE FROM declines WHERE a=? OR b=?', (user, user))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user,))
            db.execute('DELETE FROM api_tokens WHERE user_id=?', (user,))
            db.execute('DELETE FROM drafts WHERE user_id=?', (user,))
            db.execute('DELETE FROM profiles WHERE user_id=?', (user,))
            # Legacy matches retain anonymized IDs for integrity; user contact/name are erased.
            db.execute("UPDATE users SET name='Deleted participant', email=?, salt='', password_hash='' WHERE id=?",
                       ('deleted-' + user + '@example.invalid', user))
            db.execute("INSERT INTO meta VALUES('last_join',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now()),))
        return {'deleted': True, 'warning': 'Previously shared information cannot be recalled from another participant.'}

    def demo_overview(self) -> dict:
        with self.connect() as db:
            profiles = [dict(r) for r in db.execute('SELECT u.name,p.user_id FROM profiles p JOIN users u ON u.id=p.user_id ORDER BY u.name')]
            matches = [dict(r) for r in db.execute('''SELECT a.name AS first,b.name AS second,m.score,m.state
                FROM matches m JOIN users a ON a.id=m.a JOIN users b ON b.id=m.b
                WHERE m.state IN ('proposed','accepted') ORDER BY m.score DESC''')]
        return {'synthetic_only': True, 'participants': profiles, 'matches': matches, 'minimum_cohort': self.min_cohort,
                'threshold': self.threshold}


async def body(request: Request) -> dict:
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'Use application/json')
    try:
        value = await request.json()
    except ValueError:
        raise HTTPException(400, 'Invalid JSON') from None
    if not isinstance(value, dict):
        raise HTTPException(422, 'Expected a JSON object')
    return value


def create_app(*, path: str | Path | None = None, threshold: int | None = None,
               min_cohort: int | None = None, quiet_seconds: float | None = None,
               demo: bool | None = None) -> FastAPI:
    db_path = Path(path) if path else DATA / ('consumer_demo.sqlite' if os.getenv('EXCHANGE_DEMO') == '1' else 'consumer.sqlite')
    engine = Engine(db_path, threshold=int(threshold if threshold is not None else os.getenv('EXCHANGE_MATCH_THRESHOLD', '75')),
                    min_cohort=int(min_cohort if min_cohort is not None else os.getenv('EXCHANGE_MIN_COHORT', '15')),
                    quiet_seconds=float(quiet_seconds if quiet_seconds is not None else os.getenv('EXCHANGE_QUIET_SECONDS', '3')))
    demo = (os.getenv('EXCHANGE_DEMO') == '1') if demo is None else demo
    public_origin = os.getenv('EXCHANGE_PUBLIC_ORIGIN', '').rstrip('/')
    secure_cookies = os.getenv('EXCHANGE_SECURE_COOKIES', '0') == '1'

    @asynccontextmanager
    async def lifespan(app):
        async def loop():
            while True:
                await asyncio.sleep(2)
                try:
                    await asyncio.to_thread(engine.match_round)
                except Exception:
                    import logging
                    logging.getLogger('agent_exchange').exception('Match loop failed')
        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title='Agent Exchange consumer', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.engine = engine

    @app.middleware('http')
    async def security_headers(request, call_next):
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('origin')
            expected = public_origin or str(request.base_url).rstrip('/')
            if origin and origin != expected:
                return JSONResponse({'detail': 'Origin not allowed'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    def owner(request: Request) -> str:
        auth = request.headers.get('authorization', '')
        if auth.startswith('Bearer '):
            return engine.identity(auth[7:].strip(), bearer=True)
        return engine.identity(request.cookies.get(COOKIE))

    def session_response(value: dict, token: str):
        response = JSONResponse(value)
        response.set_cookie(COOKIE, token, max_age=30*86400, httponly=True, secure=secure_cookies,
                            samesite='strict', path='/')
        return response

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'static' / 'consumer.html')

    @app.get('/consumer.css')
    def css():
        return FileResponse(ROOT / 'static' / 'consumer.css')

    @app.get('/consumer.js')
    def js():
        return FileResponse(ROOT / 'static' / 'consumer.js')

    @app.get('/api/public')
    def public():
        with engine.connect() as db:
            total = db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]
        return {'participants': total, 'minimum_cohort': engine.min_cohort,
                'threshold': engine.threshold, 'demo': demo}

    @app.post('/api/register')
    async def register(request: Request):
        data = await body(request)
        user, token = engine.register(data.get('name'), data.get('email'), data.get('password'))
        return session_response({'id': user, 'registered': True}, token)

    @app.post('/api/login')
    async def login(request: Request):
        data = await body(request)
        user, token = engine.login(data.get('email'), data.get('password'))
        return session_response({'id': user, 'logged_in': True}, token)

    @app.post('/api/logout')
    def logout(request: Request):
        token = request.cookies.get(COOKIE)
        if token:
            engine.logout(token)
        response = JSONResponse({'logged_out': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.get('/api/schema')
    def schema():
        return {'purpose': 'human collaboration matching', 'fields': list(SHARE_FIELDS),
                'required': ['interests', 'goals'], 'style_options': STYLE,
                'max_tags_per_field': 8, 'threshold': engine.threshold,
                'privacy': 'Share only the selected short profile fields. Raw chats and sensitive personal data are not accepted.'}

    @app.post('/api/preview')
    async def preview(request: Request):
        owner(request)
        data = await body(request)
        return engine.preview(data.get('profile'), data.get('approved_fields'))

    @app.post('/api/drafts')
    async def draft(request: Request):
        user = owner(request)
        data = await body(request)
        return engine.draft(user, data.get('profile'), data.get('approved_fields'))

    @app.post('/api/profile')
    async def profile(request: Request):
        user = owner(request)
        data = await body(request)
        if request.headers.get('authorization', '').startswith('Bearer '):
            raise HTTPException(403, 'MCP may stage drafts only; the participant must approve in the browser')
        return engine.submit(user, data.get('profile'), data.get('approved_fields'), data.get('consent'))

    @app.get('/api/me')
    def me(request: Request):
        user = owner(request)
        engine.match_round()
        return engine.status(user)

    @app.post('/api/decision')
    async def decision(request: Request):
        user = owner(request)
        data = await body(request)
        if request.headers.get('authorization', '').startswith('Bearer '):
            raise HTTPException(403, 'Match acceptance must be approved in the browser')
        return engine.decide(user, data.get('decision'))

    @app.post('/api/tokens')
    def create_token(request: Request):
        if request.headers.get('authorization', '').startswith('Bearer '):
            raise HTTPException(403, 'Manage integration keys in the browser')
        return {'token': engine.create_token(owner(request)), 'note': 'Copy now: this key is displayed only once.'}

    @app.delete('/api/tokens')
    def revoke_tokens(request: Request):
        engine.revoke_tokens(owner(request))
        return {'revoked': True}

    @app.delete('/api/account')
    def erase(request: Request):
        if request.headers.get('authorization', '').startswith('Bearer '):
            raise HTTPException(403, 'Account deletion requires browser confirmation')
        engine.revoke(owner(request))
        response = JSONResponse({'deleted': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.get('/api/demo/overview')
    def demo_overview():
        if not demo:
            raise HTTPException(404)
        return engine.demo_overview()

    @app.get('/health')
    def health():
        return {'ok': True, 'service': 'consumer', 'demo': demo}

    return app


def seed_demo(engine: Engine):
    """Private, segregated, genuinely persisted synthetic cohort. Never put into real DB."""
    themes = [
        ('agent reliability', 'ship evaluation tools', 'python', 'product design'),
        ('climate technology', 'reduce energy waste', 'data analysis', 'hardware'),
        ('education tools', 'improve learning', 'curriculum', 'mobile development'),
        ('digital health', 'build accessible interfaces', 'accessibility', 'backend'),
        ('creative software', 'launch collaborative projects', 'visual design', 'database'),
        ('open source infrastructure', 'maintain public software', 'security', 'documentation'),
        ('urban mobility', 'improve public transport', 'mapping', 'machine learning'),
        ('science communication', 'explain complex science', 'writing', 'interactive media'),
        ('language technology', 'create multilingual apps', 'linguistics', 'frontend'),
        ('community building', 'organise local events', 'operations', 'web development'),
    ]
    created = []
    for i, (interest, goal, first, second) in enumerate(themes):
        for side in range(2):
            index = i * 2 + side + 1
            name = f'Demo Participant {index:02}'
            email = f'demo{index:02}@example.invalid'
            try:
                user, _ = engine.register(name, email, 'demo-password-not-for-real-use')
            except HTTPException as e:
                if e.status_code != 409:
                    raise
                with engine.connect() as db:
                    user = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()['id']
            profile = {'interests': [interest], 'goals': [goal],
                       'offers': [first if side == 0 else second],
                       'seeks': [second if side == 0 else first],
                       'style': 'collaborative', 'timezone': 'Europe/London'}
            engine.submit(user, profile, list(SHARE_FIELDS), True)
            created.append(user)
    result = engine.match_round(force=True)
    return {'seeded': len(created), **result}


def main():
    parser = argparse.ArgumentParser(description='Agent Exchange consumer app')
    parser.add_argument('command', choices=['serve', 'seed-demo'], nargs='?', default='serve')
    parser.add_argument('--host', default=os.getenv('HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8715')))
    args = parser.parse_args()
    if args.command == 'seed-demo':
        if os.getenv('EXCHANGE_DEMO') != '1':
            raise SystemExit('Set EXCHANGE_DEMO=1 to seed an isolated synthetic-only database.')
        engine = Engine(DATA / 'consumer_demo.sqlite', threshold=int(os.getenv('EXCHANGE_MATCH_THRESHOLD', '75')),
                        min_cohort=int(os.getenv('EXCHANGE_MIN_COHORT', '15')))
        print(json.dumps(seed_demo(engine), indent=2))
        return
    import uvicorn
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level='info', proxy_headers=True,
                forwarded_allow_ips=os.getenv('EXCHANGE_TRUSTED_PROXY_IPS', '127.0.0.1'))


if __name__ == '__main__':
    main()
