# Resume audit — 2026-10-20

Recovered the original comprehensive prompt from the prior Agent Exchange session and
saved it privately at `local_data/receipts/original-requirements.md`. The repository root
and cwd were `/Users/leo/Projects/agent-exchange`; branch `main`, no commits. Existing
source was untracked. A recoverable source snapshot was created before edits under
`local_data/snapshots/resume-20261020T004121Z/`. No existing results were discarded.

| Original milestone | At resume | Work completed in this continuation |
|---|---|---|
| 1. Pinned standards and real exchange | Working | Rechecked official sources; standards and licence records |
| 2. Three providers and lifecycle | Working | Preserved; added scoped pagination and terminal-subscription checks |
| 3. Persistence and verification | Partial | Buyer/model checkpoints, registry freshness, failure taxonomy, crash/replay review |
| 4. Live buyer/provider | Partial, 0/4 verified | Explicit prompt contract repair; new v2 IDs; 4/4 verified; bounded live injection probe |
| 5. Payments | Placeholders | Typed negotiation, HTTP ledger/402/admission, budgets/reconciliation, SDK crypto/wire, gated testnet adapter |
| 6. Experiments and adversarial checks | Selection functions only | Frozen 18,000-attempt campaign, paired analysis, failure and negative controls |
| 7. Introductions/integration/MCP | Not implemented | Synthetic approval/consent/revocation, adapter/schema/fixtures, official read-only MCP |
| Final dashboard/reports | Backend only, no UI/docs | Responsive UI, actual browser smoke, reproducible reports, source archives and receipts |

Initial verification: 16 tests passed and five HTTP tests failed because the services were
offline after the requested pause. Starting only owned services restored the original
21-test passing baseline. Final verification and exact counts are in TEST_REPORT.md.

The failed v1 live pilot, original preflight failures, pause receipt and startup source
remain preserved. New validation uses new identifiers and the same deterministic rubric.
External testnet and real cross-project execution remain unconfigured; no permission was
inferred to access funded wallets, public endpoints or other personal repositories.

## Overnight continuation audit

The next request made BUILD_SPEC.md authoritative; it was read completely. Startup found
the same uncommitted `main` repository. Source snapshot:
`local_data/receipts/overnight-start-7fad0983-8aca-4802-8940-f2dbdb716a17/`.
BUILD_SPEC.md and the user-prepared overnight launcher were preserved unchanged.

| Area at overnight start | Starting classification | Final continuation work |
|---|---|---|
| Core protocol, payment simulator, verifier, original benchmarks | Completed and previously tested | Preserved; refreshed tests, benchmark and hard-crash evidence |
| Runtime selection | Partial: policy functions/offline evaluation, little competing live capability | Three actual requirement quotes, real outcomes, backend-scoped history |
| Dashboard | Partial: observed data, no usable submission workflow | Document/CSV form, live mode, immutable approval preview, durable submit keys |
| Leo OS approval adapter | Partial: schema declarations | Durable outbox/inbox, persistent cursor, exact-preview approval; local stub only |
| Trace graph | Partial: identifiers with unconnected parents | Request/context propagation and tested cross-process parent links |
| Dedicated model-switch/verifier fault checks | Not started | Injected exit/timeout/switch/verifier failures; no model inference claimed for these tests |
| Payment-independent operation | Code path worked; supervisor dependency unverified | Actual ledger outage test and optional-ledger supervision |
| Repeatable full validation | Partial: used demonstration credit balance | Fresh isolated runtimes; original wallet preserved |
| Longer end-to-end live demonstration | Not started | Frozen 2/2 live showcase; six actual Claude calls, one paid task, preserved source evidence |

No source was restarted or replaced wholesale. Final verification is 94 passing tests;
exact evidence, failed experiments and remaining external gates are in MORNING_REPORT.md.
