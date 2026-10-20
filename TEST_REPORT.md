# Test report

Generated 2026-10-20T01:31:48.185Z. Latest full run: **94 passed in 22.41s**.

Exact command, output, source manifest and recoverable source archive:
`local_data/receipts/tests-64630d5a-e737-4073-951b-e700926281c0`.

| Checks | Evidence |
|---|---|
| A2A SDK client → server; client → upstream SDK reference process | tests/test_http.py; local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/*wire.json |
| Durable deduplication, restart, principal isolation, cancellation races | tests/test_core.py, test_resume.py, test_adversarial.py |
| Quote negotiation, budget conservation, concurrent settlement, forged/expired terms | tests/test_payments.py |
| Lost response after real HTTP admission; reconcile without charging twice | tests/test_payments.py |
| Seller failure after payment; no poll charge, no paid fallback | tests/test_adversarial.py |
| Failed model switch, CLI-child cleanup, verifier failure after payment | tests/test_workflow_faults.py; injected subprocess faults, not live inference |
| Actual ledger process outage; free work continues; paid run resumes once | tests/test_workflow_faults.py; exact owned PID, preserved ledger |
| Three real quotes, measured feedback, bound approval, parent spans | tests/test_coordinator.py |
| Official x402 signing/verification and golden headers | tests/test_x402.py; local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/x402-sdk-0e17362a-2a73-4e0f-b504-1439daed01df.json |
| Configured testnet adapter against wire stub, mainnet refusal | tests/test_x402.py; public execution not performed |
| Benchmark reproduction, denominator, feedback and private-feature controls | tests/test_benchmark.py |
| Boolean/count separation, malformed CSV refusal, blank records and quoted newlines | tests/test_verification.py |
| Retained experiment/live verdicts rechecked before headline regeneration | tests/test_reports.py; local_data/reports/summary.json |
| Consent, revocation, withheld fields, A2A introductions, adapter contracts | tests/test_extensions.py |
| Official MCP process handshake/tools and forbidden dispatch | local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/mcp-stdio-79fe1017-120e-4ee1-8cab-0aacc66c8112.json |
| Real Chrome submit, quote approval, dedup, CSV, desktop/mobile, logout | local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/browser-b0150564-0f5a-4835-bfce-17d2064500ce/receipt.json |
| Existing live artifact, traces and real usage displayed in Chrome | local_data/receipts/browser-live-9ca504ad-2088-4c57-964c-e5970b59b5aa/receipt.json |
| All owned services stopped/restarted; original paid task and balances retained | local_data/receipts/restart-4eaf81e8-9439-4e7a-9556-2ba9868ea35c.json |
| Actual owned provider SIGKILL, restart, durable artifact and no second charge | local_data/receipts/crash-restart-7143b0af-ba98-4630-9466-0bd86d721c55.json |
| One bounded live prompt-injection/canary probe | local_data/receipts/live-injection-3dff4270-67db-43d0-8c57-f6427ece738e.json |

Historical failures are retained in earlier receipts and the startup snapshot. The original
live pilot failed its quality rubric, so its four completed tasks are not counted as verified.
No mock chain result is counted as settlement. Testnet wire tests and integration stubs are
explicitly separate from public-network or cross-project execution.

Browser tests require installed Chrome, run in a temporary repository-local profile, and
capture no authentication tokens. Every full test run uses new repository-local credentials,
ports and a separate simulator wallet, then verifies owned-process shutdown. It does not
reset or spend the demonstration wallet.
