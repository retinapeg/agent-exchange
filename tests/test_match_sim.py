"""Offline matching simulation: matchers, owner agents, privacy measures and frozen plan."""
import json

import pytest

from exchange import match_sim as ms
from exchange.matchmaking import propose, tag_overlap, panel, SPECIALISTS

A = {'id': 'a', 'interests': ['python', 'physics'], 'goals': ['learn'], 'availability': ['weekend'], 'communication': ['async'], 'timezone': 'UTC'}
B = {'id': 'b', 'interests': ['python'], 'goals': ['learn'], 'availability': ['weekend'], 'communication': ['async'], 'timezone': 'UTC'}
C = {'id': 'c', 'interests': ['rust'], 'goals': ['learn'], 'availability': ['weekend'], 'communication': ['async'], 'timezone': 'UTC'}


class ScriptedPanel:
    def __init__(self, director_p=0.7, wrong_name=False):
        self.director_p, self.wrong_name, self.calls = director_p, wrong_name, []

    def complete(self, operation, payload):
        self.calls.append(operation)
        if operation == 'specialist':
            name = 'Someone else' if self.wrong_name else payload['specialist']
            dissent = 'cannot verify follow-through' if name == "Devil's Advocate" else ''
            return {'specialist': name, 'p': 0.6, 'reason': 'r', 'dissent': dissent}
        return {'p': self.director_p, 'dissent': '', 'reasons': ['overlap']}


def test_tag_overlap_scores_jaccard_and_skips_disjoint_pairs():
    pairs = tag_overlap([A, B, C])
    assert [p['participants'] for p in pairs] == [['a', 'b']]
    assert pairs[0]['score'] == 0.5


def test_propose_keeps_service_bound_but_accepts_explicit_limit():
    many = [{**B, 'id': f'p{i}'} for i in range(41)]
    with pytest.raises(ValueError):
        propose(many)
    assert len(propose(many, limit=200)['proposals']) == 41 * 40 // 2


def test_panel_keeps_specialist_dissent_and_thresholds():
    provider = ScriptedPanel(0.7)
    result = panel({'profiles': [A, B], 'qa': {}}, provider, threshold=0.5)
    assert provider.calls == ['specialist'] * len(SPECIALISTS) + ['director']
    assert result['introduce'] and result['p'] == 0.7
    assert "Devil's Advocate: cannot verify follow-through" in result['dissent']
    assert not panel({'profiles': [A, B], 'qa': {}}, ScriptedPanel(0.3))['introduce']


def test_panel_rejects_impersonated_specialist_and_out_of_range_p():
    with pytest.raises(ValueError):
        panel({'profiles': [A, B], 'qa': {}}, ScriptedPanel(wrong_name=True))
    with pytest.raises(ValueError):
        panel({'profiles': [A, B], 'qa': {}}, ScriptedPanel(1.5))


def test_population_is_seeded_with_unique_canaries():
    first, again = ms.population(7, 50), ms.population(7, 50)
    assert first == again and first != ms.population(8, 50)
    canaries = [v for p in first for v in p['canaries'].values()]
    assert len(set(canaries)) == len(canaries)
    assert all(v in p['raw_context'] for p in first for v in p['canaries'].values())
    assert all(p['hidden']['employer'] in ms.EMPLOYERS for p in first)


def test_owner_profile_is_schema_valid_and_carries_no_private_material():
    provider = ms.FixtureProvider()
    for p in ms.population(3, 40):
        outward = ms.owner_profile(provider, p)
        text = repr(outward)
        assert set(outward) <= ms.FIELDS | {'id'}
        assert not any(v in text for v in p['canaries'].values())
        assert not any(v in text for v in p['hidden'].values())
    assert provider.calls == 40


def test_gate_blocks_raw_context_and_counts_it():
    p = ms.persona(1, 0)
    assert ms.gate('commitment', {'topic': 'commitment', 'value': p['raw_context']}) is None
    assert ms.gate('commitment', {'topic': 'seniority', 'value': 'junior'}) is None
    assert ms.gate('seniority', {'topic': 'seniority', 'value': 'junior'}) == 'junior'

    class Careless(ms.FixtureProvider):
        def answer(self, payload):
            return {'topic': payload['topic'], 'value': payload['persona']['raw_context']}
    stats = {'blocked_answers': 0}
    answers = ms.ask(Careless(), {'id': 'asker'}, p, stats)
    assert stats['blocked_answers'] == 3 and set(answers.values()) == {'declined'}


def test_question_limit_is_enforced():
    class Greedy(ms.FixtureProvider):
        def questions(self, payload):
            return {'topics': list(ms.QUESTIONS)}
    with pytest.raises(ValueError):
        ms.ask(Greedy(), {'id': 'asker'}, ms.persona(1, 0), {'blocked_answers': 0})


def test_labels_depend_only_on_personas_and_seed():
    a, b = ms.population(2, 2)
    assert ms.label(2, a, b) == ms.label(2, b, a)
    assert 0 < ms.hidden_probability(a, b) < 1


def test_run_seed_small_population_measures_every_matcher():
    result = ms.run_seed(4, n=16)
    assert set(result['metrics']) == set(ms.MATCHERS)
    assert result['metrics']['constrained']['constraint_violations'] == 0
    assert all(m['direct_leakage'] == 0 for m in result['metrics'].values())
    assert sum(b[0] for b in result['calibration']) == result['pairs'] == 120
    assert 'raw_context' not in repr(result) and 'MRN-' not in repr(result)


def test_direct_leakage_detector_catches_a_leaky_owner_agent():
    class Leaky(ms.FixtureProvider):
        def profile(self, payload):
            draft = super().profile(payload)
            draft['profile']['interests'] = draft['profile']['interests'] + [payload['persona']['canaries']['mrn']]
            return draft
    result = ms.run_seed(4, Leaky(), n=10)
    assert all(m['direct_leakage'] == 10 for m in result['metrics'].values())


def test_campaign_freezes_plan_and_rejects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, 'DATA', tmp_path)
    monkeypatch.setattr(ms, 'N', 10)
    monkeypatch.setattr(ms, 'HELDOUT_SEEDS', [1000, 1001])
    monkeypatch.setattr(ms, '_ADVERSARIES', {})
    first, plan_digest = ms.campaign()
    assert first['disk_scan_leaks'] == 0 and first['seeds'] == [1000, 1001]
    assert ms.campaign()[0] == first  # reuses immutable seed records
    assert 'precision@k' in ms.table(first, plan_digest[:16])
    folder = tmp_path / 'experiments' / ('match-sim-' + plan_digest[:16])
    record = folder / 'seeds' / '1000.json'
    value = json.loads(record.read_text())
    value['result']['label_rate'] = 0.99
    record.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='checksum'):
        ms.campaign()
    monkeypatch.setattr(ms, 'K', 3)  # a changed constant is a different campaign, never the same one
    assert ms.plan() != json.loads((folder / 'plan.json').read_text())


def test_live_provider_refuses_short_budget_and_stops_at_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, 'DATA', tmp_path)
    with pytest.raises(ValueError, match='needs'):
        ms.live(budget=5, n=3)
    fixture = ms.FixtureProvider()
    def fake(prompt, schema, trace, operation):
        assert trace.startswith('match-sim-')
        return fixture.complete(operation, json.loads(prompt.split('Input JSON:\n', 1)[1]))
    result = ms.live(budget=ms.live_calls_needed(3), n=3, call=fake)
    assert result['calls'] == ms.live_calls_needed(3)
    provider = ms.ClaudeProvider(1, 'x', fake)
    provider.complete('questions', {'peer': {}})
    with pytest.raises(RuntimeError, match='budget'):
        provider.complete('questions', {'peer': {}})
