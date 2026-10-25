# Agent Exchange — decisions

Current decisions are the stable AE entries below. The original audit notes are
retained for provenance; their "pending owner choices" paragraph is superseded for
the bounded offline lifecycle work authorized on 2026-10-24. External gates remain.

## 2026-10-24 · Repository-specific, attended continuation

**Accepted — current user scope.** Work only in this checkout, one branch and writer.
No restart-from-scratch, sibling edits, unattended work, background jobs, worktrees,
unsolicited commits or pushes. Reason: preserve working functionality and ownership
of each repository's code, processes and evidence.

## 2026-10-24 · Lightweight persistent context

**Accepted — this audit.** `AGENTS.md` loads `learning.md` (verified checkpoint,
evidence, unknowns and one next step) and this file (durable choices/rationale).
Update at meaningful verified milestones and handoff. These files are not a daemon,
runtime memory store or authorization to launch work or contact another service.

## 2026-10-24 · Isolated, supervised verification

**Retained project design.** The existing test runner owns a temporary runtime,
ports, credentials and simulated wallet, with shutdown in its cleanup path.
Inspect its final service state. Do not run crash/restart validation concurrently
with other work, reset the operator wallet, or kill processes without exact ownership.
Tests may start temporary children only as part of authorized attended validation.

## 2026-10-24 · Preserve evidence and payment boundaries

**Retained project contracts.** A completed provider task is not an independently
verified artifact; a signature is not settlement. Keep failed v1 live evidence,
separate later trial IDs, unknown cost fields and simulated/live labels. Do not
silently retry uncertain remote settlement or model outcomes, or reset budgets.

## Pending owner choices

No new model run, feature, public testnet endpoint/asset/payee/cap, or cross-project
credentials were approved here. Keep external connections disabled. The suggested
next step is one supervised free fixture walkthrough with shutdown as the stopping
condition; further functionality needs a selected milestone.

## AE-001 — Local, attended scope

- **Status:** accepted, 2026-10-24; retains the repository-specific audit decision.
- **Decision:** one writer on the existing branch; only repository-local changes,
  fixtures and simulated credits; no commits, live calls or external connections.
- **Rationale:** preserve existing implementation, evidence and process ownership.
- **Evidence:** AGENTS.md, current continuation request, startup Git/process audit.
- **Tradeoffs:** slower manual progression; no autonomous production operation.
- **Revisit condition:** explicit owner authorization for a separately bounded task.

## AE-002 — Preserve the HTTP architecture and application contracts

- **Status:** accepted; retained design.
- **Decision:** seven loopback services, pinned A2A SDK JSON-RPC/SSE, read-only MCP,
  provider-owned SQLite stores; quotes and cursor replay are application extensions.
- **Rationale:** reuse working protocols and storage without a second subsystem.
- **Evidence:** ARCHITECTURE.md, pyproject.toml, test_http.py, test_mcp.py.
- **Tradeoffs:** shared implementation/OS identity is not independent isolation;
  no signed cards, push notifications, gRPC or REST binding.
- **Revisit condition:** a concrete authorized interoperability requirement.

## AE-003 — Compare immutable quotes and measured outcomes

- **Status:** accepted; retained design.
- **Decision:** filter reachable, fresh, capable providers and task budget; apply
  fixed/random/cheapest/reliability/UCB policy to HTTP quotes and observed feedback.
  Keep fixture/live history separate. Save the selection before dispatch.
- **Rationale:** auditable choices without trusting self-reported quality.
- **Evidence:** coordinator.py, buyer.py, test_coordinator.py, frozen selection plan.
- **Tradeoffs:** selection-biased local history; unknown quality is not superiority.
- **Revisit condition:** independent provider data and a predeclared evaluation.

## AE-004 — Separate identity, completion and verification

- **Status:** accepted; retained design.
- **Decision:** receiver-specific credentials, principal-scoped reads, exact origins,
  no redirects/proxies; verify artifact/input hashes and source-based correctness.
  A card, completed state or payment receipt alone does not establish useful output.
- **Rationale:** limit authority and retain independent acceptance evidence.
- **Evidence:** security.py, client.checked_artifact, verification.py, adversarial tests.
- **Tradeoffs:** local credentials cannot defend against a compromised shared OS account.
- **Revisit condition:** separately sandboxed identities and independent security review.

## AE-005 — Exact approval; simulated charge on admission

- **Status:** accepted; retained design.
- **Decision:** UI payment requires operator approval of the task/provider/quote digest.
  Quote binds amount, input, payee, asset, network and expiry; agents cannot approve.
  Explicit API simulator requests may authorize within integer task/run/peer/global
  caps. No automatic paid fallback, refund or charge for polling.
- **Expiry clarification (existing contract, verified 2026-10-24):** `now >= expires_at`
  rejects new approval/settlement. Already committed settlement reconciles to its original
  receipt after expiry. A pending expired approval remains preserved and cannot authorize
  its replacement; a new request/quote requires its own exact binding. Validly created
  reservations/authorisations stay held until explicit release or reconciliation.
- **Rationale:** approval cannot silently expand spending; budget holds count as exposure.
- **Evidence:** coordinator.approval, commerce.py, ledger.py, approval/payment tests.
- **Tradeoffs:** admission may be paid even if execution, cancellation or verification fails.
- **Revisit condition:** explicit escrow/refund requirement and a separate design review.

## AE-006 — Stable operation identities and atomic local effects

- **Status:** accepted; retained design.
- **Decision:** reuse persisted principal/key mappings and original run/order/quote IDs.
  Changed-content reuse fails. SQLite `BEGIN IMMEDIATE`, unique constraints and FULL
  synchronous WAL transactions make balance changes, settlement receipt and event atomic.
  Provider task body, artifact and events are likewise one transaction.
- **Rationale:** lost responses and concurrent retries must not double-charge or finalize twice.
- **Evidence:** common.Database.tx, tasks.py, ledger.settle, test_payments.py,
  test_task_finalization.py and test_demo_recovery.py.
- **Tradeoffs:** local exactly-once effects rely on one service writer and SQLite durability;
  they are not end-to-end exactly-once remote delivery or power-loss certification.
- **Revisit condition:** multi-host writers, different storage, or remote settlement.

## AE-007 — Explicit recovery and bounded retry

- **Status:** accepted; retained design.
- **Decision:** unfinished provider work becomes failed on restart; do not rerun models.
  Buyer checkpoints retain provider/task/order; uncertain payment reconciles the original
  ledger order. Completed requests return saved results. Failed/unknown model calls need
  explicit new operations; no silent backend switch or new payment nonce.
- **Rationale:** uncertainty is not evidence that an operation did nothing.
- **Evidence:** tasks.recover, coordinator.py, models.py, test_resume.py, fault tests.
- **Tradeoffs:** operator intervention and paid-but-not-useful outcomes remain possible;
  cancelled work does not undo committed effects.
- **Revisit condition:** a bounded retry protocol with independent reconciliation evidence.

## AE-008 — Guard provider finalization inside the existing transaction

- **Status:** accepted, 2026-10-24; new lifecycle hardening.
- **Decision:** enforce the local transition table in `TaskStore.transition` before
  writes. Only working tasks may complete, with an artifact; other transitions cannot
  publish artifacts. Input-required tasks resume through `submit` with a new key/input
  version. Terminal tasks reject late events as no-ops. Missing tasks get an explicit error.
- **Rationale:** the old terminal-only check accepted paused-task completion and invalid
  state names. Keep state validation and artifact/event publication indivisible.
- **Evidence:** new regressions failed 10/14 before the fix; 33 targeted tests then passed;
  full suite 110 passed. Tests cover unchanged rejected records, competing finalizers,
  rollback between artifact and status writes, and restart/replay.
- **Tradeoffs:** deliberately narrower than all possible A2A state transitions. Working
  progress may repeat. AUTH_REQUIRED has no resumption API; payment approval stays separate.
  No schema migration, second ledger or generic event bus was introduced.
- **Alternatives rejected:** a broad coordinator rewrite or automatic resumption of paused
  tasks would expand authority and disturb stable code without solving this small store gap.
- **Revisit condition:** external result callbacks or AUTH_REQUIRED continuation; add explicit
  input-version binding before accepting asynchronous results from older executions.

## AE-009 — Private receipts and honest costs

- **Status:** accepted; retained design.
- **Decision:** correlate task/run/order IDs and hashes; never log bearer/authorization
  tokens. Keep config, wallet state, raw histories and model receipts ignored/private.
  Keep unknown account/build costs as null, distinct from zero real service transfers.
- **Rationale:** useful audits without turning traces into credential disclosure.
- **Evidence:** common.event, tracing.py, models.py, observer.py, SECURITY.md.
- **Tradeoffs:** raw local task history still contains source data; no general PII scrubber.
- **Revisit condition:** approved real-user data use with retention/deletion requirements.

## AE-010 — Isolated reproducible validation and persistent notes

- **Status:** accepted; extends the original isolated-verification/context decisions.
- **Decision:** reuse `exchange.evidence.check`; fresh local runtime/ports/wallet,
  serialized browser/demo/fault tests and verified shutdown. Keep source receipts and
  failed runs; update learning.md and this file at verified milestones.
- **Rationale:** repeatability must not spend/reset the primary demonstration wallet.
- **Evidence:** evidence.py, test_demo_recovery.py, full-suite and local-demo receipts.
- **Tradeoffs:** Chrome/system permissions are required; receipts occupy ignored storage.
  Notes provide context, never implicit authorization to launch work.
- **Revisit condition:** headless CI environment or changed process ownership model.

## AE-011 — External deployment and integration gates

- **Status:** deferred.
- **Decision:** no public endpoints, public/testnet settlement, real users, funded accounts,
  or actual Leo OS/Continuum connections in this continuation.
- **Rationale:** simulator, SDK fixtures and local integration stubs do not establish
  network settlement, production isolation or consent for another system.
- **Evidence:** PAYMENT_MODE_REPORT.md, INTEROPERABILITY_REPORT.md, test_x402.py;
  public execution remains unverified.
- **Tradeoffs:** local demonstrations cannot establish ecosystem interoperability.
- **Revisit condition:** explicit owner scope; approved endpoints/credentials and test-only
  asset/payee/caps; separate identities/sandboxing, TLS and identity provisioning, rate
  limits, privacy/retention rules, security review, reconciliation plan and independent
  settlement confirmation before any public deployment. No automatic funding or mainnet.

## AE-012 — Preserve actionable payment and budget refusals

- **Status:** accepted implementation decision within the requested expiry/budget milestone,
  2026-10-24; no expansion of operator authority.
- **Decision:** when eligible quotes exist but all exceed the task cap, persist a policy
  failure naming the cap and lowest eligible quote, with an instruction to submit a new
  request to change terms. Forward the ledger's explicit settlement HTTP 409 through the
  provider so the buyer records a payment refusal instead of transport uncertainty.
- **Rationale:** rejection must explain the actual constraint. Generic "no eligible provider"
  and provider HTTP 500 obscured valid budget/expiry decisions despite preventing charges.
- **Evidence:** `tests/test_approval_budget.py`; pre-fix run 15 passed / 3 failed and a
  focused expiry confirmation 2 passed / 1 failed; repaired focused suite 36 passed.
  Receipt paths and final suite are recorded in learning.md.
- **Tradeoffs:** no automatic quote refresh, hold release or refund. Local admission-attempt
  markers may remain `outcome-unknown` pending reconciliation; authoritative ledger state
  and receipts decide financial effects. No schema, clock, limits or selection-policy change.
- **Revisit condition:** an explicitly scoped recovery UX change. Automatic release or
  broader retry semantics would require separate evidence/design, not follow from this fix.
