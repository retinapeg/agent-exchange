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
