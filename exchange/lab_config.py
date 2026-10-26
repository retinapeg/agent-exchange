"""Adds the three rendezvous agents to a local config.

Kept out of common.py on purpose: common.py's bytes are part of frozen experiment digests
(selection benchmark and match-sim), so editing it would silently change those plans.
"""
import secrets

from exchange.common import DATA, config, write_json

LAB_AGENTS = ('physics', 'environment', 'mathematics')


def ensure_lab_config():
    # Each agent is its own process with per-receiver credentials; a peer authenticates to
    # another with the receiver's token issued to it. Existing peers and tokens are untouched.
    path = DATA / 'config.json'
    c = config()
    if c.get('lab_version', 0) >= 1:
        return c
    base = c['peers']['registry']['port']
    for offset, name in enumerate(LAB_AGENTS, 7):
        if name in c['peers']:
            continue
        port = base + offset
        principals = ['observer', 'operator', 'test-other', *[a for a in LAB_AGENTS if a != name]]
        c['peers'][name] = {'id': name, 'port': port, 'url': f'http://127.0.0.1:{port}', 'lab_agent': True,
                            'tokens': {p: secrets.token_urlsafe(32) for p in principals}}
    c.setdefault('lab', {'backend': 'claude', 'model': 'claude-sonnet-5-5', 'authentication': 'existing Claude CLI subscription login only'})
    c['lab_version'] = 1
    write_json(path, c)
    path.chmod(0o600)
    return c
