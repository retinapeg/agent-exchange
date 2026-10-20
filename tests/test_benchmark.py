from exchange.benchmark import run_trial, analyse, uniform, workload
from exchange.buyer import choose
from exchange.verification import verify


def test_reproduction_common_random_numbers_and_feedback():
    rows = run_trial("unreliable-cheap", 1001, "ucb")
    assert rows == run_trial("unreliable-cheap", 1001, "ucb")
    assert rows[0]["decision"]["feedback"] == {}
    assert sum(h["attempts"] for h in rows[5]["decision"]["feedback"].values()) == 5
    for row in rows:
        assert not any("quality" == k or "outage" == k for p in row["decision"]["candidate_set"] for k in p)
        if row.get("artifact"):
            assert verify(row["request"], row["artifact"])["accepted"] == bool(row["verified"])
    assert sum(r["invalid_accepted"] + r["budget_violation"] for r in rows) == 0
    assert all(r["deadline_miss"] == int(r["latency_ms"] > 50) for r in rows)


def test_analysis_denominators_and_paired_differences():
    rows = [r for p in ("random", "cheapest") for s in range(3) for r in run_trial("unreliable-cheap", s, p)]
    result = analyse(rows)
    assert result["raw_rows"] == 144
    for group in result["groups"]:
        assert group["attempted"] == 72
        assert group["verified"] <= group["completed"] <= group["accepted"] <= group["attempted"]
        assert group["completion_rate"] == group["verified"] / 72
    assert len(result["paired_differences"]) == 1


def test_random_probability_and_untrusted_ratings():
    candidates = [{"peer": "a", "price": 0, "rating": 0}, {"peer": "b", "price": 20, "rating": 1000000}]
    assert choose(candidates, "random")[1]["selection_probability"] == .5
    assert choose(candidates, "reliability")[0]["peer"] == "a"
