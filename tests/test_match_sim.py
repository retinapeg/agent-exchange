"""Offline matching simulation: matchers, owner agents, privacy measures and frozen plan."""
import json

import pytest

from exchange import match_sim as ms
from exchange.matchmaking import propose, tag_overlap, panel, hybrid, SPECIALISTS

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


def test_hybrid_scores_only_constrained_survivors_and_ranks_by_p():
    provider = ScriptedPanel(0.7)
    off = {**A, 'id': 'off', 'goals': ['cofound']}  # shares interests but no goal: filtered out
    ranked = hybrid([A, B, off], provider, lambda a, b: {'profiles': [a, b], 'qa': {}}, limit=10)
    assert [r['participants'] for r in ranked] == [['a', 'b']]
    assert provider.calls == ['specialist'] * len(SPECIALISTS) + ['director']
    assert ranked[0]['p'] == 0.7 and ranked[0]['status'] == 'proposal-only'


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
    assert all(set(p['protected']) == set(ms.PROTECTED) and set(p['shareable']) == set(ms.SHAREABLE) for p in first)
    assert {ms.targets(p)['health'] for p in first} <= {'none', 'condition'}


def test_profile_schema_forbids_protected_fields_and_previews_optional_ones(tmp_path):
    from exchange.matchmaking import DisclosureStore, Profile, PURPOSE, PROTECTED
    base = dict(A, employer='Quantafy', school='UCL')
    base.pop('id')
    for field in PROTECTED:
        with pytest.raises(ValueError):
            Profile.model_validate({**base, field: 'x'})
    store = DisclosureStore(tmp_path / 'profiles.sqlite')
    shared = store.create(base, ['interests', 'employer'], 'a@example.invalid', PURPOSE)['disclosure_preview']
    assert shared == {'interests': base['interests'], 'employer': 'Quantafy'}
    assert 'school' not in store.outward()[0]


def test_owner_profile_carries_no_protected_material_and_respects_consent():
    provider = ms.FixtureProvider()
    shared_employer = 0
    for p in ms.population(3, 60):
        outward = ms.owner_profile(provider, p)
        text = repr(outward)
        assert set(outward) <= ms.FIELDS | {'id'}
        assert not any(v in text for v in p['canaries'].values())
        assert not any(f"'{v}'" in text for k, v in p['protected'].items())
        shared_employer += 'employer' in outward
    assert provider.calls == 60 and 0 < shared_employer < 60


def test_gate_only_passes_quotes_of_the_owner_card():
    p = ms.persona(1, 0)
    card = {'id': p['id'], 'goals': ['learn', 'mentor'], 'employer': 'Quantafy'}
    assert ms.gate('goals', {'topic': 'goals', 'value': 'mentor'}, card) == ('answered', 'mentor')
    assert ms.gate('employer', {'topic': 'employer', 'value': 'Quantafy'}, card) == ('answered', 'Quantafy')
    assert ms.gate('goals', {'topic': 'goals', 'value': 'cofound'}, card)[0] == 'blocked'          # not on the card
    assert ms.gate('school', {'topic': 'school', 'value': 'UCL'}, card)[0] == 'blocked'            # true but withheld
    assert ms.gate('school', {'topic': 'school', 'value': 'declined'}, card)[0] == 'declined'
    assert ms.gate('school', {'topic': 'school', 'value': p['raw_context']}, card)[0] == 'blocked'  # free text on a withheld topic
    assert ms.gate('goals', {'topic': 'employer', 'value': 'Quantafy'}, card)[0] == 'blocked'

    class Careless(ms.FixtureProvider):
        def answer(self, payload):
            return {'topic': payload['topic'], 'value': payload['persona']['raw_context']}
    stats = {}
    answers = ms.ask(Careless(), {'id': 'asker'}, p, card, stats)
    assert stats == {'blocked': 3} and set(answers.values()) == {'declined'}


def test_question_limit_and_card_topics_are_enforced():
    class Greedy(ms.FixtureProvider):
        def questions(self, payload):
            return {'topics': list(ms.QUESTIONS)}
    class Prying(ms.FixtureProvider):
        def questions(self, payload):
            return {'topics': ['religion']}
    for provider in (Greedy(), Prying()):
        with pytest.raises(ValueError):
            ms.ask(provider, {'id': 'asker'}, ms.persona(1, 0), {}, {})


def test_labels_depend_only_on_personas_and_seed():
    a, b = ms.population(2, 2)
    assert ms.label(2, a, b) == ms.label(2, b, a)
    assert 0 < ms.hidden_probability(a, b) < 1


def test_run_seed_small_population_measures_every_matcher():
    result = ms.run_seed(4, n=16)
    assert set(result['metrics']) == set(ms.MATCHERS)
    assert result['metrics']['constrained']['constraint_violations'] == 0
    assert result['metrics']['hybrid']['constraint_violations'] == 0
    assert result['metrics']['hybrid']['proposals'] == result['metrics']['constrained']['proposals']
    assert result['metrics']['hybrid']['calls'] < result['metrics']['panel']['calls']
    assert all(m['direct_leakage'] == 0 for m in result['metrics'].values())
    assert sum(b[0] for b in result['calibration']) == result['pairs'] == 120
    assert 'raw_context' not in repr(result) and 'MRN-' not in repr(result)
    assert set(result['gate']) == {'answered', 'declined', 'blocked'}


def test_inference_measure_detects_a_planted_protected_leak(monkeypatch):
    # Positive control: an owner agent that writes the health condition into its card must show up.
    monkeypatch.setattr(ms, 'N', 80)
    monkeypatch.setattr(ms, '_ADVERSARIES', {})
    class LeakyHealth(ms.FixtureProvider):
        def profile(self, payload):
            draft = super().profile(payload)
            draft['profile']['interests'] = draft['profile']['interests'] + [payload['persona']['protected']['health']]
            return draft
    leaky = ms.run_seed(5, LeakyHealth(), n=80)['metrics']['constrained']['inference']
    clean = ms.run_seed(5, n=80)['metrics']['constrained']['inference']
    assert leaky['health']['advantage'] > 0.15
    assert abs(clean['health']['advantage']) < 0.1
    weak = ms.run_seed(5, LeakyHealth(), n=80)['metrics']['constrained']['weak_signal']['health']
    assert weak['logloss_gain'] > 0.2 and weak['auc'] > 0.9   # v2.1 measures see it too


def test_weak_signal_measure_detects_the_daytime_availability_hint():
    # The generator links illness to weekday-daytime availability; accuracy cannot see it, v2.1 should.
    weak = ms.run_seed(5)['metrics']['constrained']['weak_signal']
    assert weak['health']['auc'] > 0.6 and 0 < weak['health']['logloss_gain'] < 0.2
    assert all(abs(weak[a]['logloss_gain']) < 0.02 for a in ('sexuality', 'religion', 'politics', 'ethnicity', 'address'))


def test_auc_and_bootstrap_helpers():
    assert ms.auc([0.9, 0.8, 0.1, 0.2], [True, True, False, False]) == 1.0
    assert ms.auc([0.5, 0.5], [True, False]) == 0.5
    assert ms.auc([0.5], [True]) is None
    first = ms.bootstrap([0.1, 0.2, 0.3, 0.4], 'k')
    assert first == ms.bootstrap([0.1, 0.2, 0.3, 0.4], 'k')       # fixed random seed
    assert first['lower'] <= first['mean'] <= first['upper']
    assert ms.bootstrap([0.2] * 5, 'k')['lower'] == ms.bootstrap([0.2] * 5, 'k')['upper'] == 0.2


def test_direct_leakage_detector_catches_a_leaky_owner_agent():
    class Leaky(ms.FixtureProvider):
        def profile(self, payload):
            draft = super().profile(payload)
            draft['profile']['interests'] = draft['profile']['interests'] + list(payload['persona']['canaries'].values())
            return draft
    result = ms.run_seed(4, Leaky(), n=10)
    assert all(m['direct_leakage'] == 30 for m in result['metrics'].values())  # MRN, street and £ salary


def test_campaign_freezes_plan_and_rejects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, 'DATA', tmp_path)
    monkeypatch.setattr(ms, 'N', 10)
    monkeypatch.setattr(ms, 'HELDOUT_SEEDS', [1000, 1001])
    monkeypatch.setattr(ms, '_ADVERSARIES', {})
    first, plan_digest = ms.campaign()
    assert first['disk_scan_leaks'] == 0 and first['seeds'] == [1000, 1001]
    assert ms.campaign()[0] == first  # reuses immutable seed records
    text = ms.table(first, plan_digest[:16])
    assert 'precision@k' in text and 'v2.1 (a)' in text and 'v2.1 (b)' in text
    assert set(first['precision_differences']) == {'panel - constrained', 'hybrid - constrained', 'hybrid - panel'}
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
    assert 0 < result['calls'] <= ms.live_calls_needed(3)
    provider = ms.ClaudeProvider(1, 'x', fake)
    provider.complete('questions', {'peer': {}})
    with pytest.raises(RuntimeError, match='budget'):
        provider.complete('questions', {'peer': {}})


def test_results_do_not_depend_on_python_hash_seed():
    # Set iteration order changes with PYTHONHASHSEED; cards, consent and adversary choices must not.
    import os
    import subprocess
    import sys
    code = ('import json; from exchange import match_sim as ms; f = ms.FixtureProvider(); '
            'print(json.dumps([ms.owner_profile(f, p) for p in ms.population(1000, 60)]))')
    outputs = {subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True,
                              env={**os.environ, 'PYTHONHASHSEED': h}).stdout for h in ('0', '1', '2', '3')}
    assert len(outputs) == 1
