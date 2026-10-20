"""Headline regeneration must reject evidence whose acceptance has changed."""
import copy

import pytest

from exchange.common import NS, canonical, digest
from exchange.reports import revalidate_evidence


def evidence():
    request = {"service": "requirements", "source": "Must: Keep evidence."}
    artifact = {"requirements": [{"requirement": "Keep evidence.", "priority": "required",
                                  "evidence": "Must: Keep evidence."}], "source_lines": 1}
    verdict = {"policy": "deterministic-evidence-v1", "accepted": True, "errors": []}
    rows = [{"request": request, "artifact": artifact, "verifier": verdict, "verified": 1}]
    task = {"status": {"state": "TASK_STATE_COMPLETED"},
            "history": [{"parts": [{"data": request}]}],
            "artifacts": [{"parts": [{"data": artifact}], "metadata": {NS: {
                "sha256": digest(artifact), "size": len(canonical(artifact)), "input_sha256": digest(request),
            }}}]}
    return rows, {"pilot": {"results": [{"task": task, "verifier": verdict}], "finished": 1, "verified": 1}}


def test_revalidation_preserves_raw_evidence_and_counts_without_inference():
    rows, pilots = evidence()
    before = copy.deepcopy((rows, pilots))
    result = revalidate_evidence(rows, pilots)
    assert (rows, pilots) == before
    assert result['offline_artifacts_checked'] == 1
    assert result['live']['pilot'] == {'checked': 1, 'verified': 1}
    assert result['changed_acceptance_verdicts'] == result['new_model_calls'] == 0


def test_revalidation_refuses_previously_accepted_boolean_count():
    rows, pilots = evidence()
    rows[0]['artifact']['source_lines'] = True
    with pytest.raises(ValueError, match='experiment verdict changed'):
        revalidate_evidence(rows, pilots)


def test_revalidation_refuses_damaged_live_artifact_or_wrong_summary():
    rows, pilots = evidence()
    pilots['pilot']['results'][0]['task']['artifacts'][0]['metadata'][NS]['sha256'] = 'forged'
    with pytest.raises(ValueError, match='live verdict changed'):
        revalidate_evidence(rows, pilots)
    rows, pilots = evidence()
    pilots['pilot']['verified'] = 0
    with pytest.raises(ValueError, match='summary disagrees'):
        revalidate_evidence(rows, pilots)
