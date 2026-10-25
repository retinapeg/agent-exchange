# Morning report — Agent Exchange

## Current checkpoint — approval expiry and insufficient budgets, 24 October 2026

**Complete; stop at review.** Two minimal reporting repairs, 21 new regression cases,
**131 tests passing**, all services offline. No live model calls, external services,
real transfers, commits or pushes. The prior lifecycle implementation is preserved.

### Changes and established behavior

- `exchange/coordinator.py`: distinguish an eligible but unaffordable quote set from
  missing providers. Persist the task cap/lowest eligible quote and a new-request remedy.
- `exchange/commerce.py`: preserve an explicit ledger settlement 409 through the provider.
  The buyer now records payment refusal instead of a fabricated transport uncertainty.
- `tests/test_approval_budget.py`: production ASGI handlers/guards and SQLite under a
  controlled quote clock and in-process HTTP transport. No production clock seam or new
  payment subsystem. learning.md, decisions.md and README explain the verified behavior.

New tests cover exact expiry (one microsecond before, exactly at, after), expiry while
pending and between approval/reservation/settlement, replacement approval binding, and
reconciliation after settled responses are lost and the quote expires. Financial records,
held exposure and absence of provider admission are checked. Valid holds require explicit
release/reconciliation; expired pending evidence is preserved, not silently refreshed.

Budget tests use actual offered prices: below every offer, one below/exactly equal to a
chosen offer, mixed affordable selection, repeated refusal, immutable-budget conflict,
and run/provider/global caps counting reserved, authorised and settled exposure.
Positive cases remain useful; committed receipts replay without another debit.

### Reproduce and inspect evidence

```sh
cd /Users/leo/Projects/agent-exchange
.venv/bin/python -c "from exchange.evidence import check; raise SystemExit(check(name='approval-budget-focused', paths=('tests/test_approval_budget.py', 'tests/test_payments.py', 'tests/test_coordinator.py')))"
# 36 passed in 7.12s; exit 0, no skips
./exchange.sh test
# 131 passed in 27.60s; exit 0, no skips
```

Receipts:
- `local_data/receipts/approval-budget-focused-c3d2101e-fcd2-4169-8e31-27164f97ca4d`
- `local_data/receipts/tests-64181929-4862-45b7-bab8-404c94456d9e`

Fresh baseline was 15 passing payment/coordinator checks. Before repair, new regressions
had 3 failures (15 passed); focused expiry confirmation had 1 failure (2 passed). Both
commands exited 1, with owned services stopped. These were product error-reporting defects,
not overspending or infrastructure failures. Exact commands, errors, receipt paths and
resolution are in learning.md; failed evidence remains preserved. The full suite was run
once after the final repair and includes existing local HTTP/Chrome tests. No old campaign
or live pilot was rerun.

### Git, cleanup and remaining limits

Still `main` at `e6cce9e`; nothing staged, committed or pushed. Six tracked modifications
and six untracked files include all prior work. The prior task guard, browser/demo/finalization
tests and AGENTS.md are byte-identical to startup. Today's new source archive and fingerprints:
`.cache/approval-budget-audit-20261024T132531Z/`. **All 3,209 primary files and 270 pre-existing
receipt files are unchanged**, with no new primary files. Primary and all five isolated
runtimes were checked offline, no validation processes remain, and `git diff --check` passed.

Expiry tests use controlled in-process transport; they do not prove distributed clocks,
power-failure behavior or production security. Local attempt markers may remain uncertain
until reconciliation even when the current request is explicitly refused; only the ledger
and its receipt determine financial effects. Public settlement, real accounts/users and
actual Leo OS/Continuum remain gated. No new ledger hard-crash or async-result work occurred.

**One next proposal, requiring a new task:** a bounded operator release/reconciliation
workflow for expired holds, preserving the original order and receipt. Do not start it now.

Prior lifecycle checkpoint: learning.md's historical section and
`local_data/receipts/lifecycle-handoff-3499e439-e4a1-424c-b5be-5a091f9575cb/source.tar.gz`.
That archive retains the earlier MORNING_REPORT and its failures/outcomes. The overnight
handoff below is older provenance, not authorization to execute its live commands.

---

## Historical overnight handoff — 20 October 2026 (retained provenance)

The statements and optional live commands below describe the previous run. They do not
authorize fresh model calls, startup or external work. Use the current checkpoint above.

The local demonstration works. The overnight continuation preserved the existing system
and closed the main usability gaps: interactive task submission, real provider comparison,
operator payment approval, connected HTTP spans, and repeatable validation with isolated wallets.
No commits, pushes, deployments, other-project changes or real payments were made.

## Start and demonstrate

```sh
cd ~/Projects/agent-exchange
./exchange.sh up
./exchange.sh status
./exchange.sh demo
./exchange.sh showcase
./exchange.sh showcase --live
```

Open **http://127.0.0.1:8715**. Use `peers.observer.tokens.operator` from the private
`local_data/config.json`. The dashboard has a task form, three provider cards, approvals,
artifacts, independent verdicts, payment receipts, model usage and an observed-event timeline.
Choose **Live buyer + provider** to make a new model-backed request. The live source service
currently supports requirements extraction; CSV analysis is deterministic.

`demo` is free and exercises streaming, CSV clarification and continuation, cancellation,
failure and corrected resubmission. `showcase` performs two durable fixture trials;
`showcase --live` demonstrates the same flow using actual CLI models. Showcase commands
reuse their frozen operation IDs when repeated: this preserves the artifact and avoids a
new model call or charge. Use a fresh dashboard task for a new trial; “Start another
identical task” explicitly requests another operation.

For payment review, choose **Simulated credits**, **Lowest quoted price**, submit, then
inspect the immutable task/quote and approve or decline. Requirement offers are 3, 5 and
8 CREDIT. Free mode needs no ledger. Agent ratings are claims; only observed outcomes enter
the buyer's performance history, separately for fixture and live backends.

```sh
./exchange.sh test                 # Fresh isolated runtime, then owned-process cleanup
./exchange.sh benchmark --resume   # Validate/reuse the frozen offline campaign
./exchange.sh browser-check        # Chrome view of existing live data; no inference
./exchange.sh restart-check --crash # Deliberate owned-provider crash; costs 5 test credits
./exchange.sh report               # Recheck artifacts and regenerate reports; no inference
./exchange.sh down
./exchange.sh status
```

Run crash/restart validation by itself: it deliberately makes all seven services temporarily
unavailable. `up` refuses occupied ports and never kills unrelated services. `down` addresses
only recorded, matching owned processes. Completed task and payment databases are preserved.

## Verification against the primary success criteria

| Criterion | Status and evidence |
|---|---|
| Three provider identities discovered through Agent Cards | **Live-verified local HTTP**; three distinct processes/stores; shared implementation |
| Natural-language buyer and useful live provider | **Live-verified model calls**; latest showcase 2/2 verified; 21/22-line fictional briefs |
| Genuine A2A messages and artifacts | **Live-verified** A2A 1.0 JSON-RPC/SSE; official SDK client and separate upstream-handler reference peer tested |
| Independent correctness check | **Implemented and live-verified**; separate source-based verifier; a provider's completed state does not imply acceptance |
| HTTP 402 and auditable simulated payment | **Live-verified local HTTP** using pinned SDK wire helpers; latest live showcase spent 3 simulated credits; no chain settlement |
| Price/reliability/performance selection | **Implemented and real-HTTP tested**; three actual quotes, observed feedback, five policies; causal superiority is not inferred |
| Dashboard messages/progress/usage/costs/approval | **Live-verified Chrome** desktop/mobile, task/approval workflow, real model artifact/usage display |
| Kill/restart without losing completed work or double charge | **Live-verified SIGKILL** of exact owned provider; original provider artifact, buyer response and ledger balances unchanged |
| Automated evaluation and fault accounting | **94 passed in 22.41s**; **18,000** offline attempts; failure categories and distinct task denominators |
| Reproducible evidence | **Implemented and verified**; frozen plans, raw artifacts, source archives, receipt links and report-time artifact revalidation |

Browser workflow: `local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/browser-b0150564-0f5a-4835-bfce-17d2064500ce/receipt.json`. Existing live result and model usage:
`local_data/receipts/browser-live-9ca504ad-2088-4c57-964c-e5970b59b5aa/receipt.json`. Hard crash: `local_data/receipts/crash-restart-7143b0af-ba98-4630-9466-0bd86d721c55.json`.
Full tests/source archive: `local_data/receipts/tests-64630d5a-e737-4073-951b-e700926281c0`. New live evidence:
`local_data/showcases/v1-live/` (plan, results, wire observations, events and summary).

## Genuine models, payment modes and costs

- **31 recorded CLI attempts**, 29 completed and
  2 failed. Backend attempts: {'claude': 28, 'codex': 3}.
  The overnight showcase added six genuine calls: buyer planning, provider extraction and
  buyer interpretation in each of two trials, using `claude-fable-5`. Codex `gpt-6.1-sol`
  was also successfully preflighted earlier; the paired showcase used Claude.
- Original live v1 remains **0/4 verified**.
  The repaired v2 remains **4/4**; new showcase
  **2/2**. These small synthetic-document
  trials are not general model-quality estimates. Failed results were not erased.
- Known CLI estimates total **$0.970300** across
  **28/31** calls. Actual account charges, parent
  build-model usage and build cost are **unknown**. Cache usage is retained in CLI receipts;
  the CLI estimate is counted once per call. No separately billed API route was enabled.
- Mode A free and mode B `leo-sim-v1` work over real HTTP. Mode C uses official x402 v2
  schemas, signing and cryptographic verification with explicit chain-read fixtures:
  **mock-tested chain boundary**, not settlement. Mode D public testnet is implemented and
  wire-stub tested but **blocked from public execution pending operator configuration**.
  Actual service expenditure is **zero**. No funded wallet was accessed.

## Experiments and failed checks

The latest frozen campaign is `local_data/experiments/selection-c3534f0569677014`: five scenarios × five policies ×
30 held-out seeds × 24 tasks. It retained **0 invalid accepted artifacts**
and **0 budget violations**. SELECTION_REPORT.md contains scenario-level
trade-offs, paired differences and uncertainty intervals. Synthetic provider distributions,
latencies and regret are not real-model measurements. Older campaigns remain preserved.

Report generation rechecked 17,089 offline
artifacts and all preserved live pilot/showcase results without new inference.

Preserved failures include the original four quality-rejected live artifacts, two early
Codex launch failures, and an MCP test that initially read the default runtime before its
child environment was fixed. During this continuation a free demo was accidentally launched
while the deliberate crash check was shutting services down; it received ConnectError.
The serialized rerun passed. A later ledger-outage test found that the supervisor's port
probe could reject a closed connection in TIME_WAIT during restart. The probe now matches
the server's address-reuse behavior; restart passes and an active-listener refusal test
also passes. Both failed receipts are retained. Tests also intentionally inject
model exit/timeout/switch failures, verifier unavailability after payment, lost responses,
forged credentials/receipts, malformed artifacts, cancellation races and storage faults.

## Implemented, stub-tested and remaining boundaries

Synthetic developer introductions, field approval, purpose restriction, bilateral contact
consent and revocation are implemented and tested with invented profiles. No real-user or
romantic-compatibility result is claimed. The official MCP stdio server is implemented and
process-tested for read-only discovery/status. It cannot dispatch, spend or disclose.

Continuum's buyer adapter and Leo OS's observer/approval adapter are **implemented and
stub-tested inside this repository**. The observer consumes strict `leo.integration.v1`
envelopes with a persistent cursor, rejects changed-content replay, and binds approval to
the exact preview before buyer HTTP dispatch. **Actual cross-project integration is blocked
pending approved endpoints and credentials**. No other project was read into or modified.

**Not implemented / unsupported:** production OS isolation, signed/extended Agent Cards,
push notifications, gRPC or REST bindings, arbitrary DNS peer discovery, real-user
matchmaking, escrow/refunds, and independent on-chain settlement confirmation. Public
testnet and local-chain settlement have not been executed. Local providers share an
implementation and OS account; independent SDK boundary tests are reported separately.
The GUI currently submits new tasks; advanced A2A continuation/cancellation are demonstrated
by the CLI/API. The supervisor fails closed on a core-service crash; recovery uses explicit
`up`. A ledger-only outage leaves free collaboration available and paid work fails closed.
Expired quotes require a new request and renewed acceptance. Simulator caps remain in force;
validation uses separate wallets and never resets the demonstration balance.

Exact pending approvals: test-only public endpoint/asset/payee/amount configuration and
resources for public-testnet execution; endpoint/credential authorization for actual
Leo OS/Continuum integration. Neither is needed for the local demonstration. There are no
known failing local tests at delivery; the unsupported boundaries above remain explicit.

## Manual check

Start the services, submit a free fixture task, then a live requirements task. Confirm exact
evidence in the returned artifact. Submit a simulated paid task with the cheapest policy,
inspect its quote, approve it, and confirm exactly one receipt. Reload the page and inspect
the trace and usage. Finally stop/start the services and check the same completed task.
All source changes remain uncommitted. Do not publish private `local_data/`.
