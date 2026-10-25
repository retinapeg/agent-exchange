"""Store-level finalization guards; no model or payment network calls."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from a2a import types as t
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError

from exchange.common import NS
from exchange.tasks import TaskStore, proto


def submitted(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite', 'seller')
    request = proto({'message': {'messageId': 'original', 'role': 'ROLE_USER',
        'parts': [{'data': {'service': 'csv-audit', 'source': 'value\n1\n'}}]}}, t.SendMessageRequest)
    task_id, _ = store.submit(request, 'buyer', 'original', 'trace')
    return store, task_id, request


def snapshot(store, task_id):
    return (store.get(task_id, 'buyer'), store.stream_events(task_id), store.events())


@pytest.mark.parametrize('target', ['TASK_STATE_COMPLETED', 'TASK_STATE_WORKING'])
def test_paused_task_cannot_resume_without_new_input(tmp_path, target):
    store, task_id, request = submitted(tmp_path)
    store.transition(task_id, 'TASK_STATE_WORKING')
    store.transition(task_id, 'TASK_STATE_INPUT_REQUIRED')
    before = snapshot(store, task_id)
    with pytest.raises(InvalidParamsError, match='Invalid task transition'):
        store.transition(task_id, target, **({'artifact': {'stale': True}} if target == 'TASK_STATE_COMPLETED' else {}))
    assert snapshot(store, task_id) == before
    # Only submit() can admit the next input version under a fresh operation key.
    request = proto({'message': {'messageId': 'continuation', 'taskId': task_id,
        'role': 'ROLE_USER', 'parts': [{'data': {
            'service': 'csv-audit', 'source': 'value\n1\n', 'ranges': {}}}]}}, t.SendMessageRequest)
    assert store.submit(request, 'buyer', 'continuation', 'trace') == (task_id, True)
    assert store.transition(task_id, 'TASK_STATE_WORKING')
    assert store.transition(task_id, 'TASK_STATE_COMPLETED', artifact={'current': True})
    body = json.loads(store.get(task_id, 'buyer')['body'])
    assert body['artifacts'][0]['metadata'][NS]['input_version'] == 2


@pytest.mark.parametrize('source,target,kwargs', [
    ('TASK_STATE_SUBMITTED', 'TASK_STATE_COMPLETED', {'artifact': {}}),
    ('TASK_STATE_WORKING', 'TASK_STATE_SUBMITTED', {}),
    ('TASK_STATE_WORKING', 'TASK_STATE_UNSPECIFIED', {}),
    ('TASK_STATE_WORKING', 'invented-state', {}),
    ('TASK_STATE_WORKING', 'TASK_STATE_COMPLETED', {}),
    ('TASK_STATE_WORKING', 'TASK_STATE_FAILED', {'artifact': {}}),
    ('TASK_STATE_WORKING', 'TASK_STATE_WORKING', {'artifact': {}}),
])
def test_invalid_finalization_has_no_durable_effect(tmp_path, source, target, kwargs):
    store, task_id, _ = submitted(tmp_path)
    if source == 'TASK_STATE_WORKING':
        store.transition(task_id, source)
    before = snapshot(store, task_id)
    with pytest.raises(InvalidParamsError):
        store.transition(task_id, target, **kwargs)
    assert snapshot(store, task_id) == before


def test_unknown_task_has_explicit_error(tmp_path):
    store, _, _ = submitted(tmp_path)
    with pytest.raises(TaskNotFoundError):
        store.transition('missing', 'TASK_STATE_COMPLETED', artifact={})


@pytest.mark.parametrize('other', ['TASK_STATE_COMPLETED', 'TASK_STATE_CANCELED', 'TASK_STATE_FAILED'])
def test_competing_results_commit_one_terminal_outcome(tmp_path, other):
    store, task_id, request = submitted(tmp_path)
    store.transition(task_id, 'TASK_STATE_WORKING')
    before_count = len(store.stream_events(task_id))
    barrier = Barrier(2)

    def finalize(item):
        state, artifact = item
        # Independent connections represent two completion/cancellation handlers.
        contender = TaskStore(store.path, 'seller')
        barrier.wait(timeout=5)
        return contender.transition(task_id, state, artifact=artifact)

    contenders = [('TASK_STATE_COMPLETED', {'winner': 'a'}),
                  (other, {'winner': 'b'} if other == 'TASK_STATE_COMPLETED' else None)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finalize, contenders))
    assert sum(outcomes) == 1
    winner = contenders[outcomes.index(True)]
    body = json.loads(store.get(task_id, 'buyer')['body'])
    assert body['status']['state'] == winner[0]
    events = store.stream_events(task_id)[before_count:]
    assert len(events) == (2 if winner[1] is not None else 1)
    if winner[1] is not None:
        assert body['artifacts'][0]['parts'][0]['data'] == winner[1]
    else:
        assert 'artifacts' not in body
    before = snapshot(store, task_id)
    restored = TaskStore(store.path, 'seller')
    restored.recover()
    assert restored.submit(request, 'buyer', 'original', 'trace') == (task_id, False)
    assert not restored.transition(task_id, 'TASK_STATE_COMPLETED', artifact={'late': True})
    assert snapshot(restored, task_id) == before


def test_partial_artifact_write_rolls_back_before_recovery(tmp_path, monkeypatch):
    store, task_id, _ = submitted(tmp_path)
    store.transition(task_id, 'TASK_STATE_WORKING')
    before = snapshot(store, task_id)
    event = store._event

    def fail_after_artifact(*args):
        event(*args)
        if args[-1] == 'artifact.created':
            raise sqlite3.OperationalError('injected failure after artifact event before status')

    monkeypatch.setattr(store, '_event', fail_after_artifact)
    with pytest.raises(sqlite3.OperationalError, match='injected failure'):
        store.transition(task_id, 'TASK_STATE_COMPLETED', artifact={'partial': True})
    assert snapshot(store, task_id) == before
    restored = TaskStore(store.path, 'seller')
    restored.recover()
    assert restored.get(task_id, 'buyer')['state'] == 'TASK_STATE_FAILED'
    assert 'artifacts' not in json.loads(restored.get(task_id, 'buyer')['body'])
    assert not restored.transition(task_id, 'TASK_STATE_COMPLETED', artifact={'late': True})
