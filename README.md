# Agent Exchange

**Product status: consumer matchmaking alpha.** The front door is now a consent-first human matching application. The old developer observatory lives at `/admin` when the legacy multi-service stack is running.

## Start the actual product

```sh
cd ~/Projects/agent-exchange
./consumer.sh serve
# Open http://127.0.0.1:8715
```

To try a real 20-person matchmaking demonstration in a separate synthetic-only database:

```sh
EXCHANGE_DEMO=1 ./consumer.sh seed-demo
EXCHANGE_DEMO=1 ./consumer.sh serve
```

Read **[CONSUMER_README.md](CONSUMER_README.md)** for the user journey, scoring, consent, tests, MCP adapter, hosting and privacy limitations. The standalone consumer app does not need the A2A/observer stack.

---

## Historical experimental A2A / observatory implementation

A local network where agents discover services, delegate useful work, return traceable
artifacts and optionally pay simulated credits. The buyer verifies the result against its
source. A completed task, a valid signature and a useful result are three different things.

Seven independently running local services communicate over actual HTTP: registry, buyer,
requirements extractor, CSV auditor, verifier/introduction provider, observer and simulator
ledger. Three more processes host the rendezvous lab's agents (below). The implementation uses the official A2A SDK, real SSE and a separate official MCP
stdio server for read-only discovery/status.

## Run

Requires Python 3.12+ and `uv`. Everything installed by these commands is repository-local.

```sh
./exchange.sh init
./exchange.sh up
./exchange.sh demo
./exchange.sh showcase
./exchange.sh status
./exchange.sh test
```

Open the legacy observatory at **http://127.0.0.1:8715/admin**. Log in with
`peers.observer.tokens.operator` from ignored `local_data/config.json`. The dashboard shows
observed agents, tasks, artifacts, verification, quotes, ledger state and event timelines.
Use **New task** to submit a document or CSV. Requirements can run through real CLI models;
CSV audits use the deterministic provider. The buyer compares three requirement offers
(3, 5 and 8 simulated credits) and maintains separate fixture/live outcome history.
For paid UI requests, review and approve the exact task and quote before any credits move.
Do not publish the config or raw local receipts. The browser smoke test uses installed
Chrome in an isolated repository-local profile; it does not use your normal browser profile.

### Agent rendezvous lab

Three Claude-backed agents (Physics :8717, Environment :8718, Mathematics :8719) run as separate processes. Each has
its own SQLite homebase memory, inbox/outbox, A2A card and credentials, and every turn is one bounded `claude` CLI
call. They exchange evidence over real A2A HTTP to compute a component's steady-state temperature.

Open the **Agent lab** panel at the top of the dashboard. For a live run, tick the approval box (at most 12 calls and
12 messages per run), then Start; Pause, Step, Inject fact, Resume, Stop and Replay control the run.

Conditions:
- **A:** isolated baseline.
- **B:** communication.
- **C:** intervention. It pauses at the end of round one so you can revise one agent's fact.

From the terminal: `./exchange.sh lab --mode intervention --brain claude --approve-live`, or `--brain fixture`
for no model calls. See [RENDEZVOUS_REPORT.md](RENDEZVOUS_REPORT.md) for launch details and results, and
[RENDEZVOUS_PROTOCOL.md](RENDEZVOUS_PROTOCOL.md) for the frozen experiment protocol.

Stop only project-owned processes:

```sh
./exchange.sh down
./exchange.sh status
```

`up` checks port ownership and refuses conflicts. `restart-check` deliberately restarts
all owned services and verifies that a paid operation and balances survive without another
charge. `restart-check --crash` injects SIGKILL into the exact owned provider, verifies its
durable artifact after restart, and checks the buyer response and unchanged balances.
Run it separately from other demos. Existing task stores are never reset by these commands.

## Working flow

1. The registry fetches and validates configured Agent Cards. Capability and identity claims
   remain visibly distinct from measured health and verified output.
2. The buyer obtains actual typed offers, compares prices and measured outcomes, persists
   its task/provider/quote decision, then sends an A2A message. Providers can
   ask for clarification, stream progress, fail or return artifacts with source hashes.
3. The independent verifier checks quoted requirement evidence or CSV statistics. Failed
   checks remain failed even when the provider says completed.
4. Optional simulator commerce negotiates immutable terms, returns HTTP 402, authorizes
   integer credits, settles once and admits a task. Polling and reconnecting never charge.

The free demo covers requirements, CSV clarification/continuation, streaming, cancellation,
failed CSV followed by correction, and independent verification. Real HTTP payment and
fault cases run in the tests. Nothing requires payment to use the free path.

## Reproduce the evidence

```sh
./exchange.sh benchmark --resume
./exchange.sh sdk-check
./exchange.sh report
```

The frozen campaign has **18,000 held-out simulated attempts**: five scenarios, five
selection policies, 30 seeds and 24 tasks. The observed run accepted **zero invalid
artifacts** and had **zero simulated budget violations**. Raw task artifacts and paired
uncertainty intervals regenerate [SELECTION_REPORT.md](SELECTION_REPORT.md). These are
invented provider distributions, not measurements of real model superiority.
`report` rechecks the preserved experiment and live artifacts with the current verifier
before publishing acceptance counts. It makes no new model calls and refuses changed
verdicts. The continuation audit repaired boolean/count confusion and CSV validation;
the original raw results and frozen experiment remain preserved.

The original live pilot remains **0/4 verified**. A repaired, separately identified
four-trial validation achieved **4/4 verified** with the original acceptance rule. It used
actual model-backed buyer planning, provider extraction and buyer interpretation. This is
a small development validation, not a general performance guarantee. Exact call counts,
cost estimates and known failures are in [MORNING_REPORT.md](MORNING_REPORT.md).
The new overnight showcase verified **2/2** longer document tasks using six actual model
calls, including a paid 3-credit task selected from three providers. Preserved raw evidence
is in `local_data/showcases/v1-live/`. No blockchain settlement or actual service charge occurred.

```sh
./exchange.sh preflight     # New bounded CLI probes using existing authentication
./exchange.sh live-pilot    # Frozen v2 results; reruns reuse original operation IDs
./exchange.sh showcase --live # Two frozen real-model trials; repeats reuse results/receipts
./exchange.sh browser-check # View existing real data in isolated Chrome; no new model calls
./exchange.sh live-safety   # One NEW live injection probe; consumes a model call
./exchange.sh mcp           # Official MCP stdio server; no console banner on stdout
```

CLI limits: two simultaneous calls, 120 seconds/call, 2,000 lifetime attempts, bounded output,
no automatic model retries and no new paid API route. Unknown account charges/build usage
remain unknown. `report` does not make model calls.

## Supported modes and limits

| Mode | Status |
|---|---|
| A2A 1.0 JSON-RPC + SSE | Real local traffic; task lifecycle, artifacts, cancellation, scoped cursors/replay |
| Free service | Working without the payment ledger |
| `leo-sim-v1` | Real HTTP 402 flow; non-monetary integer CREDIT; separate durable ledger |
| x402 SDK v2 fixture | Official signing/verification/golden headers; no chain settlement |
| Public testnet | Base Sepolia-only adapter, wire-stub tested; **not publicly executed** |
| MCP | Official SDK stdio, read-only discovery/run/payment status |
| Cross-project adapters | Strict envelopes, stub source → A2A, persistent observer cursor and exact-preview approval; real endpoints unconfigured |
| Developer introductions | Fictional profiles, field approval, purpose checks, bilateral consent and revocation |

Simulator caps are 25 credits/task, 200/run, 150/provider and 1,000 globally, counting held
and settled exposure. Each `test` invocation creates its own repository-local runtime,
credentials, checked ports and wallet, and shuts it down afterward. Demo/UI spending remains
durable; reaching a cap is an intentional stop, not permission to reset accounting.
Cancellation or failure after admission does not refund.

Testnet requires an explicit local config, exact public HTTPS IP endpoint with valid TLS,
approved asset/payee/cap and a fresh test-only account (`testnet-init`). `testnet --config
<path>` is a separate command. It cannot enable mainnet or import an existing wallet.
Test-asset caps are separate from simulator balances. No token acquisition is automated.
Uncertain remote settlement blocks retry pending operator reconciliation.

Push notifications, signed/extended cards, gRPC/REST binding, general DNS peer discovery,
production isolation, refunds/escrow and real-user matchmaking are unsupported. Services
share one local OS account. No other personal repository was modified or connected.

Read [STANDARDS.md](STANDARDS.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[SECURITY.md](SECURITY.md), [PAYMENT_MODE_REPORT.md](PAYMENT_MODE_REPORT.md),
[INTEROPERABILITY_REPORT.md](INTEROPERABILITY_REPORT.md) and [TEST_REPORT.md](TEST_REPORT.md)
for exact evidence and limitations. All changes are intentionally uncommitted.
