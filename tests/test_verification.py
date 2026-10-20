"""Independent acceptance rules reject forged types and invalid source data."""
import copy

import pytest

from exchange.client import checked_artifact
from exchange.common import NS, canonical, digest
from exchange.verification import verify


REQUIREMENT = {"service": "requirements", "source": "Must: Retain evidence."}
EXTRACTED = {
    "requirements": [{"requirement": "Retain evidence.", "priority": "required",
                      "evidence": "Must: Retain evidence."}],
    "source_lines": 1,
}
CSV_REQUEST = {"service": "csv-audit", "source": "a\n1\n", "ranges": {"a": [0, 5]}}
CSV_ARTIFACT = {
    "rows": 1, "columns": ["a"], "missing": {"a": 0}, "duplicate_rows": 0,
    "invalid_rows": {"a": []},
    "statistics": {"a": {"count": 1, "min": "1", "max": "1", "mean": "1"}},
}


@pytest.mark.parametrize("field", ["rows", "missing", "duplicate_rows", "statistics"])
def test_csv_boolean_counts_are_not_numbers(field):
    wrong = copy.deepcopy(CSV_ARTIFACT)
    if field == "missing":
        wrong[field]["a"] = False
    elif field == "statistics":
        wrong[field]["a"]["count"] = True
    else:
        wrong[field] = bool(wrong[field])
    assert verify(CSV_REQUEST, CSV_ARTIFACT)["accepted"]
    assert not verify(CSV_REQUEST, wrong)["accepted"]


def test_correct_checksum_does_not_validate_a_boolean_count():
    forged = {**EXTRACTED, "source_lines": True}
    task = {
        "status": {"state": "TASK_STATE_COMPLETED"},
        "artifacts": [{"parts": [{"data": forged}], "metadata": {NS: {
            "sha256": digest(forged), "size": len(canonical(forged)),
            "input_sha256": digest(REQUIREMENT),
        }}}],
    }
    assert not checked_artifact(task, REQUIREMENT)["accepted"]
    # The official protobuf Struct round trip legitimately produces doubles.
    assert verify(REQUIREMENT, {**EXTRACTED, "source_lines": 1.0})["accepted"]


def test_verifier_boolean_verdict_is_not_an_integer():
    request = {"service": "verify", "submission": REQUIREMENT, "artifact": EXTRACTED}
    verdict = {"policy": "deterministic-evidence-v1", "accepted": True, "errors": []}
    assert verify(request, verdict)["accepted"]
    assert not verify(request, {**verdict, "accepted": 1})["accepted"]


def test_matching_contact_flag_is_not_an_integer():
    fields = {"interests": ["AI"], "goals": ["build"], "availability": ["weekends"],
              "communication": ["chat"]}
    request = {"service": "match", "profiles": [{"id": "a", **fields}, {"id": "b", **fields}]}
    proposal = {"participants": ["a", "b"], "shared_interests": ["AI"],
                "shared_goals": ["build"], "availability": ["weekends"],
                "communication": ["chat"], "status": "proposal-only", "contact_disclosed": False}
    artifact = {"purpose": "developer-introduction", "proposals": [proposal],
                "identity": "synthetic pseudonymous; not anonymous",
                "consent": "separate explicit consent from both profile owners required"}
    assert verify(request, artifact)["accepted"]
    proposal["contact_disclosed"] = 0
    assert not verify(request, artifact)["accepted"]


@pytest.mark.parametrize("source", ["a\n1\n\n", "a\n\n1\n", "a\r\n\r\n1\r\n\r\n"])
def test_empty_csv_records_are_ignored(source):
    assert verify({**CSV_REQUEST, "source": source}, CSV_ARTIFACT)["accepted"]


def test_empty_cells_and_quoted_newlines_are_preserved():
    request = {"service": "csv-audit", "source": 'a,b\n"hello\nworld",2\n,3\n\n', "ranges": {}}
    artifact = {"rows": 2, "columns": ["a", "b"], "missing": {"a": 1, "b": 0},
                "duplicate_rows": 0, "invalid_rows": {}, "statistics": {}}
    assert verify(request, artifact)["accepted"]


@pytest.mark.parametrize("source,ranges", [
    ("a,a\n1,2\n", {}),
    ("a\n1,2\n", {}),
    ("a,b\n1\n", {}),
    ("\na\n1\n", {}),
    (",".join(str(i) for i in range(41)) + "\n", {}),
    ("a\n" + "1\n" * 5001, {}),
    ("a\n1\n", {"a": [5, 0]}),
    ("a\n1\n", {"a": [0, "NaN"]}),
    ("a\n1\n", {"a": [False, 5]}),
])
def test_invalid_csv_source_cannot_be_verified(source, ranges):
    result = verify({"service": "csv-audit", "source": source, "ranges": ranges}, {})
    assert not result["accepted"]
    assert "verification_input_invalid" in result["errors"]


def test_plausible_forged_duplicate_header_audit_is_rejected():
    request = {"service": "csv-audit", "source": "a,a\n1,2\n", "ranges": {}}
    artifact = {"rows": 1, "columns": ["a", "a"], "missing": {"a": 0},
                "duplicate_rows": 0, "invalid_rows": {}, "statistics": {}}
    assert not verify(request, artifact)["accepted"]
