# Payment mode report

| Mode | Implementation and evidence | Actual settlement |
|---|---|---|
| A · Free | Real separate-process A2A, independent artifact verification | No payment |
| B · Simulator | HTTP 402, accepted immutable quote, authorization, ledger settlement, admission ticket | Integer CREDIT only; `leo-sim-v1`, `leo:local` |
| C · SDK fixtures | Official x402 2.25.0 v2 wire types, signing, verification, golden tests | None; chain reads explicitly mocked |
| D · Public testnet | Configured Base Sepolia-only client, durable signed payload, gated fresh test account; wire-stub tested | **Not executed**; operator configuration/test assets absent |

The simulator owns an initial total of 1,000 credits. Account balances plus held availability
obey conservation: holds are reserved within the buyer balance, settlement transfers that
balance to a provider. Reservations, authorizations, settled, failed and released amounts are
separate. Unknown remote outcomes are retained in buyer/provider payment records while the
ledger remains the authoritative source of settled/held amounts. No new nonce/order is
created to retry uncertainty. Per-task/run/peer/global exposure caps include held and settled
amounts. The ledger transaction makes debit, credit and receipt indivisible.

A task is charged on admission. The ticket binds principal, order, immutable quote and input.
Status polling, SSE reconnect and artifact retrieval never charge. Lost responses and process
restart reuse the order and original task. Evidence: `local_data/receipts/crash-restart-7143b0af-ba98-4630-9466-0bd86d721c55.json`, `local_data/receipts/restart-4eaf81e8-9439-4e7a-9556-2ba9868ea35c.json` and tests/test_payments.py.
The dashboard requires an explicit operator decision over an immutable preview before
authorization. Changed or expired terms cannot reuse that approval. CLI/API requests may
explicitly authorize simulator spending within deterministic caps. No agent grants UI consent.

Release is allowed before settlement. After admission, cancellation or bad delivery does not
refund the charge. Seller failure after payment is tested and reported as paid-but-not-useful.
There is no escrow, automatic refund, atomic fair exchange or on-chain reversal claim.

SDK cryptographic evidence: `local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/x402-sdk-0e17362a-2a73-4e0f-b504-1439daed01df.json`. Negative controls include changed payee, amount,
nonce, expiry and network. A valid signature is not settlement. The public-testnet client
records a resource-server settlement response but does not claim independent chain confirmation.
An unresolved testnet response blocks automatic retry; operator reconciliation is required.

Testnet has no mainnet switch and no external wallet import path. Explicit repository-local
configuration must pin Base Sepolia, an exact public HTTPS IP endpoint with valid TLS,
asset, payee, integer amount cap and operation ID. General DNS endpoints are not supported.
`testnet-init` creates a fresh project-only account; funding/acquiring tokens is never automatic.
No testnet operation, funded-wallet access or real service payment occurred in this assignment.
Actual service expenditure: **0**. Model subscription/account charges remain unknown.
