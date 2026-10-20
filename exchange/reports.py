"""Regenerate headline reports from immutable local receipts and raw trial records."""
import json
import re
from collections import Counter
from pathlib import Path

from exchange.common import ROOT, DATA, digest, now, write_json
from exchange.benchmark import analyse
from exchange.evidence import receipt
from exchange.match_evaluation import evaluate
from exchange.client import checked_artifact
from exchange.verification import verify


def read(path):
    return json.loads(path.read_text())


def latest(pattern, directory=None):
    paths = sorted((directory or DATA/'receipts').glob(pattern), key=lambda p:p.stat().st_mtime)
    return paths[-1] if paths else None


def rel(path):
    return str(path.relative_to(ROOT)) if path else 'not recorded'


def put(name, text):
    (ROOT/name).write_text(text.strip()+'\n')


def revalidate_evidence(rows, pilots):
    """Check retained artifacts with current rules without rerunning providers."""
    checked = 0
    for row in rows:
        if 'artifact' not in row:
            continue
        verdict = verify(row['request'], row['artifact'])
        if verdict['accepted'] is not row['verifier']['accepted'] or int(verdict['accepted']) != row['verified']:
            raise ValueError('retained experiment verdict changed; preserve and investigate before reporting')
        checked += 1
    live = {}
    for name, pilot in pilots.items():
        verified = 0
        for result in pilot['results']:
            if not result.get('task'):
                if result.get('verifier',{}).get('accepted') or result.get('status')=='verified':
                    raise ValueError('accepted live result has no task artifact')
                continue
            task = result['task']
            request = task['history'][0]['parts'][0]['data']
            verdict = checked_artifact(task, request)
            if verdict['accepted'] is not result['verifier']['accepted']:
                raise ValueError('retained live verdict changed; preserve and investigate before reporting')
            verified += int(verdict['accepted'])
        if len(pilot['results']) != pilot['finished'] or verified != pilot['verified']:
            raise ValueError('retained live summary disagrees with artifacts')
        live[name] = {'checked': len(pilot['results']), 'verified': verified}
    return {'offline_attempts': len(rows), 'offline_artifacts_checked': checked,
            'live': live, 'changed_acceptance_verdicts': 0, 'new_model_calls': 0,
            'verifier_sha256': digest((ROOT/'exchange/verification.py').read_bytes())}


def morning(s, test_folder, experiment_folder, pilots):
    showcase=s.get('showcase') or {}
    return f'''# Morning report — Agent Exchange

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
| Natural-language buyer and useful live provider | **Live-verified model calls**; latest showcase {showcase.get('verified',0)}/{showcase.get('planned',2)} verified; 21/22-line fictional briefs |
| Genuine A2A messages and artifacts | **Live-verified** A2A 1.0 JSON-RPC/SSE; official SDK client and separate upstream-handler reference peer tested |
| Independent correctness check | **Implemented and live-verified**; separate source-based verifier; a provider's completed state does not imply acceptance |
| HTTP 402 and auditable simulated payment | **Live-verified local HTTP** using pinned SDK wire helpers; latest live showcase spent {showcase.get('simulated_credits',0)} simulated credits; no chain settlement |
| Price/reliability/performance selection | **Implemented and real-HTTP tested**; three actual quotes, observed feedback, five policies; causal superiority is not inferred |
| Dashboard messages/progress/usage/costs/approval | **Live-verified Chrome** desktop/mobile, task/approval workflow, real model artifact/usage display |
| Kill/restart without losing completed work or double charge | **Live-verified SIGKILL** of exact owned provider; original provider artifact, buyer response and ledger balances unchanged |
| Automated evaluation and fault accounting | **{s['tests']}**; **{s['offline_attempts']:,}** offline attempts; failure categories and distinct task denominators |
| Reproducible evidence | **Implemented and verified**; frozen plans, raw artifacts, source archives, receipt links and report-time artifact revalidation |

Browser workflow: `{s['browser']}`. Existing live result and model usage:
`{s['browser_live']}`. Hard crash: `{s['crash_restart']}`.
Full tests/source archive: `{rel(test_folder)}`. New live evidence:
`local_data/showcases/v1-live/` (plan, results, wire observations, events and summary).

## Genuine models, payment modes and costs

- **{s['model_attempts']} recorded CLI attempts**, {s['model_status'].get('completed',0)} completed and
  {s['model_status'].get('failed',0)} failed. Backend attempts: {s['model_backends']}.
  The overnight showcase added six genuine calls: buyer planning, provider extraction and
  buyer interpretation in each of two trials, using `claude-fable-5`. Codex `gpt-6.1-sol`
  was also successfully preflighted earlier; the paired showcase used Claude.
- Original live v1 remains **{pilots['v1']['verified']}/{pilots['v1']['finished']} verified**.
  The repaired v2 remains **{pilots['v2']['verified']}/{pilots['v2']['finished']}**; new showcase
  **{showcase.get('verified',0)}/{showcase.get('finished',0)}**. These small synthetic-document
  trials are not general model-quality estimates. Failed results were not erased.
- Known CLI estimates total **${s['known_cli_estimate_usd']:.6f}** across
  **{s['calls_with_estimates']}/{s['model_attempts']}** calls. Actual account charges, parent
  build-model usage and build cost are **unknown**. Cache usage is retained in CLI receipts;
  the CLI estimate is counted once per call. No separately billed API route was enabled.
- Mode A free and mode B `leo-sim-v1` work over real HTTP. Mode C uses official x402 v2
  schemas, signing and cryptographic verification with explicit chain-read fixtures:
  **mock-tested chain boundary**, not settlement. Mode D public testnet is implemented and
  wire-stub tested but **blocked from public execution pending operator configuration**.
  Actual service expenditure is **zero**. No funded wallet was accessed.

## Experiments and failed checks

The latest frozen campaign is `{rel(experiment_folder)}`: five scenarios × five policies ×
30 held-out seeds × 24 tasks. It retained **{s['invalid_accepted']} invalid accepted artifacts**
and **{s['budget_violations']} budget violations**. SELECTION_REPORT.md contains scenario-level
trade-offs, paired differences and uncertainty intervals. Synthetic provider distributions,
latencies and regret are not real-model measurements. Older campaigns remain preserved.

Report generation rechecked {s['artifact_revalidation']['offline_artifacts_checked']:,} offline
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
'''


def report():
    generated = now()
    pointer = DATA/'experiments/latest.json'
    if not pointer.exists():
        raise ValueError('run benchmark before report')
    folder = ROOT/read(pointer)['directory']
    frozen = read(folder/'plan.json')
    rows = []
    for path in sorted((folder/'trials').glob('*.json')):
        value = read(path)
        if value['sha256'] != digest(value['rows']) or value['plan_digest'] != digest(frozen):
            raise ValueError('corrupt or mismatched raw trial: '+str(path))
        rows.extend(value['rows'])
    analysis = analyse(rows)
    write_json(folder/'analysis.json',analysis)
    calls = [read(p) for p in (DATA/'models').glob('*/receipt.json')]
    call_counts = Counter(r['status'] for r in calls)
    backends = Counter(r['backend'] for r in calls)
    known = [r['estimated_inference_usd'] for r in calls if r.get('estimated_inference_usd') is not None]
    pilot1 = read(DATA/'receipts/live-pilot.json')
    pilot2 = read(DATA/'receipts/live-pilot-v2.json')
    pilots={'v1':pilot1,'v2':pilot2}
    showcase=read(DATA/'showcases/v1-live/summary.json') if (DATA/'showcases/v1-live/summary.json').exists() else None
    if showcase:
        pilots['showcase']=read(DATA/'showcases/v1-live/results.json')
    revalidated = revalidate_evidence(rows, pilots)
    test = latest('tests-*/receipt.json')
    tested = read(test) if test else None
    if not tested or tested['results']['exit_code'] != 0:
        raise ValueError('latest full test receipt is not successful')
    test_summary = re.findall(r'\d+ passed[^\n]*',tested['results']['output'])[-1]
    validation=ROOT/tested['results']['runtime_directory']/'receipts' if tested['results'].get('runtime_directory') else DATA/'receipts'
    browser,mcp,sdk=(latest(p,validation) for p in ('browser-*/receipt.json','mcp-stdio-*.json','x402-sdk-*.json'))
    restart,injection,crash,browser_live=(latest(p) for p in ('restart-*.json','live-injection-*.json','crash-restart-*.json','browser-live-*/receipt.json'))
    match = evaluate()
    summary = {'generated_at':generated,'tests':test_summary,'test_receipt':rel(test),'offline_attempts':len(rows),
        'invalid_accepted':sum(r['invalid_accepted'] for r in rows),'budget_violations':sum(r['budget_violation'] for r in rows),
        'model_attempts':len(calls),'model_status':dict(call_counts),'model_backends':dict(backends),
        'known_cli_estimate_usd':sum(known),'calls_with_estimates':len(known),'actual_account_charges':None,
        'live_original':{'finished':pilot1['finished'],'verified':pilot1['verified']},'live_validation':{'finished':pilot2['finished'],'verified':pilot2['verified']},
        'browser':rel(browser),'mcp':rel(mcp),'restart':rel(restart),'sdk':rel(sdk),'injection':rel(injection),
        'validation_directory':rel(validation),'browser_live':rel(browser_live),'crash_restart':rel(crash),'showcase':showcase,
        'actual_service_expenditure':0,'construction_usage':None,'public_testnet_executed':False,
        'artifact_revalidation': revalidated}
    write_json(DATA/'reports/summary.json',summary)
    lines=['# Selection experiment report','',f'Regenerated {generated} from `{folder.relative_to(ROOT)}`. {len(rows):,} attempted synthetic tasks.',
        '', 'All outcomes below are controlled offline simulation, not measurements of real models. CREDIT is non-monetary. Intervals use 30 seed replicates.', '',
        '| Scenario | Policy | Verified / attempted | Completion % (95% interval) | Credits | Credits / verified | Mean simulated ms | Deadline misses | Switches | Simulated regret |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in analysis['groups']:
        ci=g['completion_interval']; cp=g['cost_per_accepted_artifact']
        lines.append(f"| {g['scenario']} | {g['policy']} | {g['verified']}/{g['attempted']} | {100*g['completion_rate']:.1f} ({100*ci['lower']:.1f}, {100*ci['upper']:.1f}) | {g['cost']} | {cp:.3f} | {g['mean_latency_ms']:.1f} | {g['deadline_miss']} | {g['switch']} | {g['regret']:.2f} |")
    lines += ['', '## Paired differences against random', '', '| Scenario | Policy | Verified-rate difference, percentage points (95% interval) |','|---|---|---:|']
    for p in analysis['paired_differences']:
        d=p['verified_rate_difference'];lines.append(f"| {p['scenario']} | {p['policy']} | {100*d['mean']:+.1f} ({100*d['lower']:+.1f}, {100*d['upper']:+.1f}) |")
    lines += ['', f"Invalid artifacts accepted: {summary['invalid_accepted']}. Budget violations: {summary['budget_violations']}. Repeat charges: {sum(r['repeat_charge'] for r in rows)} in this single-charge simulation; independent payment fault tests are the evidence for actual retry behavior.",
        '', 'No single policy is presumed best. Cheap-sufficient and all-equivalent are explicit controls; a free provider can be the useful choice. Infrastructure failures remain in the attempted denominator. Conditional completion metrics, all counts and policy decisions are preserved in analysis.json and raw trials.',
        '', 'Regret uses the declared synthetic expected-utility oracle at each learner budget. Price and quality distributions are invented. Confidence intervals are normal approximations without multiplicity correction. See EXPERIMENT_PROTOCOL.md.']
    put('SELECTION_REPORT.md','\n'.join(lines))
    put('TEST_REPORT.md', f'''# Test report

Generated {generated}. Latest full run: **{test_summary}**.

Exact command, output, source manifest and recoverable source archive:
`{rel(test.parent)}`.

| Checks | Evidence |
|---|---|
| A2A SDK client → server; client → upstream SDK reference process | tests/test_http.py; {rel(validation)}/*wire.json |
| Durable deduplication, restart, principal isolation, cancellation races | tests/test_core.py, test_resume.py, test_adversarial.py |
| Quote negotiation, budget conservation, concurrent settlement, forged/expired terms | tests/test_payments.py |
| Lost response after real HTTP admission; reconcile without charging twice | tests/test_payments.py |
| Seller failure after payment; no poll charge, no paid fallback | tests/test_adversarial.py |
| Failed model switch, CLI-child cleanup, verifier failure after payment | tests/test_workflow_faults.py; injected subprocess faults, not live inference |
| Actual ledger process outage; free work continues; paid run resumes once | tests/test_workflow_faults.py; exact owned PID, preserved ledger |
| Three real quotes, measured feedback, bound approval, parent spans | tests/test_coordinator.py |
| Official x402 signing/verification and golden headers | tests/test_x402.py; {rel(sdk)} |
| Configured testnet adapter against wire stub, mainnet refusal | tests/test_x402.py; public execution not performed |
| Benchmark reproduction, denominator, feedback and private-feature controls | tests/test_benchmark.py |
| Boolean/count separation, malformed CSV refusal, blank records and quoted newlines | tests/test_verification.py |
| Retained experiment/live verdicts rechecked before headline regeneration | tests/test_reports.py; local_data/reports/summary.json |
| Consent, revocation, withheld fields, A2A introductions, adapter contracts | tests/test_extensions.py |
| Official MCP process handshake/tools and forbidden dispatch | {rel(mcp)} |
| Real Chrome submit, quote approval, dedup, CSV, desktop/mobile, logout | {rel(browser)} |
| Existing live artifact, traces and real usage displayed in Chrome | {rel(browser_live)} |
| All owned services stopped/restarted; original paid task and balances retained | {rel(restart)} |
| Actual owned provider SIGKILL, restart, durable artifact and no second charge | {rel(crash)} |
| One bounded live prompt-injection/canary probe | {rel(injection)} |

Historical failures are retained in earlier receipts and the startup snapshot. The original
live pilot failed its quality rubric, so its four completed tasks are not counted as verified.
No mock chain result is counted as settlement. Testnet wire tests and integration stubs are
explicitly separate from public-network or cross-project execution.

Browser tests require installed Chrome, run in a temporary repository-local profile, and
capture no authentication tokens. Every full test run uses new repository-local credentials,
ports and a separate simulator wallet, then verifies owned-process shutdown. It does not
reset or spend the demonstration wallet.
''')
    put('INTEROPERABILITY_REPORT.md', f'''# Interoperability report

Verified on {generated}; pinned A2A SDK 1.2.3, protocol 1.0, JSON-RPC + SSE.

| Direction / boundary | Actually exercised | Limit |
|---|---|---|
| Official SDK client → Exchange | Agent Card, SendMessage, GetTask, streaming artifact/status | Local HTTP only |
| Exchange client → separate upstream DefaultRequestHandler process | Structured send and immediate Message response | Project-authored harness around independently maintained SDK; not a deployed third-party peer |
| Exchange providers | Send/get/cancel/list, continuation, artifact integrity, scoped replay, version mismatch | Shared implementation; topology alone is not independent interoperability |
| x402 SDK 2.25.0 | v2 schema/headers, EIP-3009 signature, tamper rejection, payment identifier | Contract reads are explicit fixtures; no local-chain/public settlement |
| MCP SDK 2.3.0 | Real stdio initialization, list_tools, read-only calls | Receipt: `{rel(mcp)}`; no task/spending/disclosure tools |
| Continuum/Leo OS envelopes | Strict schema, stub sender → A2A, durable notification cursor, exact-preview approval → buyer HTTP | Both adapters are project-local stubs; neither real project connected or modified |

Evidence: `{rel(validation)}/sdk-client-wire.json`, `reference-server-wire.json`,
`{rel(sdk)}`, plus test receipts. Unsupported: push notifications, signed/extended cards,
gRPC, REST binding, arbitrary peer extensions, public ecosystem certification. Cursor replay
and quote contracts are namespaced application features. The upstream SDK serializer handles
required empty pagination fields; golden live checks assert those fields on actual HTTP responses.
''')
    put('PAYMENT_MODE_REPORT.md', f'''# Payment mode report

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
restart reuse the order and original task. Evidence: `{rel(crash)}`, `{rel(restart)}` and tests/test_payments.py.
The dashboard requires an explicit operator decision over an immutable preview before
authorization. Changed or expired terms cannot reuse that approval. CLI/API requests may
explicitly authorize simulator spending within deterministic caps. No agent grants UI consent.

Release is allowed before settlement. After admission, cancellation or bad delivery does not
refund the charge. Seller failure after payment is tested and reported as paid-but-not-useful.
There is no escrow, automatic refund, atomic fair exchange or on-chain reversal claim.

SDK cryptographic evidence: `{rel(sdk)}`. Negative controls include changed payee, amount,
nonce, expiry and network. A valid signature is not settlement. The public-testnet client
records a resource-server settlement response but does not claim independent chain confirmation.
An unresolved testnet response blocks automatic retry; operator reconciliation is required.

Testnet has no mainnet switch and no external wallet import path. Explicit repository-local
configuration must pin Base Sepolia, an exact public HTTPS IP endpoint with valid TLS,
asset, payee, integer amount cap and operation ID. General DNS endpoints are not supported.
`testnet-init` creates a fresh project-only account; funding/acquiring tokens is never automatic.
No testnet operation, funded-wallet access or real service payment occurred in this assignment.
Actual service expenditure: **0**. Model subscription/account charges remain unknown.
''')
    put('MATCHMAKING_REPORT.md', '# Synthetic introduction evaluation\n\n'+match['scope']+'.\n\n'+
        '| Policy | Proposals | Invented mutual acceptances | Constraint violations | Withheld-field leakage |\n|---|---:|---:|---:|---:|\n'+
        '\n'.join(f"| {k} | {v['proposed']} | {v['simulated_mutual_acceptance']} | {v['constraint_violations']} | {v['withheld_field_leakage']} |" for k,v in match['results'].items())+
        '\n\nRaw profiles, predeclared labels and metrics: `local_data/receipts/match-evaluation.json`. Per-field preview, purpose checks, owner-token bilateral consent and revocation are tested separately. These invented labels are not real consent, romantic compatibility or real-user outcomes.')
    put('MORNING_REPORT.md', morning(summary, test.parent, folder, pilots))
    location = receipt('implementation-report',summary,[str(folder.relative_to(ROOT)),rel(test),rel(browser),rel(browser_live),rel(mcp),rel(restart),rel(crash),'local_data/showcases/v1-live'],
        ['Public testnet not executed','Real cross-project endpoints not configured','Shared OS account; not production isolation'])
    return {**summary,'report_receipt':location}
