"""Offline matching simulation: matchers, owner agents, privacy measures and frozen plan."""
import json

import pytest

from exchange import match_sim as ms
from exchange.matchmaking import coarsen_availability, propose, tag_overlap, panel, hybrid, SPECIALISTS

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
    v3 = ms.v3_table(first, plan_digest[:16])
    assert all(ms.LEVEL_NAMES[level] in v3 for level in ms.LEVELS) and 'default:' in v3
    assert first['v3']['default'] in ms.LEVELS
    assert first['v4']['default'] in ('none', ms.PRIVATE) and 'v4 private overlap' in ms.v4_table(first, plan_digest[:16])
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


def test_availability_levels_coarsen_the_sim_vocabulary():
    tags = ['early-morning', 'weekday-daytime', 'weekday-evening', 'weekend']
    assert coarsen_availability(tags, 'exact') == sorted(tags)
    assert coarsen_availability(['weekday-daytime'], 'day-part') == ['afternoon', 'morning']
    assert coarsen_availability(['weekend'], 'day-part') == ['afternoon', 'evening', 'morning']
    assert coarsen_availability(['early-morning', 'weekday-evening'], 'week-part') == ['weekday']
    assert coarsen_availability(['weekend'], 'week-part') == ['weekend']
    assert coarsen_availability(tags, 'none') is None
    with pytest.raises(ValueError):
        coarsen_availability(tags, 'hourly')


def test_availability_constraint_applies_only_when_both_cards_state_it():
    hidden = [{k: v for k, v in X.items() if k != 'availability'} for X in (A, B)]
    assert [p['participants'] for p in propose(hidden)['proposals']] == [['a', 'b']]
    assert not ms.violation(*hidden)
    clash = {**B, 'availability': ['weekday-evening']}
    assert propose([A, clash])['proposals'] == [] and ms.violation(A, clash)


def test_removed_availability_leaves_cards_and_qa_without_it():
    provider = ms.FixtureProvider()
    people = ms.population(1000, 12)
    for level in ms.LEVELS:
        cards = [ms.owner_profile(provider, p, level) for p in people]
        values = {v for c in cards for v in c.get('availability', [])}
        expected = {'exact': set(ms.AVAILABILITY), 'day-part': {'morning', 'afternoon', 'evening'},
                    'week-part': {'weekday', 'weekend'}, 'none': set()}[level]
        assert values <= expected and (level != 'none' or all('availability' not in c for c in cards))
    result = ms.run_seed(4, n=16, level='none')
    assert result['level'] == 'none' and result['metrics']['hybrid']['constraint_violations'] == 0
    assert result['metrics']['hybrid']['proposals'] > 0


def test_v3_decision_rule_picks_the_finest_level_with_no_detectable_health_signal():
    ci = lambda lo, hi: {'mean': (lo + hi) / 2, 'lower': lo, 'upper': hi}
    leak = {'health': {'auc': ci(0.6, 0.7), 'logloss_gain': ci(0.01, 0.03)}}
    clean = {'health': {'auc': ci(0.45, 0.55), 'logloss_gain': ci(-0.01, 0.01)}}
    half = {'health': {'auc': ci(0.45, 0.55), 'logloss_gain': ci(0.001, 0.01)}}  # AUC passes, gain does not
    assert ms.decide({'exact': leak, 'day-part': half, 'week-part': clean, 'none': clean}) == 'week-part'
    assert ms.decide({'exact': leak, 'day-part': leak, 'week-part': leak, 'none': leak}) == 'none'
    assert ms.decide(dict.fromkeys(ms.LEVELS, clean)) == 'exact'


def test_disclosure_store_applies_the_v3_availability_default(tmp_path):
    from exchange.matchmaking import AVAILABILITY_DEFAULT, FIELDS, PURPOSE, DisclosureStore
    from exchange.verification import verify
    assert AVAILABILITY_DEFAULT == 'none'
    store = DisclosureStore(tmp_path / 'profiles.sqlite')
    created = [store.create({k: v for k, v in A.items() if k != 'id'}, sorted(FIELDS), f'{i}@example.invalid', PURPOSE) for i in 'xy']
    assert all('availability' not in c['disclosure_preview'] for c in created)
    outward = store.outward()
    assert all('availability' not in p for p in outward)
    result = propose(outward)
    assert len(result['proposals']) == 1 and verify({'service': 'match', 'profiles': outward}, result)['accepted']


def test_private_overlap_is_asked_once_per_card_compatible_pair_and_never_shows_slots():
    cards = [{k: v for k, v in X.items() if k != 'availability'} for X in (A, B, C)]
    cards.append({**cards[1], 'id': 'd', 'communication': ['video']})   # fails a card constraint with everyone
    asked = []
    def overlap(x, y):
        asked.append((x, y))
        return (x, y) != ('a', 'c')
    result = propose(cards, private_overlap=overlap)
    assert asked == [('a', 'b')]                       # c shares no interest with a or b; d shares no communication
    assert [p['participants'] for p in result['proposals']] == [['a', 'b']]
    assert result['proposals'][0]['availability'] == [] and result['proposals'][0]['availability_overlap'] is True
    assert propose(cards, private_overlap=lambda x, y: False)['proposals'] == []


def test_overlap_features_and_cross_validated_attacker():
    feats = ms.overlap_features(['a', 'b', 'c', 'z'], {('a', 'b'): True, ('a', 'c'): False, ('b', 'c'): True})
    assert feats[0] == ['overlap_rate=5', 'neighbour_rate=9'] and feats[3] == ['overlap_rate=none']
    import random
    r = random.Random(0)
    sick = [r.random() < 0.3 for _ in range(200)]
    planted = ms.cv_health([[f'x={y}', f'n={r.randint(0, 5)}'] for y in sick], sick, ['test'])
    assert planted['auc'] > 0.95 and planted['logloss_gain'] > 0.3
    constant = ms.cv_health([['x=1'] for _ in sick], sick, ['test'])
    assert constant['auc'] == 0.5      # a prior-only attacker ranks nobody above anyone
    noise = ms.cv_health([[f'n={r.randint(0, 5)}'] for _ in sick], sick, ['test'])
    assert abs(noise['auc'] - 0.5) < 0.12 and noise['logloss_gain'] < 0.02


def test_private_overlap_run_has_no_availability_on_cards_and_no_violations():
    result = ms.run_seed(4, n=24, level=ms.PRIVATE)
    assert 0 < result['overlap_queries'] <= 24 * 23 // 2
    for m in ms.V4_MATCHERS:
        assert result['metrics'][m]['constraint_violations'] == 0 and 'cv_health' in result['metrics'][m]
    assert result['probe'] is not None and result['metrics']['hybrid']['direct_leakage'] == 0


def test_v4_decision_rule_needs_no_detectable_health_signal_and_half_the_precision_back():
    ci = lambda lo, hi: {'mean': (lo + hi) / 2, 'lower': lo, 'upper': hi}
    row = lambda prec, auc: {'precision_at_k': {'mean': prec}, 'health': {'auc': auc}}
    rows = lambda v4_prec, v4_auc: {'hybrid': {'exact': row(0.42, ci(0.6, 0.7)), 'none': row(0.32, ci(0.45, 0.55)), ms.PRIVATE: row(v4_prec, v4_auc)}}
    assert ms.decide_v4(rows(0.40, ci(0.46, 0.54)))['default'] == ms.PRIVATE
    assert ms.decide_v4(rows(0.36, ci(0.46, 0.54)))['default'] == 'none'     # recovers only 40%
    assert ms.decide_v4(rows(0.42, ci(0.52, 0.60)))['default'] == 'none'     # health still detectable
    assert abs(ms.decide_v4(rows(0.37, ci(0.46, 0.54)))['recovered_fraction'] - 0.5) < 1e-9
    assert ms.decide_v4(rows(0.37, ci(0.46, 0.54)))['default'] == ms.PRIVATE  # exactly half counts
