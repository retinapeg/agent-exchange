# Agent Exchange — learning and verified checkpoint

Last checked: **2026-10-24, Europe/London**. Scope: this repository only.

## Current checkpoint — approval expiry and budgets, complete

**2026-10-24, Europe/London.** Two small production repairs in coordinator.py and
commerce.py, plus 21 new regressions in `tests/test_approval_budget.py`. No dependency,
schema, selection-policy, expiry rule, ledger accounting or task-finalization change.
The installed Python 3.12.14 environment was reused. README describes the clearer errors;
AE-005 clarifies the existing expiry contract and AE-012 records the implementation choice.

- All eligible quotes over the task cap now produce a persisted policy failure naming
  the cap/lowest eligible quote and requiring a new request to change terms.
- An explicit ledger settlement refusal (HTTP 409) now reaches the buyer as a payment
  failure with its expiry reason. Previously it became provider HTTP 500 and buyer
  `outcome-unknown` transport failure. Neither defect allowed an excess charge.
- Controlled-clock tests exercise production ASGI handlers, guards and SQLite with a
  routed in-process transport and deferred buyer scheduling; no production clock changes.
  Existing full-suite tests separately cover real local HTTP and Chrome.

### What the new regressions establish

Approval hashes the run ID, task, provider and full quote (including amount, payee,
asset/network and expiry). The checkpoint/preview precede approval; commerce saves the
quote before acceptance, the ledger saves its reservation/token before authorization,
and debit/credit/receipt/event commit atomically. Buyer/provider save admission results
only after the ledger response. Retry uses the original quote, order and authorization.

Expiry is checked at **now >= expires_at**, including the exact instant. Pending expired
approval returns actionable 409 and retains its unapproved preview. A replacement needs a
new request/quote and binding; old/altered bindings fail. Approval granted earlier cannot
bypass expiry before authorization or settlement. Negative tests inspect balances, holds,
orders, settlement rows and provider admission/tasks, not just errors. Valid reservations
and authorisations remain held; the existing explicit release path works before settlement.
Local admission-attempt markers conservatively remain `outcome-unknown` until reconciliation;
the ledger remains authoritative. There is no automatic release, refresh, refund or retry.

A committed payment still reconciles after expiry, including injected lost admission and
settlement responses: same receipt/order/authorization, no extra debit, completed work
preserved. Budget tests discover actual offers, check below/equal caps and mixed affordable
selection, reject changed-budget identity reuse, and verify run/provider/global caps count
reserved, authorised and settled exposure. No paid admission occurs for unaffordable work.

### Commands, results and retained failures

Run through the isolated runner (not bare pytest against the primary runtime):

```sh
.venv/bin/python -c "from exchange.evidence import check; raise SystemExit(check(name='approval-budget-focused', paths=('tests/test_approval_budget.py', 'tests/test_payments.py', 'tests/test_coordinator.py')))"
./exchange.sh test
```

- Focused: **36 passed in 7.12s**, exit 0, no skips:
  `local_data/receipts/approval-budget-focused-c3d2101e-fcd2-4169-8e31-27164f97ca4d`.
- Final full suite, run once after repairs: **131 passed in 27.60s**, exit 0, no skips:
  `local_data/receipts/tests-64181929-4862-45b7-bab8-404c94456d9e`.
- Fresh baseline: `check(name='approval-budget-baseline', paths=('tests/test_payments.py',
  'tests/test_coordinator.py'))`: **15 passed in 3.28s**, exit 0,
  `local_data/receipts/approval-budget-baseline-63a191d3-0cee-49a9-a6d2-69d9cfc7c00d`.
- Before repairs: `check(name='approval-budget-regressions-before',
  paths=('tests/test_approval_budget.py',))`: **15 passed / 3 failed**, exit 1,
  `local_data/receipts/approval-budget-regressions-before-0bb9031f-8777-4dd4-9234-38958877f296`.
  Failures were the two product reporting defects above; budget failed two controls.
- Focused confirmation before repairs: `check(name='approval-expiry-refusal-before',
  paths=('tests/test_approval_budget.py::test_approved_quote_expiring_before_new_effects',))`:
  **2 passed / 1 failed**, exit 1,
  `local_data/receipts/approval-expiry-refusal-before-530d74dd-f601-4457-8e44-71e79f417f27`.
  The assertion was moved ahead of explicit release to expose the original response
  directly. Reserved/authorised/settled cap coverage was then expanded; expectations
  were not weakened. No fixture, browser-permission or infrastructure failures occurred.

For each `check(...)` above, the invocation was `.venv/bin/python -c "from
exchange.evidence import check; raise SystemExit(check(...))"` with the listed arguments.
Every receipt contains the exact subprocess command, output, source manifest/archive and
runtime path. Failed tests changed only isolated fixture/audit state, and all five runners
stopped their owned services. Their final service states were freshly checked again.

### Preservation, scope and one next proposal

Startup: `main`, HEAD `e6cce9ef9be7895e5b72ecd14817c6b2a7e0c296`, four tracked edits and
five untracked files, nothing staged. Source exactly matched the prior lifecycle-handoff
manifest/archive. Historical 110-test and 7-test results were verified as receipts, not
presented as fresh executions. Prior evidence is retained below and in
`local_data/receipts/lifecycle-handoff-3499e439-e4a1-424c-b5be-5a091f9575cb`.

New audit: `.cache/approval-budget-audit-20261024T132531Z/` holds the 83-file source
snapshot, historical receipt verification, starting fingerprints and
`preservation-and-cleanup.json`. **3,209 primary files and 270 existing receipt files
unchanged**, no new primary files. AGENTS.md, the prior task guard and all three prior
changed/new test files are unchanged. Existing work was not staged/discarded/committed/pushed.
Current tree has six tracked modifications and six untracked files, including the new test.
All primary/validation services are offline; no validation service/test/browser processes
remain. `git diff --check` passed. No live calls, external connections or repeated campaigns.

Limits: controlled-clock expiry tests are in-process handler tests, not a distributed-clock
or production-security proof. Explicit release/reconciliation remains a low-level operator
workflow; conservative local attempt markers do not assert a ledger charge. No new ledger
hard-crash or asynchronous-result work was implemented.

**One next proposed milestone (not owner-approved):** review a bounded operator workflow
for reconciling/releasing expired holds, retaining the authoritative receipt and exact order.
Stop here; these notes authorize no further work. Historical sections below are provenance.

## Historical read-only checkpoint

- Root: `/Users/leo/Projects/agent-exchange`; branch: `main`.
- Audited HEAD: `e6cce9ef9be7895e5b72ecd14817c6b2a7e0c296` (20 October).
- Working tree was clean before this audit. Only `AGENTS.md`, `learning.md` and
  `decisions.md` are added; no source edits, commits or pushes were made.
- README, MORNING_REPORT, HANDOFF and RESUME_AUDIT were reviewed. Their claims that
  all source is uncommitted are historical: a later initial-build commit now exists.
- `./exchange.sh status` found the primary manager and all seven services offline.
  The build has finished; there is no active run to resume blindly.

## Historical read-only verification

- Existing Python 3.12.14 `.venv` and dependencies reused without installation.
- **`./exchange.sh test`: 94 passed in 22.84s, exit 0**, including the existing
  local HTTP, fault, MCP and isolated desktop/mobile browser checks.
- Receipt: `local_data/receipts/tests-00446ea2-a32a-441e-bec0-da10a83fa667/receipt.json`.
- Isolated test data: `local_data/validation-runs/205354a1-de1d-4756-8c12-ea4d83496e3f`.
  The receipt confirms the test manager stopped and all seven services were offline.
- Logs and preservation fingerprints: `.cache/resume-audit-20261024/`.
  **3,209** existing primary data/evidence files were fingerprinted before/after;
  none changed. This inventory excluded prior validation runs, snapshots and receipts.
- Tests used fixtures and a separate simulated wallet. No real model calls,
  public-network settlement, paid services or new integration connections were made.

## Evidence and limits to retain

- Read `BUILD_SPEC.md`/`EXECUTION_CHECKLIST.md` for established scope and
  `TEST_REPORT.md`, `PAYMENT_MODE_REPORT.md`, `INTEROPERABILITY_REPORT.md` for evidence.
- Historical MORNING_REPORT: original live pilot **0/4**, repaired v2 **4/4**, later
  live showcase **2/2**. Preserve all three; these are small synthetic trials, not
  a general quality guarantee. None was rerun by this audit.
- The historical 18,000-attempt selection campaign is simulated. Actual service
  HTTP and simulated credit movement do not demonstrate blockchain settlement.
- Public testnet requires explicit operator configuration; production isolation,
  real-user matchmaking and on-chain settlement remain unverified/unsupported.
- Continuum/Leo OS adapters are stub-tested inside this project. Real cross-project
  endpoints and credentials remain unapproved; do not import their data or code.
- Keep `local_data/config.json`, credentials and raw private receipts out of Git.
  Never reset demonstration balances to make a failing budget check pass.
- `preflight`, `live-safety`, fresh live tasks and some showcase paths can invoke
  models. Do not treat an old success or a reused operation ID as fresh verification.

## Continuation assessment and next step

**Ready for supervised local development.** Recheck status and ownership first.
Live calls, unattended runs, public testnet and cross-project integration require
separate scope; this audit did not start any of them.

Suggested next bounded task: a supervised free fixture task in the dashboard;
inspect its source, artifact and independent verdict, then stop owned services and
record the result. Choose one milestone before beginning new functionality.

Maintenance: refresh this checkpoint after verification and retain prior receipt
links/failures. Record durable choices in `decisions.md`.

## 2026-10-24 · Lifecycle continuation audit

- Preserved the startup source (81 files) and hashed 3,209 primary data/evidence
  files in `.cache/lifecycle-audit-20261024T124722Z/`; existing notes remain above.
- Baseline `./exchange.sh test`: sandbox Chrome launch failed (93 passed, 1 failed),
  receipt `local_data/receipts/tests-7d111ec3-a13b-46c0-88f4-274988c37122`.
  Authorized rerun outside the sandbox: **94 passed in 22.73s**,
  receipt `local_data/receipts/tests-a62eac81-3168-4f7b-8163-1b0e5875e8e1`.
- Revalidated 750 preserved trial files / 18,000 attempts with plan and row hashes;
  the current verifier checked 17,089 artifacts with no changed verdicts. Recorded
  invalid acceptances and budget violations are both zero within this simulation.
- Rechecked historical artifacts: original pilot 0/4, repaired v2 4/4, showcase 2/2.
  Six completed CLI receipts correlate with the two showcase run IDs (planning,
  extraction, interpretation). This is preserved local provenance, not fresh model
  execution or independent account/billing confirmation; actual charges stay unknown.
- Selected gap: `TaskStore.transition` only protected terminal states. It allowed
  an input-required task to complete without new input and artifacts on nonterminal
  transitions. Resolved by AE-008 and the verified checkpoint below.

## Historical lifecycle continuation — verified checkpoint

### What exists and the trust boundaries

Seven separate services use loopback HTTP: registry, buyer, requirements, CSV,
verifier/introduction provider, observer/dashboard and integer-credit ledger.
The pinned A2A SDK provides JSON-RPC/SSE; MCP is read-only. No dependencies were added.

1. An authenticated operator/buyer submits a task with an idempotency key. Same
   principal/key/content returns the saved run; changed content is rejected. IDs are
   generated UUIDs persisted in SQLite, **not deterministic hashes of the task text**.
2. Registry health/cards filter eligible providers. Buyer requests immutable quotes,
   applies policy and budget filtering, and checkpoints the provider/task/quote.
   Requirements offers are 3/5/8 CREDIT from csv/requirements/verifier respectively.
3. UI simulator work pauses for exact-preview operator approval; agents cannot grant
   it. Explicit CLI/API simulator work can authorize within configured caps. The free
   path works with the ledger offline. Approval and task execution states are distinct.
4. Paid admission uses HTTP 402, a bound quote/order/authorization and the authoritative
   simulator ledger. Debit, credit, receipt and settlement event share one transaction.
   A reused order does not transfer credits twice. Provider admission binds task input.
5. Provider stores input, task state and events; it executes fixtures or an explicitly
   enabled model. Artifact digest/input provenance and terminal state commit together.
6. Buyer independently checks source evidence/calculations and records its verdict.
   Task completion, useful output and payment settlement are separate claims. Dashboard
   shows recorded messages, quotes, receipts and trace/parent-span links.

Identity claims and model/provider output remain untrusted. Exact origins, scoped
credentials and an independent verifier constrain them; all services still share one
OS account. No production security or independent third-party interoperability claim.

### Finalization, duplicate delivery and restart

| Current provider state | Allowed next states through `transition` |
|---|---|
| Submitted | Working, failed, canceled, rejected |
| Working | Working progress, input-required, auth-required, completed, failed, canceled, rejected |
| Input-required / auth-required | Failed, canceled, rejected |
| Any terminal state | None; late/duplicate finalizers return false with no new events/artifact |

Only `submit` can continue an input-required task: a fresh key admits a new input
version and sets submitted. AUTH_REQUIRED resumption is not implemented. Completion
requires an artifact; other state changes cannot publish one. These are this project's
worker rules, not a claim about every transition allowed by A2A.

The selected gap was paused-task completion without renewed input, plus unchecked
state/artifact combinations. `tasks.py` now rejects these **inside the existing SQLite
write transaction before any writes**. No schema migration or payment change was needed.
Concurrent finalizers serialize; one outcome wins, and the loser cannot alter its artifact
or append a second terminal event. This was already transactionally supported; new tests
now check competing completion, cancellation and failure explicitly.

- Duplicate task: original persisted principal/key mapping and task ID are returned.
- Duplicate approval: same decision/binding is idempotent; changed binding or opposing
  decision conflicts. No silent quote increase; expired pending approval needs a new request.
- Duplicate result: terminal guard preserves the original artifact and event history.
- Failure during artifact publication: artifact event, status and task body roll back
  together. Recovery fails unfinished work; it does not silently repeat execution.
- Crash after committed simulated charge: original order/authorization reconciles to
  its saved receipt. Polls/replays do not charge. Charge-on-admission survives cancellation
  and failed delivery; automatic refund/escrow is not implemented.
- Unknown model outcome is retained as unknown, not retried or reported as free.

Limits: this change does not add an external result-delivery API or an input-version
token on worker completion calls. A future asynchronous callback protocol must bind the
execution version before accepting results across continuations. Mid-transaction hard
process kill/power loss is not the same experiment as the injected exception rollback.

### Reproduction commands and fresh outcomes

Use the existing environment; no installation is necessary in this checkout.
All commands below run fixtures only. `check()` creates isolated local ports, credentials
and a simulated wallet, supervises its children, and records final shutdown.

```sh
cd ~/Projects/agent-exchange
./exchange.sh test
.venv/bin/python -c "from exchange.evidence import check; raise SystemExit(check(name='task-finalization-after', paths=('tests/test_task_finalization.py', 'tests/test_core.py', 'tests/test_resume.py')))"
.venv/bin/python -c "from exchange.evidence import check; raise SystemExit(check(name='local-demo', paths=('tests/test_browser.py', 'tests/test_coordinator.py', 'tests/test_demo_recovery.py')))"
```

| Check | Actual outcome / receipt under `local_data/receipts/` |
|---|---|
| Baseline full suite | 94 passed in 22.73s; `tests-a62eac81-3168-4f7b-8163-1b0e5875e8e1` |
| New regressions against old source | 10 failed, 4 passed; `task-finalization-before-038eb675-b75c-401c-9f68-18445da6d8c4` |
| First targeted fix run | 31 passed, 2 failed due to test misuse of protobuf `data.update`; retained in `task-finalization-after-1c5a4f41-f12e-406f-8c99-ff9598219d2e` |
| Corrected targeted suite | 33 passed in 0.43s; `task-finalization-after-28202698-a84a-4832-8ebf-93ef771ff369` |
| Full suite after runtime fix + demo tests | **110 passed in 29.38s**; `tests-53cb4ce0-1810-4775-8e4b-2b229d8d22b8` |
| Local demo, including added UI trace/receipt assertions | **7 passed in 12.05s**; `local-demo-0ce9ce83-7563-43da-8a45-c3c1fcdc69c7` |

The final demo reran the only test changed after the full suite (browser assertions).
Each receipt includes exact pytest command/output, source manifest/archive, runtime
directory and all seven services offline. Initial sandbox Chrome failure is preserved
above; its permission-enabled baseline rerun passed. No genuine model call was repeated.
Final preservation check: **all 3,209 primary data/evidence files unchanged**, no new
primary files, AGENTS.md unchanged, and `git diff --check` passed. All validation runtimes
and primary services are offline; no matching test/service/browser process remains.
See `.cache/lifecycle-audit-20261024T124722Z/preservation-after.json`.

### Local demonstration and validated workflows

The 7-check demo covers UI task submission, three-provider comparison, exact 3-credit
approval, visible receipt, Show trace, verified artifact, duplicate submission, free CSV,
declined/forged approval, free SSE/clarification/cancellation/failure correction, and paid
provider SIGKILL/restart with the same task/result and unchanged balances.

Runtime: `local_data/validation-runs/a0b6fe55-f3e9-497c-8d3c-ff4fd716aef0/`.
Within its `receipts/`, `browser-4e3a4440-f5e8-4b03-b4fd-82c47a2f307d/` contains
workflow.json and approval/artifact/trace/desktop/mobile screenshots. Automated Chrome
checks passed with no page errors or horizontal overflow; approval, artifact, trace and
mobile screenshots were also inspected. `crash-restart-4483387c-3062-4614-93c0-1cb27678df15.json`
records the exact owned crash and unchanged provider task, buyer result and ledger balance.
The default dashboard was not started; validation used isolated dynamic loopback ports.

For a later attended manual walkthrough (uses the durable primary demo wallet):

```sh
cd ~/Projects/agent-exchange
./exchange.sh up
./exchange.sh demo
# Open http://127.0.0.1:8715; choose Deterministic local provider.
# For simulated credits, inspect the exact preview and approve or decline.
./exchange.sh down
./exchange.sh status
```

The startup command and default URL were verified in exchange.sh, common.py and private
config (only URL readout). Use `peers.observer.tokens.operator` locally to log in; never
copy it into a report. Stop at the end; do not run crash checks alongside another demo.
No live-mode command is needed for reproduction.

### Historical trials, offline methodology and provenance

The original 94-test receipts exist and the baseline was freshly reproduced. Historical
model outcomes were **artifact-revalidated, not rerun**: v1 0/4, repaired v2 4/4, later
showcase 2/2. Six completed, exit-0 CLI receipts in `local_data/models/*/receipt.json`
match showcase trace IDs and planning/extraction/interpretation roles. This establishes
repository provenance, not independent provider-side execution or actual account charges.
Known estimates, unknown charges and zero actual service transfers remain distinct.

Frozen `local_data/experiments/selection-c3534f0569677014/` contains 750 trials:
5 synthetic scenarios × 5 policies × 30 held-out seeds × 24 tasks = 18,000 attempts.
Provider quality/outage/price distributions are invented; keyed randomness pairs policies.
All attempted tasks remain in the denominator; private evaluator distributions do not
enter provider choice. Intervals are seed-level normal approximations, not a security bound.

This audit checked frozen plan/row hashes, reran `reports.revalidate_evidence` over 17,089
stored artifacts and all ten historical model trial artifacts, and independently summed
per-task/trial/provider costs against 25/200/150-credit caps. Zero changed verdicts,
invalid accepted artifacts or simulated budget violations were found. The campaign was
not regenerated. Receipts: `.cache/lifecycle-audit-20261024T124722Z/` contains
`evidence-revalidation.json`, `budget-revalidation.json` and `live-provenance.json`.
`./exchange.sh report` can also revalidate stored artifacts without inference, but it
regenerates historical reports and must not overwrite this current handoff unintentionally.

### Practical lessons, limitations and next step

- Validate lifecycle state before writing provenance. A transaction can atomically commit
  an invalid decision; atomicity alone does not make that decision valid.
- Preserve failed tests and trials; a corrected fixture or model prompt is new evidence.
  The new test initially treated protobuf Value as a mutable dict; rebuilding through
  the existing proto parser fixed the test without changing production serialization.
- A successful admission can be paid-but-not-useful. Keep its receipt even when independent
  verification or execution fails. Never reset wallet caps to make validation pass.
- Browser success is now fresh local Chrome evidence, not an assumption from historical
  screenshots. The simulator and fixture campaign do not prove arbitrary adversarial safety.
- Shared OS-account isolation, public settlement, real users and actual Leo OS/Continuum
  endpoints remain unimplemented/gated as described in AE-011. No external action occurred.
- `reports.morning()` still generates the historical report format, including old Git-state
  language. Do not run broad report regeneration as a routine resume action.

**Historical next step (now addressed above):** add deterministic tests for expired approval and a task cap below all
offered prices, asserting no order/charge and an actionable rejection. Other narrow followups
are precise ledger pre/post-commit process-crash injection and input-version binding before
any future external result callback. No additional functionality is authorized by these notes.
