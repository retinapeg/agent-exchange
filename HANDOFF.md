# Agent Exchange — implementation delivered locally

The original paused build was resumed on 2026-10-20. See `RESUME_AUDIT.md` for the starting
state and recovered requirements, `EXECUTION_CHECKLIST.md` for scope, `MORNING_REPORT.md`
for the final evidence-based implementation report, and `TEST_REPORT.md` for test receipts.
The continuation audit repaired verifier type/CSV handling and added evidence revalidation
to report generation. Preserved experiment and live acceptance counts remain unchanged.

All source remains uncommitted on the original `main` branch. Earlier source snapshots,
v1 live failures and pause evidence remain in ignored `local_data/`. Credentials are
private in `local_data/config.json`; do not paste or commit them.

```sh
./exchange.sh up
./exchange.sh demo
./exchange.sh showcase --live
./exchange.sh test
./exchange.sh benchmark --resume
./exchange.sh report
./exchange.sh down
./exchange.sh status
```

The observer is at http://127.0.0.1:8715. Use the observer operator token from local config
for login. Existing CLI authentication is reused for optional live calls. `live-pilot`
reuses the immutable v2 results; it does not silently create fresh trials.
The overnight continuation adds an interactive task/approval dashboard, three real provider
offers, observed performance, connected trace spans and a frozen live showcase (2/2 verified).
`showcase --live` also reuses its existing results. Use a new dashboard task for fresh inference.
Full tests use isolated runtimes and wallets. `restart-check --crash` verifies an actual
owned provider crash; run it separately from other demonstrations.

Public testnet execution and real cross-project connections require explicit configuration.
No real service payments, mainnet access, funded-wallet imports, external outreach, commits,
pushes, public deployment or modifications of other projects occurred.
