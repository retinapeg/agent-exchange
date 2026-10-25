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
  constrained in precision@5 shrank from +0.10 (v1) to +0.01. Commitment still drives the hidden labels.
- Links between protected attributes and employer, school or city are not modelled, so that
  route for inference is untested.
- Invented population and compatibility model, fixture agents; not real-user outcomes. No live
  run (`--provider claude`) occurred.

# Match simulation v2.1 metrics

Plan `f9f2a261cef174cd`, frozen in `EXPERIMENT_PROTOCOL.md` ("match-sim v2.1 metrics" and its
amendment) before this run. Same held-out seeds 1000–1009 and the same v2 population; all v2
measures reproduce exactly. Intervals are paired bootstrap 95% CIs: resample the 10 seeds with
replacement, 10,000 replicates. Raw records: `local_data/experiments/match-sim-f9f2a261cef174cd/`.

## (a) Precision@5 differences between matchers

| Comparison | Difference in precision@5 |
|---|---|
| panel − constrained | +0.012 [0.003, 0.021] |
| hybrid − constrained | +0.023 [0.019, 0.028] |
| hybrid − panel | +0.012 [0.002, 0.022] |

All three intervals exclude 0: hybrid ranks best, then panel, then constrained. The gains are
small, about 1 to 2 points of precision@5.

## (b) Weak-signal leakage

Log-loss gain is how much better (in nats per person) the adversary's probabilities predict the
true value than the development prior does: 0 means no usable signal. AUC applies to binary
attributes only (health: condition vs none); 0.5 means no signal. The matcher columns are
identical because all three expose the same information.

| Attribute | Measure | constrained | panel | hybrid |
|---|---|---|---|---|
| health | log-loss gain | **+0.022 [0.011, 0.033]** | +0.022 [0.011, 0.033] | +0.022 [0.010, 0.032] |
| health | AUC | **0.649 [0.617, 0.681]** | 0.649 [0.617, 0.680] | 0.649 [0.617, 0.681] |
| sexuality | log-loss gain | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| religion | log-loss gain | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| politics | log-loss gain | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| ethnicity | log-loss gain | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| address (home area) | log-loss gain | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| employer (expected, consented) | log-loss gain | +1.326 [1.293, 1.358] | +1.326 [1.294, 1.358] | +1.326 [1.294, 1.358] |
| school (expected, consented) | log-loss gain | +0.741 [0.710, 0.775] | +0.741 [0.710, 0.775] | +0.741 [0.710, 0.774] |
| city (expected, consented) | log-loss gain | +1.346 [1.318, 1.375] | +1.346 [1.319, 1.374] | +1.346 [1.318, 1.375] |

(The CLI prints ethnicity as −0.000; the exact value is about 1e-16, rounding error.)

**Health leaks a little, through availability.** The v2 accuracy measure read 0.000, but v2.1
detects the built-in hint: a small positive log-loss gain and AUC about 0.65, both with intervals
clear of no-signal. An adversary that sees someone's card can rank people with a health
condition above those without about 65% of the time, from their weekday-daytime availability.
That is weak but real leakage of special-category data through a field people legitimately share,
and the v2 success criterion (accuracy near base rate) hid it.

The five independent protected attributes show no signal: the adversary chose the prior (w = 0)
for each, so their gain is exactly 0.

## Sanity checks (unseen seeds 5–7, before the freeze)

| Check | Log-loss gain | AUC | Result |
|---|---|---|---|
| Planted health in the card (seed 5) | +0.59 | 1.00 | clearly positive on both |
| Built-in daytime-availability hint | +0.020 to +0.044 | 0.64 to 0.72 | small positive: detected |
| Same, availability removed from the view | −0.014 to +0.004 | 0.48 to 0.57 | gone: the signal is the hint |

## Reproducibility fix

The first v2.1 run (plan `28a601e1e8192539`) exposed a bug. The fixture owner agent drew consent for
employer and school by iterating over a Python set, whose order changes between processes. So a
fresh process could approve different fields (seed 1000: 16,053 or 16,452 declined answers). Both
frozen runs, v2 and the first v2.1, happened to use the same order. The code now fixes that
order, so it reproduces them in every process; a test checks four hash seeds. The rerun under
the fixed code is identical to the first v2.1 run. One pre-freeze note changed: politics no
longer picks w = 1/4 (that came from the other order).

## Caveats

- The weak-signal adversary is naive Bayes with one calibration weight per attribute. A
  stronger model could find more signal, so these are lower bounds on leakage.
- With 10 seeds, bootstrap intervals are approximate; resampling seeds respects that people
  within a seed share pairs, at the cost of few resampling units.
- Proxy links between protected attributes and employer, school or city are not modelled.
- Invented population and compatibility model, fixture agents; not real-user outcomes. No live
  run (`--provider claude`) occurred.

# Match simulation v3: availability granularity

Plan `23daade3c0932ad9`, frozen in `EXPERIMENT_PROTOCOL.md` ("match-sim v3: availability
granularity") before this run. Same held-out seeds 1000–1009 and population. L0 reproduces every
v2.1 number exactly. Each level coarsens the approved card before anyone sees it; the adversary is
retrained per level, so it knows the coarsening. Columns are for the hybrid matcher (card plus gated
Q&A). Intervals are seed bootstrap 95% CIs (10,000 replicates).

## v3 results

| Level | Health log-loss gain | Health AUC | Hybrid precision@5 | vs L0 | Gate block rate | Proposals/seed |
|---|---|---|---|---|---|---|
| L0 exact (v2.1) | **+0.022 [0.011, 0.033]** | **0.649 [0.617, 0.681]** | 0.418 [0.402, 0.432] | — | 3.0% [2.9, 3.1] | 785 |
| L1 day-part | −0.005 [−0.011, 0.002] | **0.546 [0.523, 0.569]** | 0.327 [0.318, 0.337] | −0.091 [−0.103, −0.079] | 3.0% [2.9, 3.1] | 1,559 |
| L2 weekday/weekend | −0.011 [−0.018, −0.004] | **0.526 [0.501, 0.552]** | 0.340 [0.329, 0.349] | −0.078 [−0.093, −0.064] | 3.0% [2.9, 3.1] | 1,450 |
| L3 removed | −0.019 [−0.025, −0.014] | 0.478 [0.457, 0.498] | 0.313 [0.301, 0.323] | −0.105 [−0.121, −0.091] | 3.0% [2.9, 3.1] | 1,810 |

Bold: an interval that excludes no-signal on the leaking side. All levels: 0 constraint
violations, 0 canaries in any output, 0 canaries on disk. For reference, the constrained matcher at
L0 scores 0.394.

## Decision

**Default: L3, availability removed.** No level passed the pre-registered rule, so L3 is the
default through its fallback clause ("if none qualifies except L3, the default is L3"):

- L1 and L2 still show health signal: their AUC intervals sit above 0.5 (L2 only just, from 0.501).
  Week-part still leaks because a person with a condition is more often weekday-only.
- L3 nominally fails too, but on the other side. Its gain interval is below 0 and its AUC interval
  is below 0.5. That is not leakage: health is independent of every remaining card field by
  construction (see the caveats).

The choice does not depend on that two-sided wording. If only leakage counts (gain above 0 or AUC
above 0.5), L1 and L2 still fail on AUC and L3 passes, so the default is still L3.

Applied in `exchange/matchmaking.py`:

- `AVAILABILITY_DEFAULT = 'none'`; `DisclosureStore.create` drops availability before storing, so
  the disclosure preview and outward profiles never contain it.
- `availability` is optional in `Profile`.
- `propose` and the independent verifier (`exchange/verification.py`) require shared availability
  only when both cards state it.
- The simulation still passes each level explicitly. Applying the default changed a source digest;
  the rerun under plan `87a1cc8bc63a9a15` reproduces this table and the L0 detail exactly.

## Cost

Privacy costs precision here. Removing availability lowers hybrid precision@5 by 0.105, to 0.313,
which is below the L0 constrained matcher (0.394). The hidden compatibility model rewards exact
shared availability, and without it the hard constraint stops filtering: hybrid proposals per seed
more than double. L2 keeps the most precision of the coarse levels (0.340) but still leaks
slightly. The gate block rate is 3.0% at every level; it is the fixture's careless-answer rate,
which coarsening does not change. At L3, availability questions are declined instead of answered.

## Caveats

- Everything is fixture agents on an invented population. The health-to-availability link (60% of
  people with a condition pick weekday-daytime) and the precision cost (the hidden model weights
  exact availability) are both made up. Real data could show more or less of either.
- Negative gains at L1–L3 mean the adversary is miscalibrated, not that it learns something. It
  chose likelihood weight 1/2 on development seed 2 at every level; on held-out seeds that weight
  fits noise and loses to the prior. The v2.1 measure assumes this weight selection holds up; at
  coarse levels it does not.
- L3's AUC interval (0.457–0.498) excludes 0.5 although nothing on the card relates to health.
  The intervals cover seed-to-seed variation for one trained adversary, not variation in its
  training, so they are probably too narrow. Treat edges near the null (L2's 0.501, L3's 0.498)
  as inconclusive.
- The rule weighs privacy only. A different rule could accept L2's small residual signal for
  +0.027 precision@5 over L3; that would be a new protocol, not a reading of this one.
- The A2A `match` service still scores whatever profiles a caller sends, availability included;
  the default applies where profiles are stored (`DisclosureStore`).
