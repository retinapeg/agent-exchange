# AGENT EXCHANGE: INTEROPERABLE AGENTS, DELEGATION AND PAYMENT EXPERIMENTS

## 0. Mission and working contract

Build Agent Exchange inside ~/Projects/agent-exchange: a working network
layer through which independent agents discover services, exchange
messages, delegate tasks, negotiate constraints, obtain verifiable
artifacts and optionally pay through an HTTP 402/x402 flow.

This is not another chatbot, a set of Python functions pretending to be
remote agents, or a payment button attached to a mock dashboard.

Build separately running services communicating over real local HTTP,
with durable state, observable failures and reproducible experiments.

Leo OS is the owner's command centre. Continuum is the persistent-agent
research runtime. Agent Exchange owns discovery, interoperability,
delegation and optional service commerce. Do not rebuild or modify the
other projects.

Work autonomously through implementation, integration, evaluation, review
and repair. Use substantial compute for useful experiments and adversarial
checks, not unbounded recursive agent conversations.

Make reversible implementation choices without interrupting me.
Queue genuine permission blockers while continuing independent work.


## 1. Scope, repository safety and permissions

Inspect the current folder, local instructions and Git status before
changes. If empty, initialise only this project. If files exist, preserve
useful work and make a recoverable local snapshot including untracked
source.

Do not delete or overwrite an existing implementation merely because
this prompt describes a new project.

Only this repository is writable. No edits, deletions, copying or
absorption of code from Leo OS, Continuum or other personal repositories
without consent.

Public protocol SDKs are dependencies, not permission to merge my other
projects. Keep licence and attribution records.

Use one source-code writer, repository-local environments/caches, bounded
worker concurrency and explicit process ownership. No worktrees, branches,
commits, pushes, global settings changes, public deployment or background
login service installation without approval.

Public documentation, necessary package downloads, local HTTP fixtures
and approved existing model-CLI authentication are allowed.

No real-money payments, mainnet transactions, funded wallet access,
third-party outreach or scraping private data. Synthetic peer messages
over local HTTP are allowed.

Build a process lock and never kill another process by a broad name match.
Check ports rather than assuming no other project is running.


## 2. Standards-first implementation

Read the current official A2A specification and compatible SDK
documentation. Choose and pin a published protocol version and transport
supported by the installed SDK.

Record versions, source URLs and retrieval dates in STANDARDS.md.
Do not mix message fields or methods from different versions.

Implement real Agent Cards, declared capabilities, messages, task
lifecycle, artifacts, status retrieval, cancellation and streaming where
supported by the chosen binding.

Advertise only capabilities that work. Test version mismatch and
unsupported capabilities explicitly.

Use A2A for external agent collaboration. Keep MCP as a separate
tool-facing integration; do not call an arbitrary HTTP endpoint “MCP”
or rename internal JSON “A2A”.

Use the official x402 SDK and its matching wire formats for payment mode.
Resolve inconsistencies between examples, documentation and SDK versions
before claiming compliance. Record what was actually verified.

Quotes, budget policies, reputation and this marketplace's negotiation
rules are application features unless a cited standard explicitly defines
them. Namespace custom extensions.

Do not imply every A2A peer implements payment negotiation or our
quote schema.


## 3. Required service topology

Deliver a buyer/coordinator, a registry, at least three separately
addressable provider instances and an observer dashboard.

Each provider has its own identity, task store and configurable behaviour.
The buyer must not access provider databases or private evaluator data.

The providers must communicate across real sockets. Unit tests may use
in-process clients, but the end-to-end demonstration must launch separate
processes and capture actual requests/responses.

Keep localhost as the default network boundary.

Use useful service types, for example:

- Extract structured requirements from a fictional job brief with quoted
  evidence.

- Audit a synthetic CSV for missingness, duplicates, invalid ranges and
  summary statistics.

- Verify a submitted structured artifact against its source and a
  declared rubric.

At least one task must require clarification and subsequent continuation.
At least one must stream progress and return an artifact.
At least one must fail and recover safely.

Do not make the entire system a hard-coded double(x) example.

Providers may share implementation libraries, but separate process
communication does not prove independent implementation
interoperability. Test that distinction separately.


## 4. Discovery, identity and trust

Implement Agent Card retrieval, capability search, schema validation,
freshness, health and version compatibility.

Start from an explicit registry and configured peer URLs; do not scan
the public internet.

Registry listings are claims, not proof of identity or quality. Local
development identities must be visibly labelled as such.

Use per-peer authentication and principal-scoped task access. Do not
accept self-asserted high ratings as verified reputation.

For remote-ready configuration require HTTPS and validated credentials.
Treat cards, descriptions, messages and artifact metadata as untrusted
content.

A signed card may establish provenance under a trust policy; it does not
establish that the agent is honest.

Protect discovery and artifact fetching against SSRF, redirects to
disallowed destinations, oversized responses and internal metadata
endpoints.

Local test mode may allow exact loopback origins, ports and schemes in
configuration; it must not create a general private-network exception.

Show which provider properties are declared, measured, stale or unknown.


## 5. Task and artifact lifecycle

Implement the selected A2A lifecycle faithfully, including input-required
and failure cases where applicable.

Keep payment, execution and verification states separately represented
rather than inventing new core A2A states.

Persist task IDs, context/message IDs, trace IDs, input versions, source
principal, cancellation state and artifact references.

Make application-level submission deduplication explicit and testable;
do not assume the protocol guarantees exactly-once submission.

For a repeated principal/idempotency-key pair with identical content,
return the original operation. Reject reuse with changed content.

Make concurrent duplicates safe with database constraints and
transactions, not a check followed by an unprotected insert.

Reconnect streaming clients using documented transport capabilities.
If replay is an application extension, label it. Deduplicate replayed
events and support a status-query fallback.

Cancellation must stop future local work where possible and report
effects that already happened.

Artifacts need media type, size, checksum, provenance and access controls.
Never execute downloaded content automatically.

A declared “completed” task is not automatically a verified result.
The buyer's independent verifier determines acceptance under a
predeclared rule.


## 6. Negotiation and non-payment collaboration

Implement a typed application-level quote:

- Quote ID and provider.
- Task/input digest.
- Service and declared deliverable.
- Price/asset/network, if applicable.
- Expiry and deadline.
- Verification policy.
- Cancellation terms.

Support bounded negotiation:

request
-> clarification or offer
-> accept/reject/counteroffer
-> final agreed quote.

Limit rounds and preserve a transcript. The LLM may propose terms;
deterministic policy validates scope, budgets and required approvals.

Support genuinely free tasks. Also support explicitly labelled
non-monetary credits in the local simulator, but do not describe those
as x402 settlement.

Communication and collaboration must work without payment infrastructure.

Do not assume a quote in a message is an enforceable contract or that an
LLM can grant wallet authority.

If parameters change, issue a new quote and require renewed acceptance.
No silent substitutions of recipient, asset, task or amount.


## 7. x402 payment modes

Implement separate modes with conspicuous status:

A. Free service:
   Real A2A traffic and no payment.

B. Local payment simulator:
   Real HTTP challenge/retry flow with an explicit simulator ledger;
   no blockchain settlement claim.

C. SDK-backed test integration:
   Official x402 types, signing and verification tested against
   appropriate fixtures or a local test chain.

D. Public testnet integration:
   Implemented but only executed with explicit operator configuration
   and test-only credentials.

Mainnet and real-money execution are out of scope. A boolean hidden in
the UI must not be able to enable mainnet.

Never import a user's existing funded wallet. Do not acquire tokens,
pay gas or transmit wallet secrets on the assumption that compute
is unlimited.

The payment flow must distinguish:

quote
-> payment authorisation
-> verification
-> settlement
-> resource delivery
-> independent quality verification.

A 402 response is not a payment.
A valid signature is not settlement.
Settlement is not proof that the service produced correct work.

Use exact SDK-supported headers and encodings for the pinned version,
with golden-wire tests.

A custom simulated scheme must have a clearly separate name and must
not be advertised as a standard on-chain scheme.


## 8. Retry, settlement and budget correctness

Implement immutable order/task references, quote binding, expiry checks,
recipient/asset/network validation, nonces or the scheme's replay
mechanism, idempotency keys and durable payment receipts.

Use atomic integer monetary units or explicit decimal arithmetic with
asset precision. Never floats for balances.

Separate reserved, authorised, settled, failed, released and
outcome-unknown amounts. In a simulator, enforce ledger conservation
and non-negative available balances.

Use the SDK's payment-identifier extension when compatible, plus
application-level binding and access control.

An idempotency key is not authentication, and a cached artifact must not
be retrievable by a different principal merely guessing that key.

Test:

- Crash after authorisation.
- Crash after settlement but before local commit.
- Lost responses.
- Concurrent retries.
- Expired quote.
- Wrong payee.
- Forged receipt.
- Duplicate delivery.

When settlement is uncertain, reconcile before authorising a new payment.
Never use a new nonce to “retry” an unresolved payment blindly.

Document charge timing for long-running A2A work. For example, a
fixed-price admitted task may produce a task ticket whose subsequent
status checks and artifact retrieval are not charged again.

Do not charge for every poll or SSE reconnect.

State what cancellation and failure do to payment. Do not claim automatic
refunds, escrow, atomic fair exchange or reversal unless implemented and
tested.

A payment can succeed while useful delivery fails; preserve and report
that state.

Budget decisions belong to a deterministic policy engine. Separate
per-task, per-run, per-peer and global spending caps.

Real expenditure remains zero during this assignment; simulation balances
and test assets are different resources.


## 9. Genuine model-backed agents

Implement fixture and live model providers separately. Use installed
Codex/Claude CLIs and existing supported authentication when available.

Inspect actual help/docs and probe exact model identifiers. Do not invent
Astra/Fable API identifiers, hide working logins behind fresh config homes,
or switch to a new paid API route.

A live buyer should translate a normal request into a structured task,
identify missing requirements, choose among declared capabilities and
interpret verified results.

At least one live provider should process a nontrivial document or dataset
request. If available, run a paired exchange in which both buyer and seller
use actual models.

Models propose structured messages and decisions. Deterministic code owns
network access, payment policy, task state, parsing, artifact storage and
verification.

Do not expose arbitrary shell or wallet signing to model text.

Capture actual streaming events, model identity, usage and failures.
Use per-call deadlines, bounded output, retries and owned-process cleanup.

Never count a fixture response as a real model interaction.

If credentials or model access block the live path, keep implementing
protocol integration, record the precise blocker, and mark live behaviour
unverified.

Do not build deliberately nonfunctional adapters and declare the product
complete.


## 10. Agent/provider selection experiments

Implement and compare inspectable policies:

- Random eligible provider.
- Cheapest eligible provider.
- Capability-filtered fixed provider.
- Reliability-aware heuristic.
- An online learning policy, only after the basics work.

Construct simulated providers with controlled price, latency, quality,
outage and misleading-advertisement patterns.

Do not assign those synthetic characteristics to real models as measured
facts.

Use meaningful verifiable tasks and the same frozen workload across
policies. Keep private outcome distributions and oracle data inaccessible
to buyer agents.

Include expensive-but-better, cheap-and-sufficient, all-equivalent,
unreliable-cheap and nonstationary cases.

For controlled simulation, define whether outcome randomness is
task/provider-based or attempt-based and use common random numbers
where appropriate.

For real providers, repeated requests are fresh trials, not the same
hidden random outcome.

Measure:

- Verified completion.
- Total cost.
- Cost per accepted artifact.
- Latency and deadline misses.
- Invalid artifacts accepted.
- Repeat charges.
- Budget violations.
- Provider-switch count.
- Simulated regret against a clearly defined oracle.

Real-world regret without observed counterfactuals is not available.

Log candidate sets, selection features, policy version and actual
selection probability when the policy supplies one.

Do not infer causal provider superiority from selection-biased operational
logs. A learned policy requires suitable feedback, not just a dashboard
of counts.


## 11. Evaluation campaign and error taxonomy

Freeze scenarios, split, acceptance rules and analysis before scored
inference.

Run a small development pilot, then a substantial offline suite and a
declared live pilot when authorised credentials work.

A suitable offline target is at least 30 seeds per scenario family across
four selection policies. Include repetitions, failure injection and
counterexamples.

Select live sample sizes before scored runs and report the completed
fraction if the run is interrupted.

Use generous finite provider-call and wall-clock budgets, configurable
concurrency and checkpointed progress.

Start with no more than two simultaneous model calls and a 2,000-call
safety ceiling for this project. Do not treat this ceiling as a requirement
to waste capacity.

Respect account limits shared with other projects.

Separate transport, authentication, version, schema, provider,
task-quality, verification, payment, storage and policy failures.

Track attempted, accepted, completed, verified and abandoned tasks with
distinct denominators.

Report paired differences and scenario-level uncertainty intervals.
Keep infrastructure failures in the overall outcome accounting, with
conditional results separately labelled.

Show cost-quality trade-offs and cases where a simple/free provider wins.

All headline numbers must regenerate from preserved raw artifacts.
Fixed random seeds support simulated reproduction, not bit-identical
fresh model outputs.


## 12. Interoperability evidence

Test the server with an independently constructed client from the pinned
official A2A SDK, not only the custom client that shares our serializers.

Test our client against a suitable independently implemented local
reference peer where practical.

Record each direction, SDK version, transport and capability actually
tested.

A three-agent demo sharing one broken serializer is not proof of
ecosystem interoperability.

Validate x402 payloads against the pinned official schemas or SDK
reference fixtures.

Distinguish wire/schema validation, cryptographic verification,
local-chain settlement and public-testnet settlement.

Do not collapse them into one green “payments work” badge.

If an SDK capability is unavailable, report the supported subset and
precise incompatibility.

Do not implement a private approximation and label it
standard-compliant.


## 13. Dashboard, traces and honest costs

Build a usable responsive dashboard showing discovered agents, identities,
capabilities, health, outstanding quotes, task messages, streaming
progress, artifacts, verifier results, permission requests and
payment states.

Provide a real timeline/network view based on observed events.
Show who talked to whom and which operation produced each result.
“Thinking” animations are not observability.

Record schema version, event/trace/span/parent IDs, peer IDs,
task/order/quote IDs, attempt, protocol version, provider/model,
timestamps, input/output hashes, usage, latency, retry reason and
final disposition.

Redact secrets and private content before persistence.

Separate construction-build receipts, model-inference estimates, service
payment amounts, test/simulator balances and actual observed charges.

Store price provenance, rate timestamp, currency and cost formula version.
Handle cache categories without double-counting.

Unknown usage or cost stays unknown, never zero.

Every build milestone and evaluation run needs a receipt linking source
manifest, checks executed, actual results, logs, artifacts and known
defects.

Do not fabricate build-model usage when parent-session telemetry
is unavailable.


## 14. Developer matchmaking extension

Once the task exchange works, implement a small synthetic
developer-introduction application using the same protocol.

This is the first step towards the later agent-mediated matchmaking
idea, not a finished dating product.

Use fictional profiles with user-approved fields:

- Technical interests.
- Collaboration goals.
- Availability.
- Preferred communication.
- Coarse location/timezone.

Each agent sees only the approved outward-facing profile, not a raw
personal conversation history.

Implement disclosure preview, per-field approval, purpose restriction,
revocation and separate bilateral consent before contact details are
exchanged.

Agents may propose introductions but cannot consent on behalf of users.

Use opaque local IDs and describe the result as pseudonymous and
data-minimised, not guaranteed anonymous.

Do not claim embeddings or hashed interests prevent re-identification.
Do not import real ChatGPT exports or infer sensitive personal traits.

Compare the synthetic matching policy with a simple tag-overlap baseline
using predefined mutual-interest labels.

Measure constraint violations, withheld-field leakage and introduction
acceptance in the simulation.

Do not claim real romantic compatibility or real-user outcomes from
invented profiles.

Keep dating and sensitive-data deployment outside this build. Document
remaining privacy engineering and assessment requirements without
asserting legal compliance.


## 15. Future integration without merging repositories

Define local adapters for Continuum as a buyer and Leo OS as an
observer/approval interface.

Do not connect to their real databases or modify their code during
this assignment.

Use this project-local envelope, explicitly NOT the A2A wire format:

    schema_version: leo.integration.v1
    message_id, trace_id, correlation_id, causation_id
    source, target, kind, created_at, deadline_at
    idempotency_key, payload

Use RFC3339 UTC timestamps, nullable causation/deadline fields,
stable IDs and a strict JSON schema.

Initial kinds:
    task.requested
    task.progress
    task.completed
    task.failed
    task.cancel.requested
    task.cancelled
    approval.requested

Persist receiving cursors and deduplicate by source plus message ID;
reject changed-content reuse.

Map the integration envelope to real A2A operations at the adapter
boundary.

Add contract fixtures and stub-based integration tests. Label stub tests
as such. Actual cross-project integration waits for approved endpoint
configuration.

After the core is verified, expose selected discovery/status operations
through a real MCP server using a supported SDK.

Task dispatch, spending and disclosure still need deterministic
authorisation even when invoked through MCP.


## 16. Security and fault injection

Test malicious cards, forged agent identity, prompt injection in
task/artifact text, confused-deputy requests, replay, cross-principal task
access, path traversal, redirects, oversized payloads, runaway negotiation
and cyclic delegation.

Test seller failure after payment, lost settlement response, buyer
restart, registry outage, disconnection during streaming, verifier failure,
cancellation races, model-switch failure and simultaneous duplicate
submissions.

An agent must not purchase a paid alternative because free service failed
unless the owner's policy permits it.

A paid receipt must not bypass task authorisation or artifact
verification. Reviews cannot override failed deterministic checks.

Use local authentication, same-origin dashboard controls, explicit network
allowlists and least-privilege credentials.

No public raw execution endpoint. Keep signing authority outside
model context.

Do not execute arbitrary generated code unless independently sandboxed
without secrets; ordinary process separation is insufficient.


## 17. Delivery order and stopping criteria

Maintain an execution checklist and build vertically:

1. Pinned protocols, registry and real two-process task exchange.

2. Three providers, artifacts, streaming, clarification and cancellation.

3. Durable task state, retries and independent verification.

4. Live-model buyer/provider path when authentication permits.

5. Local payment flow, SDK conformance and failure accounting.

6. Policy comparisons, adversarial tests and analytical reports.

7. Synthetic developer matchmaking and optional MCP bridge.

Do not stop at the first mock. Finish the highest-priority functioning
slices before expanding optional features.

If permissions block a capability, mark that slice blocked and continue
other accepted work.

Deliver:

- README.md
- STANDARDS.md
- ARCHITECTURE.md
- SECURITY.md
- EXPERIMENT_PROTOCOL.md
- INTEROPERABILITY_REPORT.md
- PAYMENT_MODE_REPORT.md
- TEST_REPORT.md
- MORNING_REPORT.md
- Integration fixtures
- Reproducible analysis

Provide one-command startup/shutdown for processes owned by this project,
health/status commands, offline demos, live preflight, benchmark/resume
commands and actual browser smoke-test evidence.

A restart must preserve task/payment state and not repeat a charge.

The README should explain the problem in plain language, show the working
flow, publish reproducible numbers and state the supported
protocol/payment modes.

No fabricated badges, real-world customers, mainnet settlement, anonymity,
decentralisation or production-readiness claims.

Conclude with completed checks, unsupported capabilities, actual live
calls, payment mode, known defects and exact pending approvals.

Stop at verified completion or the declared deadline/budget.
Leave changes uncommitted and never auto-deploy.

Official implementation references to check:

https://a2a-protocol.org/latest/specification/
https://a2a-protocol.org/latest/sdk/
https://docs.x402.org/
https://docs.x402.org/extensions/payment-identifier
https://modelcontextprotocol.io/specification/latest
https://developers.openai.com/codex/noninteractive/
https://developers.openai.com/codex/auth/
https://code.claude.com/docs/en/cli-reference