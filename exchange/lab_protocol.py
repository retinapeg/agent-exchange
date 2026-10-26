"""Shared, deterministic definitions for the three-agent rendezvous lab.

Nothing here performs inference. Trial values come from a seed and reach an agent
only as that agent's own private facts; the scheduler keeps the ground truth.
"""
from __future__ import annotations

import json
import random
import re
from decimal import Decimal

import jsonschema
from a2a import types as t

from exchange.common import NS, ROOT, digest, now, uid
from exchange.tasks import proto

SCHEMA_VERSION = 'agent-exchange.lab-message.v1'
MESSAGE_SCHEMA = json.loads((ROOT / 'integration/lab-message.schema.json').read_text())
MESSAGE_VALIDATOR = jsonschema.Draft202012Validator(MESSAGE_SCHEMA, format_checker=jsonschema.FormatChecker())

AGENTS = {
    'physics': {'letter': 'A', 'label': 'Agent A', 'name': 'Physics',
                'domain': 'Component physics: electrical power and heat dissipated by the device under test.'},
    'environment': {'letter': 'B', 'label': 'Agent B', 'name': 'Environment',
                    'domain': 'Operating environment: conditions of the air around the device under test.'},
    'mathematics': {'letter': 'C', 'label': 'Agent C', 'name': 'Mathematics',
                    'domain': 'Thermal models, formulas and numerical calculation.'},
}
ORDER = tuple(AGENTS)
MODES = {'isolated': 'A · Isolated baseline', 'communication': 'B · Communication enabled',
         'intervention': 'C · Information intervention'}
BRAINS = ('claude', 'fixture', 'fixture-chatty')
INTENTS = ('request', 'inform', 'correction', 'answer')
DECISIONS = ('accept', 'reject', 'uncertain')
# Hard per-run limits. Requests may lower them (tests), never raise them.
LIMITS = {'max_inferences': 12, 'max_deliveries': 12, 'active_seconds': 360, 'absolute_seconds': 3600,
          'messages_per_turn': 2, 'content_chars': 600, 'turns_per_agent': 5, 'evidence_per_message': 6}
TOLERANCE_C = 0.05
# Canonical inputs: which agent privately holds each one, and its unit.
INPUTS = {'heat_load': ('physics', 'W'), 'ambient_temperature': ('environment', '°C'),
          'thermal_resistance': ('mathematics', 'K/W')}
FORMULA = 'T_steady = T_ambient + P × R_th'
TASK = ('Determine the steady-state temperature, in °C, of the electronic component under test. '
        'The information required is split between different agents. The trial succeeds only when every agent '
        'records its own final answer, supported by evidence in its own memory.')
NOTES = {
    'heat_load': 'Steady electrical power dissipated as heat by the component under test.',
    'ambient_temperature': 'Temperature of the ambient air around the component under test.',
    'thermal_resistance': 'Thermal resistance from the component to the ambient air.',
    'steady_state_formula': 'Steady-state temperature of a component dissipating power P through thermal resistance R_th into ambient air at T_ambient.',
}
KEY = re.compile(r'^[a-z][a-z0-9_]{1,47}$')


def number_text(value):
    """Stable text form used in prompts, transcripts and leak checks."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return ('%.6f' % value).rstrip('0').rstrip('.')


def truth(inputs):
    value = Decimal(str(inputs['ambient_temperature'])) + Decimal(str(inputs['heat_load'])) * Decimal(str(inputs['thermal_resistance']))
    return float(round(value, 6))


def _usable(values):
    # Leak detection searches for these numbers in text. Keep them distinct from each
    # other and from the small integers that appear in prompts (budgets, turn numbers).
    texts = [number_text(v) for v in values]
    if len(set(texts)) != len(texts):
        return False
    return not any(float(v).is_integer() and abs(v) <= 12 for v in values)


def trial(kind='fixed', seed=None):
    if kind == 'fixed':
        inputs = {'heat_load': 120, 'ambient_temperature': 21, 'thermal_resistance': 0.18}
        revision = 150
        seed = None
    elif kind == 'random':
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError('random trials need an integer seed')
        rng = random.Random(f'rendezvous-v1:{seed}')
        while True:
            inputs = {'heat_load': round(rng.uniform(40, 250), 1), 'ambient_temperature': round(rng.uniform(-5, 40), 1),
                      'thermal_resistance': round(rng.uniform(0.05, 0.6), 3)}
            revision = round(inputs['heat_load'] * rng.uniform(1.2, 1.6), 1)
            if _usable([*inputs.values(), revision]):
                break
    else:
        raise ValueError('trial kind must be fixed or random')
    return {'kind': kind, 'seed': seed, 'inputs': inputs, 'truth_c': truth(inputs),
            'intervention': {'agent': 'physics', 'key': 'heat_load', 'value': revision, 'unit': 'W',
                             'note': 'Operator revision: re-measured heat load.'}}


def private_facts(agent, inputs):
    facts = [{'key': key, 'value': inputs[key], 'unit': unit, 'note': NOTES[key]}
             for key, (owner, unit) in INPUTS.items() if owner == agent]
    if agent == 'mathematics':
        facts.append({'key': 'steady_state_formula', 'value': FORMULA, 'unit': '', 'note': NOTES['steady_state_formula']})
    return facts


def agent_card(peer):
    meta = AGENTS[peer['id']]
    return proto({'name': peer['id'],
        'description': f"{meta['label']} ({meta['name']}). {meta['domain']} Local development identity; decisions come from its own Claude CLI context or a labelled fixture.",
        'version': '0.1.0', 'supportedInterfaces': [{'url': peer['url'] + '/a2a', 'protocolBinding': 'JSONRPC', 'protocolVersion': '1.0'}],
        'capabilities': {'streaming': False, 'extensions': [{'uri': NS, 'description': 'Optional rendezvous message envelope agent-exchange.lab-message.v1; not part of core A2A', 'required': False}]},
        'defaultInputModes': ['application/json'], 'defaultOutputModes': ['application/json'],
        'securitySchemes': {'peerBearer': {'httpAuthSecurityScheme': {'scheme': 'bearer', 'description': 'Per-receiver local development credential'}}},
        'securityRequirements': [{'schemes': {'peerBearer': {'list': []}}}],
        'skills': [{'id': 'rendezvous', 'name': 'Evidence exchange', 'description': meta['domain'],
                    'tags': ['rendezvous', meta['name'].lower()]}]}, t.AgentCard)


def evidence_digest(item):
    return digest({k: item[k] for k in ('key', 'value', 'unit', 'origin')})


def evidence_item(fact):
    # origin is where the value first entered any homebase; lineage is every hop since.
    item = {'evidence_id': fact['fact_id'], 'key': fact['key'], 'value': fact['value'], 'unit': fact['unit'],
            'origin': {'agent': fact['origin_agent'], 'kind': fact['lineage'][0]['kind'], 'fact_id': fact['origin_fact']},
            'lineage': fact['lineage'][:24]}
    item['digest'] = evidence_digest(item)
    return item


def envelope(*, run_id, sender, recipient, intent, content, evidence, turn_id, call_id, brain, in_reply_to=None):
    value = {'schema_version': SCHEMA_VERSION, 'message_id': uid(), 'run_id': run_id, 'sender': sender, 'recipient': recipient,
             'intent': intent, 'content': content, 'evidence': evidence, 'in_reply_to': in_reply_to, 'created_at': now(),
             'causation': {'turn_id': turn_id, 'call_id': call_id, 'brain': brain}}
    MESSAGE_VALIDATOR.validate(value)
    return value


def value_pattern(value):
    text = re.escape(number_text(value))
    tail = r'0*' if '.' in number_text(value) else r'(?:\.0+)?'
    return re.compile(r'(?<![0-9.])' + text + tail + r'(?![.]?[0-9])')


def mentions(text, value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return isinstance(value, str) and len(value) > 8 and value in text
    return bool(value_pattern(value).search(text))


def turn_schema(agent, allow_messages):
    """Model-facing schema: types and enums only. Size limits are enforced afterwards."""
    ids = {'type': 'array', 'items': {'type': 'string'}}
    properties = {
        'evidence_decisions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['evidence_id', 'decision', 'reason'], 'properties': {
                'evidence_id': {'type': 'string'}, 'decision': {'enum': list(DECISIONS)}, 'reason': {'type': 'string'}}}},
        'derived_facts': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['key', 'value', 'unit', 'depends_on', 'method'], 'properties': {
                'key': {'type': 'string'}, 'value': {'type': 'number'}, 'unit': {'type': 'string'},
                'depends_on': ids, 'method': {'type': 'string'}}}},
        'answer': {'type': 'object', 'additionalProperties': False, 'required': ['status', 'value_celsius', 'depends_on', 'justification'],
            'properties': {'status': {'enum': ['final', 'provisional', 'cannot_answer']}, 'value_celsius': {'type': ['number', 'null']},
                           'depends_on': ids, 'justification': {'type': 'string'}}},
        'note_to_self': {'type': 'string'},
    }
    if allow_messages:
        properties['messages'] = {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['to', 'intent', 'content', 'evidence_fact_ids'], 'properties': {
                'to': {'enum': [a for a in ORDER if a != agent]}, 'intent': {'enum': list(INTENTS)},
                'content': {'type': 'string'}, 'evidence_fact_ids': ids}}}
    return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}
