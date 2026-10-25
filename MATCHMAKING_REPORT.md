# Synthetic introduction evaluation

four fictional profiles, six pairs, invented labels; no real user outcomes.

| Policy | Proposals | Invented mutual acceptances | Constraint violations | Withheld-field leakage |
|---|---:|---:|---:|---:|
| tag-overlap | 6 | 2 | 3 | 0 |
| constrained | 3 | 2 | 0 | 0 |

Raw profiles, predeclared labels and metrics: `local_data/receipts/match-evaluation.json`. Per-field preview, purpose checks, owner-token bilateral consent and revocation are tested separately. These invented labels are not real consent, romantic compatibility or real-user outcomes.

<!-- match-sim: hand-written below this line; ./exchange.sh report keeps it -->

# Match simulation v1 (Phase A, frozen)

Plan `d1023bc5d845506e`, frozen in `EXPERIMENT_PROTOCOL.md` ("Match simulation") before the scored
run. Held-out seeds 1000–1009, 200 fictional developers per seed (19,900 pairs each), k = 5, panel
threshold 0.5, fixture agents (no model calls, cost $0). Hidden label rate 0.061. Means with
normal-approximation 95% intervals across the 10 seeds. Raw seed records and analysis:
`local_data/experiments/match-sim-d1023bc5d845506e/` (not in git).

| Matcher | Proposals/seed | Precision@5 | Recall@5 | Precision − tag-overlap | Violations/seed | Direct leak | Calls/proposal |
|---|---:|---|---|---|---:|---:|---:|
| tag-overlap | 9,759 | 0.159 [0.145, 0.173] | 0.068 [0.063, 0.074] | 0 (baseline) | 8,976 | 0 | 0.020 |
| constrained | 783 | 0.380 [0.364, 0.396] | 0.142 [0.138, 0.146] | +0.221 [0.207, 0.234] | 0 | 0 | 0.255 |
| panel | 2,381 | 0.484 [0.468, 0.501] | 0.223 [0.216, 0.230] | +0.325 [0.312, 0.338] | 1,165 | 0 | 108.7 |

The panel ranks best but proposes pairs that break the hard constraints (no shared goal,
availability or communication value), and evaluating every pair costs about 109 would-be model
calls per proposal. Constrained has zero violations at roughly a fifth of the panel's recall gap.

## Leakage

Direct leakage: **0** canaries (MRN, street, £ salary) found in outward profiles, matcher outputs or
any of the 1,194,000 gated Q&A answers, and 0 in the run-folder files. The gate blocked 35,954
answers (3.0%, matching the fixture's deliberate 3% raw-context paste rate).

Inference leakage, adversary accuracy minus majority base rate:

| Matcher | Health | Employer | Borough (independent control) |
|---|---|---|---|
| tag-overlap | −0.009 [−0.016, −0.003] | +0.404 [0.384, 0.424] | −0.049 [−0.059, −0.038] |
| constrained | −0.009 [−0.016, −0.003] | +0.404 [0.384, 0.424] | −0.049 [−0.059, −0.038] |
| panel | +0.043 [0.026, 0.059] | +0.404 [0.382, 0.425] | −0.046 [−0.059, −0.033] |

- Employer is highly guessable from shared interests in every matcher: legitimately shared fields
  are enough to infer it.
- Health leaks slightly only through the panel, via Q&A answers (commitment, fixed schedule)
  that correlate with the condition. The two profile-only matchers show none.

## Calibration (panel, pooled pairs)

| p bin | Pairs | Mean p | Label rate |
|---|---:|---:|---:|
| 0.1–0.2 | 8,643 | 0.165 | 0.000 |
| 0.2–0.3 | 44,619 | 0.257 | 0.002 |
| 0.3–0.4 | 68,408 | 0.350 | 0.014 |
| 0.4–0.5 | 53,520 | 0.443 | 0.072 |
| 0.5–0.6 | 20,887 | 0.536 | 0.267 |
| 0.6–0.7 | 2,756 | 0.631 | 0.570 |
| 0.7–0.8 | 161 | 0.735 | 0.708 |
| 0.8–0.9 | 6 | 0.833 | 0.833 |

The fixture panel's p ranks well but is overconfident below 0.6: pairs scored 0.3–0.5 are
labelled good far less often than p says. tag-overlap and constrained give no probability.

## Caveats

- **The borough control is −0.05, not about 0.** The adversary does worse than always guessing the
  most common borough: its naive Bayes model, trained on 600 development personas, overfits noise.
  So the measure is biased downward by roughly 0.05, and small positive values (health +0.04 for
  the panel) likely understate the true leak.
- Invented population, invented compatibility model, fixture agents. This shows whether the
  matchers and privacy boundary behave as designed under those assumptions, not real-user outcomes.
- The fixture panel's specialists are unvalidated heuristics; a live model would behave differently.
- Calls are would-be model calls counted in fixture mode; no live run (`--provider claude`) occurred.
- tag-overlap and constrained see identical information, so their inference numbers coincide.
