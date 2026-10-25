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

# Match simulation v2 (frozen)

Plan `8370cb84903e9e65`, frozen in `EXPERIMENT_PROTOCOL.md` ("match-sim v2") before the scored
run. Same held-out seeds (1000–1009), 200 fictional developers per seed, k = 5, threshold 0.5,
fixture agents, cost $0. Hidden label rate 0.066. Means with normal 95% intervals across seeds.
Raw records: `local_data/experiments/match-sim-8370cb84903e9e65/` (not in git). v2 uses a new
population generator, so its numbers are not directly comparable with v1.

What v2 changed: a `hybrid` matcher (constrained filter, then the panel ranks the survivors);
protected attributes (health, sexuality, religion, politics, ethnicity, address) kept separate
from shareable ones (employer, school, city); optional `employer`/`school` card fields; Q&A
answers limited to quotes of the owner's card; and an adversary that falls back to the
prior when its model does not beat it.

| Matcher | Proposals/seed | Precision@5 | Recall@5 | Precision − constrained | Violations/seed | Direct leak | Calls/proposal |
|---|---:|---|---|---|---:|---:|---:|
| constrained | 785 | 0.394 [0.380, 0.408] | 0.135 [0.130, 0.140] | 0 (baseline) | 0 | 0 | 0.26 |
| panel | 1,876 | 0.406 [0.396, 0.416] | 0.173 [0.166, 0.180] | +0.012 [0.003, 0.021] | 514 | 0 | 138.0 |
| hybrid | 785 | 0.418 [0.403, 0.433] | 0.143 [0.138, 0.148] | +0.023 [0.019, 0.028] | 0 | 0 | 13.3 |

Hybrid meets its target: zero violations, about a tenth of the panel's calls per proposal, and
the best precision@5. It proposes exactly the constrained set, re-ranked by panel p.

## Leakage

- Direct leakage: **0** canaries in outward cards, matcher outputs, Q&A or run-folder files.
- Q&A gate: of 1,241,124 answers, 1,049,568 answered, 154,474 declined (topic not on the card)
  and **37,082 blocked (3.0%)**, matching the fixture's deliberate 3% raw-context paste rate.

Inference advantage (accuracy minus prior-only base rate). The three matchers expose the same
information (Q&A can only quote the card), so their columns are identical, as the protocol predicted.

| Attribute | constrained | panel | hybrid |
|---|---|---|---|
| health (condition vs none) | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| sexuality | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| religion | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| politics | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| ethnicity | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| address (home area) | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| **protected mean** | **0.000 [0.000, 0.000]** | **0.000 [0.000, 0.000]** | **0.000 [0.000, 0.000]** |
| employer (expected, consented) | +0.671 [0.654, 0.688] | +0.671 [0.654, 0.688] | +0.671 [0.654, 0.688] |
| school (expected, consented) | +0.410 [0.394, 0.427] | +0.410 [0.394, 0.427] | +0.410 [0.394, 0.427] |
| city (expected, consented) | +0.607 [0.588, 0.626] | +0.607 [0.588, 0.626] | +0.607 [0.588, 0.626] |

The protected zeros come from how the measure works. For every protected attribute, the
adversary's model did not beat the prior on the validation seed, so it guessed the most common
value, and its advantage is zero by definition. Two checks give the zero its meaning:

- Positive control: an owner agent that writes the health value into its card gives health
  advantage +0.28 (accuracy 1.00 vs base 0.72). The measure does detect a direct leak.
- Limitation: the built-in weak hint (illness shifts availability towards weekday daytime) is
  invisible to this accuracy measure. Section v2.1 adds measures for weak signals.

## Calibration (panel, all pairs pooled)

| p bin | Pairs | Mean p | Label rate |
|---|---:|---:|---:|
| 0.1–0.2 | 21,086 | 0.176 | 0.002 |
| 0.2–0.3 | 43,837 | 0.260 | 0.006 |
| 0.3–0.4 | 60,055 | 0.342 | 0.025 |
| 0.4–0.5 | 55,264 | 0.436 | 0.097 |
| 0.5–0.6 | 16,890 | 0.543 | 0.297 |
| 0.6–0.7 | 1,742 | 0.636 | 0.501 |
| 0.7–0.8 | 110 | 0.726 | 0.582 |
| 0.8–0.9 | 16 | 0.812 | 0.625 |

As in v1, the fixture panel ranks pairs well but is overconfident.

## Erratum

The frozen v2 protocol says the positive control ran on "development seed 5". Seed 5 is an
**unseen** seed: the development seeds are 0–2. The check is unaffected (seed 5 is in neither
the adversary's training data nor the held-out set). The protocol text is left as frozen,
because editing it would change the plan hash.

## Caveats

- The panel lost v1's commitment answers (Q&A now only quotes the card), so its edge over
  constrained shrank from +0.16 to +0.01. Commitment still drives the hidden labels.
- Links between protected attributes and employer, school or city are not modelled, so that
  route for inference is untested.
- Invented population and compatibility model, fixture agents; not real-user outcomes. No live
  run (`--provider claude`) occurred.
