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
