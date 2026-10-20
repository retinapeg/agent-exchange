import copy
import random
from exchange.common import DATA


def choose(candidates, policy="fixed", seed=0, history=None):
    if not candidates:
        raise ValueError("no eligible provider")
    history = history or {}
    candidates = sorted(candidates, key=lambda p: p["peer"])
    probability = None
    if policy == "random":
        selected = random.Random(seed).choice(candidates)
        probability = 1 / len(candidates)
    elif policy == "cheapest":
        selected = min(candidates, key=lambda p: (p.get("price", 0), p["peer"]))
    elif policy == "fixed":
        selected = min(candidates, key=lambda p: (not p.get("fixed_preference", False), p["peer"]))
    elif policy in ["reliability", "ucb"]:
        import math
        total = sum(v["attempts"] for v in history.values())
        def score(p):
            h = history.get(p["peer"], {"attempts": 0, "verified": 0})
            rate = (h["verified"] + 1) / (h["attempts"] + 2)
            bonus = math.sqrt(2 * math.log(total + 2) / (h["attempts"] + 1)) if policy == "ucb" else 0
            return rate + bonus - p.get("price", 0) * 0.015 - min(p.get("mean_latency_ms", 0), 300000) * 0.000002
        selected = max(candidates, key=score)
    else:
        raise ValueError("unknown policy")
    return selected, {"policy": policy, "version": "v2", "candidate_set": candidates, "selection_probability": probability, "selected": selected["peer"], "feedback": copy.deepcopy(history)}



def make_buyer(c):
    from exchange.coordinator import Coordinator
    return Coordinator(c, DATA).application()
