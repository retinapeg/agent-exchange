# Rendezvous experiment protocol

Kept separate from `EXPERIMENT_PROTOCOL.md`, which is part of the frozen match-sim plan digest.
## Agent rendezvous v1: three Claude agents

Frozen before the scored live campaign, 2026-10-26. Executable definition: `exchange/lab_protocol.py`,
`exchange/lab_agent.py`, `exchange/lab.py` and `exchange/lab_cli.py`. The plan, its fresh seeds and a digest of
those sources live in `local_data/experiments/rendezvous-v1/plan.json`. A source change refuses to run under the
frozen plan.

- Agents: A Physics holds the heat load, B Environment the ambient temperature, C Mathematics the thermal resistance
  and the formula T = T_ambient + P × R_th. Each agent is its own process, with its own SQLite homebase, A2A card,
  per-receiver credentials, inbox and outbox. Each turn is one Claude CLI call made by that agent's process
  (`claude-sonnet-5-5`, existing subscription login, tools disabled, safe mode, no session persistence, an empty
  temporary working directory, API-key variables removed). The prompt holds only the agent's own memory, notes,
  conversation and delivered evidence.
- Conditions:
  - **A isolated:** one turn each; no messages, and the transport refuses messages for the run.
  - **B communication:** agents exchange messages freely within the limits.
  - **C intervention:** as B, but the run pauses automatically at the end of round one. The operator then injects
    the trial's seeded revision of the heat load into Physics only, and resumes.
- Scheduler:
  - Round-robin turns. Queued messages are delivered before the next turn.
  - An agent gets another turn only when it has new delivered input or an operator notice.
  - Limits: at most 5 turns per agent, 12 turns (= model calls) per run, 12 delivery attempts per run, 360 s active
    time and 3,600 s absolute time.
  - No retries. Failed turns and deliveries are recorded and never repeated.
- Trials: the fixed trial (120 W, 21 °C, 0.18 K/W; truth 42.6 °C; revision 150 W) and two seeded random trials
  drawn at freeze time. Random ranges: P from 40 to 250 W, T_ambient from −5 to 40 °C and R_th from 0.05 to
  0.6 K/W; the revision multiplies P by a factor between 1.2 and 1.6. All three conditions use the same inputs
  within a trial. Order: isolated, communication, intervention.
- Primary outcome: agents whose final answer is within ±0.05 °C of the deterministic ground truth (the revised
  truth in condition C). Ground truth is computed by the scheduler and never sent to an agent.
- Secondary outcomes:
  - all three agents correct
  - delivered messages, model calls and active seconds
  - facts each agent accepted from others
  - unverified claims: a derived value or answer that is not a model quantity (P × R_th, or T) computable from the
    evidence its cited facts trace back to
  - leakage findings: another agent's private value in a prompt or output before it was delivered
  - event audit: every recorded delivery must equal the sender's outbox digest and the recipient's inbox digest
  - whether the revision propagated
- Interpretation: one stochastic run per cell (nine runs) with one model; descriptive only, with no significance
  tests. Failed runs are reported, never re-run. This is not a general claim about agent capability.
- Development runs before the freeze (unscored; `local_data/dev-lab/smoke1`): four live runs (one isolated, two
  communication, one intervention; 22 CLI calls) led to two changes.
  - The task text now says every agent must record its own evidence-backed final answer. In the first
    communication run only Mathematics finished, because the goal did not say others needed the answer.
  - The claim checker now accepts intermediate quantities (temperature rise) computable from cited evidence. It
    had flagged a correct P × R_th as unverified.
- Frozen plan: `local_data/experiments/rendezvous-v1/plan.json`, sha256
  `84985f9fc7512595b455787dc93461510db3320fe711f290914d006b55f4ce23`, frozen 2026-10-26 before any scored run.
  Seeds: fixed trial, 696464613104 and 512778079728.

### After campaign v1 (not part of the frozen plan)

Campaign v1 ran all nine cells on 2026-10-26 under the frozen sources. Its stored results (`results.json`, and the
run records shown in the dashboard) are kept exactly as recorded. Changes made afterwards alter the source digest,
so `lab-campaign` now refuses to extend v1; any further campaign needs a new plan folder.

- Leakage detector v1.1. In the v1 communication run on seed 696464613104, Physics and Environment each
  back-calculated Mathematics' private R_th = (122.9823 − 27.6) / 198.3 = 0.481 from the delivered answer. The v1
  rule counted these 2 values as findings. v1.1 reports such a value as inference only when it equals an arithmetic
  combination of numbers the agent held, to two digits beyond the shown precision. Coincidences (21 / 120 ≈ 0.18)
  and values from rounded inputs still count. The v1 numbers are reported unchanged; the reclassification is
  labelled post hoc.
- Report tables list cells in plan order. The dashboard lists each leakage finding with its assessment.
