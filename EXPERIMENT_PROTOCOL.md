# Experiment protocol

Frozen before the held-out run, 2026-10-20. Executable definition: `exchange/benchmark.py`.

- Five synthetic scenarios: expensive-better, cheap-sufficient, all-equivalent,
  unreliable-cheap and nonstationary (quality changes halfway through a trial).
- Five policies: random, cheapest, capability-filtered fixed, reliability heuristic,
  and UCB (upper confidence bound, which gives less-tried providers an exploration bonus).
- Development seeds 0–4, four tasks each; held-out seeds 1000–1029, 24 tasks each.
  Held-out total: 750 policy trials and 18,000 attempted tasks. No model inference here.
- Workload alternates fictional requirement extraction and synthetic CSV audits.
  The independent verifier checks exact evidence/counts/statistics, unchanged from the free path.
- Random outcomes are keyed by scenario, seed, task, provider and dimension. Policies
  share the same potential outcomes, allowing paired comparisons. A new live model call
  is a fresh observation and does not share these synthetic random outcomes.
- The selector receives eligible peers, prices, declared capabilities and past observed
  verification feedback. It receives no hidden quality/outage parameters or oracle labels.
  This is code separation in an offline evaluator, not a sandbox isolation claim.
- Primary denominator: every attempted task, including outages and budget abandonment.
  Completed-task conditional accuracy is separately labelled. Report cost per verified artifact,
  latency, deadline misses (>50 simulated ms), switches, invalid acceptance, repeat charges,
  budget violations and simulated regret.
- Regret compares expected quality minus 0.015 times price with the best feasible action
  at the learner's current remaining budget. This is a synthetic dynamic oracle, not
  real-world regret or a hindsight optimum under a separate oracle budget.
- Uncertainty: means and normal-approximation 95% intervals across 30 seeds, with paired
  differences against random within each scenario. No multiplicity adjustment or claims
  of causal real-provider superiority. Simulation latency is not measured HTTP latency.
- Per-task/run/peer simulation caps: 25/200/150 integer credits. Global bound per replicate
  is 1000 (the tighter run cap dominates). No real payment or real model characteristics.
- Maximum 18,000 held-out attempts and 600 seconds per invocation; checkpoint each
  seed/policy trial with plan and content hashes. Resume validates immutable raw records.

Plans, development data, raw trial artifacts, checksums and regenerated analysis live under
`local_data/experiments/selection-<plan-hash>/`. A source change creates a different plan;
it cannot silently change an existing scored run.

Live pilots: the original frozen v1 has four trials and 0/4 accepted. Validation v2 uses
new IDs after an explicit whitespace/line-count prompt repair, also four trials with at
most 12 CLI calls. Acceptance is unchanged. These are development/validation observations,
not an unbiased estimate over unrelated documents or a comparison between real models.

Overnight showcase v1: two predeclared 21/22-line fictional document tasks, one free fixed
provider and one cheapest simulated paid provider. At most six actual CLI calls (planner,
provider, interpreter per trial), 600-second wall budget, sequential trials, unchanged
deterministic acceptance. The plan was saved before requests. Actual requests, events and
artifacts are retained under `local_data/showcases/v1-live/`. Repeat commands reuse the
original operations and are not counted as fresh inference. This is integration validation,
not a model comparison. The fixture showcase is separately named and never counted as live.

Runtime policy v2 adds declared requirement-price offers and a small measured-latency
penalty to the reliability/UCB score. Offline latency remains simulated; runtime feedback
records actual local task timings. The updated offline source manifest includes the shared
canonical JSON helper used by the verifier, and creates a new campaign without replacing
the original raw trials. Operational selection history is selection-biased.

## Match simulation (Phase A of MATCH_PLAN.md)

Frozen before the held-out run, 2026-10-25. Executable definition: `exchange/match_sim.py`
(constants `N`, `K`, `THRESHOLD`, seeds), with `exchange/matchmaking.py`. The plan digest covers
those files, `exchange/common.py`, `exchange/benchmark.py` and this file; any change creates a
new campaign folder under `local_data/experiments/match-sim-<plan-hash>/`.

- Population: 200 seeded fictional developers per seed. Each private persona has raw context with
  three canaries (`MRN-dddd-XX`, a made-up `<n> <Name> Lane`, an exact `£` salary) and three hidden
  attributes: health, employer, borough. Health and employer are generated to correlate with
  shareable fields (a realistic inference channel); borough is independent (a control).
  Personas are regenerated from the seed and never written to disk.
- Labels: a hidden compatibility model over latent facts (true interests, goals, availability,
  communication, timezone, commitment, seniority) gives p; the label is one keyed Bernoulli draw
  per pair. Some latent facts reach the matchers only through Q&A, some never. Matchers never see
  personas, p or labels. Development label rate is about 6%.
- Owner agents (fixture by default): draft the outward `Profile`, drop some true interests, add
  noise, withhold timezone for some owners; answer at most 3 questions. The Exchange gate passes
  only enumerated profile-level answers; anything else is blocked, replaced by `declined` and
  counted. The fixture agent tries to paste raw context into 3% of answers to exercise the gate.
- Matchers, on the same 19,900 pairs per seed: `tag-overlap` (any shared interest, ranked by
  Jaccard), `constrained` (existing `propose`: shared interests, goals, availability and
  communication), `panel` (Compatibility, Friction, Timing, Devil's Advocate, Director; p with
  dissent; introduce when p >= 0.5). Only the panel reads Q&A. Fixture panel roles are
  unvalidated heuristics over profiles and Q&A.
- Seeds: development 0–2 (tuning, tests, adversary background knowledge); held-out 1000–1009.
- Measures per matcher, per seed, then mean and normal-approximation 95% intervals across the 10
  held-out seeds:
  - precision@5: per person, share of their top-5 proposed partners with a positive label,
    averaged over people with at least one proposal; recall@5: positives retrieved in the top 5
    over all their positives, averaged over people with at least one positive. Paired difference
    in precision@5 versus `tag-overlap` within seed.
  - calibration (panel only; pooled pairs): p in ten 0.1 bins vs observed label rate. The other
    matchers give no probability (n/a).
  - direct leakage: count of scored-persona canaries found by pattern in anything outside the
    owner agents (outward profiles, matcher outputs, every gated Q&A answer), plus a scan of
    every file in the run folder.
  - inference leakage: a naive Bayes adversary trained only on development-seed personas sees
    what one counterpart sees about each person (outward profile, plus that person's Q&A answers
    for the panel) and guesses each hidden attribute. Report accuracy minus the majority-class
    base rate in the scored population. Privacy holds near 0; the borough control should be ~0.
  - constraint violations (proposed pairs lacking a shared goal, availability or communication
    value), proposals per seed, model calls per proposal (fixture calls counted as would-be model
    calls, including all-pairs Q&A and panel calls) and cost per proposal ($0 for fixture).
- Table columns, as printed by `./exchange.sh match-sim`: matcher, proposals/seed, precision@k,
  recall@k, precision minus tag-overlap, violations/seed, direct leak, calls/proposal,
  cost/proposal; then inference advantage for health, employer, borough; then the panel
  calibration table and the gate count.
- Not in this run: stateless vs persistent owner agents; neutral vs pressured incentive.
  `--provider claude --budget N` is a separate unscored live development run on 4 developers
  from seed 0 (82 calls), refused before any call when the budget is lower; it is never mixed
  into the frozen table.

This is an invented population and an invented compatibility model. Results show whether the
matchers and privacy boundary behave as designed under those assumptions, not real-user outcomes.

## match-sim v2

Frozen before the held-out run, 2026-10-25. The v1 section above and its campaign
(`match-sim-d1023bc5d845506e`) are unchanged. Same executable files and digest rule as v1; the
plan's `schema_version` is `leo.match-sim.v2`, so v2 has a different plan hash and folder.

Changes from v1:

- Matchers: `constrained` (baseline for paired differences), `panel`, and `hybrid`: the
  constrained filter runs first, then the panel scores only the surviving pairs; all survivors are
  proposed, ranked by panel p. Hybrid has zero constraint violations by construction and its panel
  calls scale with survivors, not all pairs. `tag-overlap` is not run.
- Two attribute tiers. **Protected** (UK GDPR special category plus address): health, sexuality,
  religion, politics, ethnicity, address (home area; the exact street is a canary). They are never
  outward fields; `Profile` forbids them. **Shareable with consent**: employer, school, city,
  interests. Employer and school are new optional outward fields that appear in the disclosure
  preview only when approved (fixture owners approve employer 60%, school 50%). City is not a
  field but fixes the timezone.
- Generation: health keeps v1's proxy (illness shifts availability towards weekday daytime);
  sexuality, religion, politics, ethnicity and address are independent of everything outward,
  each with a common majority value. Correlations between protected attributes and
  employer, school or city are deliberately not modelled, so that proxy route is untested here.
- Q&A may only quote the owner's outward card: topics are card fields, and the gate passes an
  answer only if it equals a value on that card. Outcomes are counted separately: answered,
  declined (topic not on the card) and blocked (anything else, including free text and true but
  withheld values). The fixture still pastes raw context into 3% of answers.
- Consequence, stated before the run: Q&A adds nothing beyond the card, so all three matchers
  expose the same information and their inference rows will be identical. The panel loses v1's
  commitment and schedule answers; commitment still drives the hidden labels.
- Adversary: naive Bayes per attribute over deduplicated view features, trained on what the
  same owner-agent behaviour produces on development seeds (attacker background knowledge).
  Selection: train on seeds 0–1, validate on seed 2; where naive Bayes does not beat the most common
  development value, it guesses that value instead (a prior-only attacker). Then retrain on
  seeds 0–2. This is a stronger adversary than v1's and removes v1's negative bias (borough −0.05).
- Scoring: health is scored as condition vs none. Base rate is the accuracy of the prior-only
  attacker on the scored population. Inference advantage = accuracy − base rate. **Success
  criterion: the mean protected-attribute advantage is near 0 with its 95% interval reported.**
  Employer, school and city guessability is reported separately as "expected, consented".
- Positive control (sensitivity check, run on development seed 5 before freezing): an owner agent
  that writes the health value into its card gives health advantage +0.28 (accuracy 1.00 vs base
  0.72); the clean agent gives 0.00. A test enforces this. The accuracy measure does not detect
  the weak availability proxy for health: no argmax attacker beats the prior from it. A
  calibrated-probability measure would be needed for weak proxies.
- Table, as printed by `./exchange.sh match-sim`: matcher, proposals/seed, precision@k, recall@k,
  precision minus constrained, violations/seed, direct leak, calls/proposal; protected inference
  per attribute and pooled mean (rows) by matcher (columns); shareable guessability; panel
  calibration over all pairs; gate counts and run-folder canary scan.
- Unchanged from v1: N = 200, k = 5, threshold 0.5, development seeds 0–2, held-out seeds
  1000–1009, canaries, hidden compatibility model, precision/recall/calibration/direct-leak
  definitions, normal 95% intervals across seeds. Canaries now embed the persona index so they
  are unique within a seed. `--provider claude` remains a separate unscored run (at most 160
  calls for 4 developers) and was not run.

Invented population and compatibility model; fixture agents. Not real-user outcomes.

## match-sim v2.1 metrics

Frozen before the held-out rerun, 2026-10-25. Everything in "match-sim v2" stands; this section
only adds measures. The plan's `schema_version` is `leo.match-sim.v2.1`, so it has a new plan
hash and folder; the v1 and v2 campaigns are untouched. Same held-out seeds 1000–1009. The v2
measures are recomputed unchanged and must reproduce the frozen v2 numbers.

- (a) Precision@5 differences for every pair of matchers (panel − constrained, hybrid −
  constrained, hybrid − panel). Paired bootstrap: resample the 10 held-out seeds with
  replacement, 10,000 replicates, fixed random seed; percentile 95% interval of the mean
  per-seed difference. The seed is the resampling unit because people within a seed share pairs.
- (b) Weak-signal leakage for every attribute, per matcher information set:
  - The adversary outputs probabilities: Laplace-smoothed development prior times the naive Bayes
    likelihood raised to a weight w in {1, 1/2, 1/4, 1/8, 1/16, 1/32, 0}. w is chosen per
    attribute by log-loss on development seed 2 after training on seeds 0–1, then the model is
    retrained on seeds 0–2. w = 0 is the prior.
  - Log-loss gain = mean log-loss of the smoothed development prior minus mean log-loss of the
    adversary, in nats per person. 0 means no usable signal; it can be slightly negative from
    noise.
  - AUC for binary attributes (health, condition vs none): the probability a person with a
    condition scores above one without.
  - Intervals: the same seed bootstrap as (a).
- Sanity checks, run on unseen seeds 5–7 before freezing:
  - Planted health in the card (seed 5): log-loss gain +0.59, AUC 1.00. Required: clearly
    positive on both.
  - Built-in daytime-availability hint: health gain +0.015 to +0.051, AUC 0.62 to 0.73. With
    availability removed from the view: gain −0.014 to +0.004, AUC 0.48 to 0.57. So the signal is
    the hint. Required: a small positive value on (b); if absent, the report says so plainly.
  - Independent protected controls (sexuality, religion, ethnicity, address): w = 0, gain 0.
    Politics picks w = 1/4 and shows about ±0.003 noise.
- Table additions to `./exchange.sh match-sim`: an (a) block and a (b) block; shareable attributes
  are marked as expected.

### v2.1 amendment: deterministic consent draws

Added before the scored rerun that the report uses. The fixture owner agent drew consent for its
optional fields by iterating over a Python set, whose order changes between processes. The first
v2.1 run (plan `28a601e1e8192539`) and the v2 run both happened to use the order school, then
employer. The code now fixes that order, so it reproduces both runs in every process; a test
checks this under four hash seeds. No measure or constant changes. Under the fixed code the
sanity checks on unseen seeds 5–7 read: planted health gain +0.59, AUC 1.00; daytime hint gain
+0.020 to +0.044, AUC 0.64 to 0.72 (availability removed: gain −0.014 to +0.004, AUC 0.48 to
0.57); all five independent protected controls choose w = 0 with gain 0. The earlier note that
politics picks w = 1/4 came from the other set order and no longer applies.

## match-sim v3: availability granularity

Frozen before the held-out run, 2026-10-25. Everything in v2 and v2.1 stands. The plan's
`schema_version` is `leo.match-sim.v3` (new plan hash and folder). Same held-out seeds 1000–1009,
same population, owner agents, matchers and adversary design.

- Levels, applied by the Exchange to the approved card (`coarsen_availability` in
  `exchange/matchmaking.py`); the Q&A gate can only quote the coarsened card:
  - L0 `exact`: the current tags (early-morning, weekday-daytime, weekday-evening, weekend).
  - L1 `day-part`: morning / afternoon / evening. Daytime counts as morning and afternoon; a tag
    naming no time of day (weekend) covers all three.
  - L2 `week-part`: weekday vs weekend only.
  - L3 `none`: availability is removed from the card.
- Hard constraint change, needed for L3: shared availability is required only when both cards
  state it. At L0–L2 every card states it, so L0 reproduces v2.1 exactly.
- The hidden compatibility labels still use exact latent availability, so coarser cards can cost
  precision.
- The adversary knows the level: it is retrained per level on development seeds, with the same
  v2.1 weight selection.
- Measures per level, for the hybrid matcher (its information set: card plus gated Q&A):
  - health log-loss gain and AUC (condition vs none);
  - hybrid precision@5 and its paired difference from L0;
  - hybrid Q&A-gate block rate (blocked / all hybrid answers).
  All with the v2.1 seed bootstrap (10,000 replicates, percentile 95% CI).
- Decision rule (pre-registered, computed by `decide` in `match_sim.py`): the default is the
  finest level where the health AUC CI includes 0.5 and the log-loss gain CI includes 0
  (interval ends count as included). If none qualifies except L3, the default is L3. Precision
  does not enter the rule; it is reported as the cost.
- After the run, the chosen default is applied in `exchange/matchmaking.py`. That changes a source
  digest, so the campaign is rerun under the resulting plan hash and must reproduce every number.
- Sanity run on unseen seeds 5–7 before freezing (3 seeds, wide intervals): health gain / AUC
  L0 +0.036 / 0.68, L1 +0.010 / 0.58, L2 +0.004 / 0.57 (gain CI includes 0, AUC CI does not
  include 0.5), L3 −0.006 / 0.52; hybrid precision@5 0.42, 0.31, 0.33, 0.31; gate block rate
  3.0–3.1% at every level; 0 violations. On those seeds the rule picks L3.

## match-sim v4: private overlap

Frozen before the held-out run, 2026-10-25. Final simulation run. Everything in v2–v3 stands. The
plan's `schema_version` is `leo.match-sim.v4` (new plan hash and folder). Same held-out seeds
1000–1009 and population; the campaign reruns every v3 level, and v3 must reproduce.

- Condition `private-overlap` (v4): cards are L3, with no availability. Availability stays with each
  owner's agent. For a candidate pair the Exchange asks one yes/no question, "do our availabilities
  overlap?", answered from both private fields (`propose(..., private_overlap=...)`). The question is
  asked only for pairs that already pass the card constraints (shared interest, goal and
  communication), at most once per pair; constrained and hybrid share the same answers. A "no"
  removes the pair, replacing the card availability constraint. Slots are never shown. The panel
  (not compared here) gets no answers.
- Attacker (for the v4 table, applied the same way to L0, L3 and v4): it sees everything the matcher
  sees. That is the person's card, the gated Q&A for hybrid and, for v4, every overlap answer the
  matcher received, which is the same per-pair budget. From the answers it uses the person's own
  yes-rate and the mean yes-rate of their yes-neighbours (deciles).
  - Model: binary naive Bayes on health (condition vs none).
  - Fitting: nested 5-fold cross-validation on each held-out seed. The inner CV chooses a feature
    family (one field, or all) and a likelihood weight from the v2.1 set by log-loss.
  - Measures: log-loss gain is against each training fold's smoothed prior. AUC ranks the
    out-of-fold evidence term only, so a prior-only attacker scores exactly 0.5.
  - This differs from the v3 adversary (trained on development seeds), so the v4 table's L0 and L3
    health numbers are not the v3 numbers.
- Report, for constrained and hybrid at L0, L3 and v4: health AUC and log-loss gain;
  precision@5 and its paired difference from L0. All use the seed bootstrap (10,000 replicates,
  95% percentile CI).
- Decision rule (pre-registered, `decide_v4`), on the hybrid matcher: v4 becomes the default if its
  health AUC CI includes 0.5 and it recovers at least half of the L3 precision loss:
  mean(v4) − mean(L3) ≥ 0.5 × (mean(L0) − mean(L3)), using point estimates. Otherwise L3 (the v3
  default) stays. Constrained is reported, not decided on.
- Secondary measure, not in the rule: a lying counterpart sets its own private availability to
  weekday-daytime and asks each person once (same one-question budget), with the same CV attacker.
- Applying the default: if v4 wins, stored profiles keep availability private and matching uses the
  yes/no overlap; if L3 stays, the code keeps the v3 default. Either way the campaign is rerun if a
  source digest changes and must reproduce.
- Sanity run on unseen seeds 5–7 before freezing (hybrid):
  - Health AUC: L0 0.69 / 0.59 / 0.76; L3 0.48 / 0.52 / 0.57; v4 0.60 / 0.56 / 0.64. The
    attacker mostly picks the availability family at L0 and the neighbour-rate family at v4.
  - Lying prober AUC: 0.66 / 0.64 / 0.71.
  - v4 hybrid precision@5 equals L0 on all three seeds (0.458, 0.378, 0.423).
  - 0 violations.
