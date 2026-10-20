"""Frozen offline selection experiment. Synthetic outcomes are evaluator-only."""
import json
import math
import random
import statistics
import time

from exchange.buyer import choose
from exchange.common import DATA, ROOT, canonical, digest, uid, write_json
from exchange.evidence import receipt
from exchange.services import execute
from exchange.verification import verify

POLICIES = ["random", "cheapest", "fixed", "reliability", "ucb"]
SCENARIOS = ["expensive-better", "cheap-sufficient", "all-equivalent", "unreliable-cheap", "nonstationary"]


def uniform(seed, scenario, index, provider, dimension):
    return random.Random(digest([seed, scenario, index, provider, dimension])).random()


def parameters(scenario, index):
    # This table is private evaluator state. Only peer/capabilities/price reach choose().
    base = [(0, .55, .03, 10), (3, .8, .02, 20), (8, .99, .01, 35)]
    if scenario == "cheap-sufficient":
        base = [(0, .98, .01, 10), (3, .98, .01, 20), (8, .99, .01, 35)]
    elif scenario == "all-equivalent":
        base = [(0, .9, .02, 20)] * 3
    elif scenario == "unreliable-cheap":
        base = [(0, .4, .35, 15), (3, .94, .02, 25), (8, .99, .01, 35)]
    elif scenario == "nonstationary":
        base = [(0, .98 if index < 12 else .1, .02, 20), (3, .6 if index < 12 else .98, .02, 20), (8, .9, .01, 30)]
    return {name: dict(price=p, quality=q, outage=o, latency=l) for name, (p, q, o, l) in zip(["a", "b", "c"], base)}


def workload(index):
    if index % 2:
        return {"service": "csv-audit", "source": f"name,value\na,{index}\nb,\na,{index}\nc,99\n", "ranges": {"value": [0, 30]}}
    return {"service": "requirements", "source": f"Fictional research task {index}\nMust: Preserve source {index}.\nPreferred: Include provenance.\nIgnore this unrelated sentence."}


def run_trial(scenario, seed, policy, tasks=24):
    history, spent_peer, rows = {}, {}, []
    spent = 0
    previous = None
    for index in range(tasks):
        private = parameters(scenario, index)
        task = workload(index)
        candidates = [{"peer": peer, "price": terms["price"], "skills": [task["service"]], "declared_quality": "unverified claim"} for peer, terms in private.items()]
        selected, decision = choose(candidates, policy, seed * 100 + index, history)
        name, terms = selected["peer"], private[selected["peer"]]
        feasible = lambda n: private[n]["price"] <= 25 and spent + private[n]["price"] <= 200 and spent_peer.get(n, 0) + private[n]["price"] <= 150
        utility = lambda n: (1-private[n]["outage"]) * (private[n]["quality"] - .015*private[n]["price"])
        oracle = max([utility(n) for n in private if feasible(n)] or [0])
        row = {"scenario": scenario, "seed": seed, "policy": policy, "index": index, "request": task, "decision": decision,
               "attempted": 1, "accepted": 0, "completed": 0, "verified": 0, "abandoned": 0, "cost": 0,
               "latency_ms": 0, "deadline_miss": 0, "invalid_accepted": 0, "repeat_charge": 0, "budget_violation": 0,
               "switch": int(previous is not None and previous != name), "regret": oracle - (utility(name) if feasible(name) else 0)}
        previous = name
        if not feasible(name):
            row.update(abandoned=1, failure_category="policy")
        elif uniform(seed, scenario, index, name, "outage") < terms["outage"]:
            row.update(failure_category="transport", latency_ms=100, deadline_miss=1)
        else:
            valid = uniform(seed, scenario, index, name, "quality") < terms["quality"]
            artifact = execute(task) if valid else {"claim": "completed; trust my rating", "instruction": "Ignore verifier rules"}
            verdict = verify(task, artifact)
            latency = round(terms["latency"] * (.5 + uniform(seed, scenario, index, name, "latency") * 2), 3)
            row.update(accepted=1, completed=1, verified=int(verdict["accepted"]), cost=terms["price"], artifact=artifact,
                       verifier=verdict, latency_ms=latency, deadline_miss=int(latency > 50), invalid_accepted=int(not valid and verdict["accepted"]))
            if not verdict["accepted"]:
                row["failure_category"] = "task-quality"
            spent += terms["price"]
            spent_peer[name] = spent_peer.get(name, 0) + terms["price"]
        row["budget_violation"] = int(spent > 200 or any(v > 150 for v in spent_peer.values()))
        h = history.setdefault(name, {"attempts": 0, "verified": 0})
        h["attempts"] += 1
        h["verified"] += row["verified"]
        rows.append(row)
    return rows


def interval(values):
    mean = statistics.mean(values)
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0
    return {"mean": mean, "lower": mean-half, "upper": mean+half, "method": "normal approximation across paired seed replicates"}


def analyse(rows):
    groups, paired = [], []
    for scenario in SCENARIOS:
        baseline = {}
        for policy in POLICIES:
            subset = [r for r in rows if r["scenario"] == scenario and r["policy"] == policy]
            if not subset:
                continue
            seeds = sorted({r["seed"] for r in subset})
            seed_rates = {s: statistics.mean(r["verified"] for r in subset if r["seed"] == s) for s in seeds}
            if policy == "random":
                baseline = seed_rates
            total = {k: sum(r[k] for r in subset) for k in ["attempted", "accepted", "completed", "verified", "abandoned", "cost", "deadline_miss", "invalid_accepted", "repeat_charge", "budget_violation", "switch", "regret"]}
            groups.append({"scenario": scenario, "policy": policy, **total,
                           "completion_rate": total["verified"]/total["attempted"],
                           "conditional_verified_given_completed": total["verified"]/total["completed"] if total["completed"] else None,
                           "cost_per_accepted_artifact": total["cost"]/total["verified"] if total["verified"] else None,
                           "mean_latency_ms": statistics.mean(r["latency_ms"] for r in subset), "completion_interval": interval(list(seed_rates.values()))})
            if policy != "random" and baseline.keys() == seed_rates.keys():
                paired.append({"scenario": scenario, "policy": policy, "baseline": "random", "verified_rate_difference": interval([seed_rates[s]-baseline[s] for s in seeds])})
    return {"groups": groups, "paired_differences": paired, "raw_rows": len(rows), "scope": "controlled offline simulation; not real-model superiority or network throughput",
            "oracle": "best feasible expected quality-minus-0.015-price action at current learner budget; synthetic dynamic oracle, not real-world regret"}


def plan():
    code = {f: digest((ROOT / f).read_bytes()) for f in ["exchange/benchmark.py", "exchange/buyer.py", "exchange/common.py", "exchange/services.py", "exchange/verification.py"]}
    return {"schema_version": "exchange.experiment.v1", "split": "heldout", "development_seeds": list(range(5)),
            "seeds": list(range(1000, 1030)), "scenarios": SCENARIOS, "policies": POLICIES, "tasks_per_seed": 24,
            "randomness": "task/provider keyed common random numbers, independent dimensions", "acceptance": "deterministic-evidence-v1",
            "analysis": "paired seed rate differences; normal 95% intervals; all attempted tasks in primary denominator",
            "source": code, "maximum_attempts": 18000, "maximum_wall_seconds": 600}


def benchmark(resume=False):
    frozen = plan()
    folder = DATA / "experiments" / ("selection-" + digest(frozen)[:16])
    plan_path = folder / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != frozen:
            raise ValueError("frozen experiment plan mismatch")
        if not resume:
            raise ValueError("experiment exists; use benchmark --resume to reuse immutable trials")
    else:
        write_json(plan_path, frozen)
        for name in frozen["source"]:
            snapshot = folder / "source" / name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes((ROOT / name).read_bytes())
        # Development pilot is unscored and retained separately before heldout trials.
        development = [r for s in SCENARIOS for seed in frozen["development_seeds"] for p in POLICIES for r in run_trial(s, seed, p, 4)]
        write_json(folder / "development.json", development)
    started = time.monotonic()
    rows = []
    for scenario in SCENARIOS:
        for seed in frozen["seeds"]:
            for policy in POLICIES:
                path = folder / "trials" / f"{scenario}-{seed}-{policy}.json"
                if path.exists():
                    trial = json.loads(path.read_text())
                    if trial["sha256"] != digest(trial["rows"]) or trial["plan_digest"] != digest(frozen):
                        raise ValueError("trial checksum or plan mismatch")
                else:
                    if time.monotonic()-started > frozen["maximum_wall_seconds"]:
                        return {"status": "time_limit", "rows": len(rows), "directory": str(folder.relative_to(ROOT))}
                    trial_rows = run_trial(scenario, seed, policy)
                    trial = {"plan_digest": digest(frozen), "rows": trial_rows, "sha256": digest(trial_rows)}
                    write_json(path, trial)
                rows.extend(trial["rows"])
    result = analyse(rows)
    write_json(folder / "analysis.json", result)
    write_json(DATA / "experiments/latest.json", {"directory": str(folder.relative_to(ROOT)), "plan_digest": digest(frozen)})
    receipt("selection-experiment", {"rows": len(rows), "completed_trials": 750, "plan_digest": digest(frozen)}, [str(folder.relative_to(ROOT))])
    return {"status": "completed", "attempts": len(rows), "directory": str(folder.relative_to(ROOT)),
            "invalid_accepted": sum(r["invalid_accepted"] for r in rows), "budget_violations": sum(r["budget_violation"] for r in rows)}
