"""Offline matching simulation: matchers, owner agents, privacy measures and frozen plan."""
import pytest

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
