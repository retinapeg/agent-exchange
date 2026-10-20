# Security and boundaries

This is a local research implementation, not a production security claim. Tests establish
specific properties; they do not prove sandbox isolation, anonymity or legal compliance.

- Exact configured IP origins and ports; no redirects, environment proxies, wildcard
  private-network access or DNS rebinding path. Remote policy requires public HTTPS with
  certificate validation. General DNS endpoint configuration is deliberately unsupported.
- Per-receiver bearer credentials; task and artifact reads are principal-scoped. Observer
  credentials cannot dispatch. Dashboard uses same-origin checks, HttpOnly/SameSite cookies,
  server-enforced one-hour expiry, logout revocation, CSP and DOM `textContent` rendering.
  Task submission and approval require that operator session. The observer uses a separate
  operator client for those explicit actions; its read-only credential cannot approve.
  UI payments always require an exact-preview decision, and changed/expired terms fail closed.
- Credentials live only in ignored `local_data/config.json` (0600). Simulator authorization
  tokens are private ledger state and are excluded from public summaries and event logs.
  Receipt capture avoids request authentication headers. Treat the whole local data directory
  as private. Task history and model artifacts intentionally retain submitted synthetic input;
  this build is not a general personal-data ingestion or automatic redaction service.
- Models receive bounded structured input and output. Claude runs with tools disabled,
  strict empty MCP configuration, safe mode and no session persistence. Codex uses ephemeral
  read-only mode with shell, browser, apps, plugins and multi-agent features disabled.
  No arbitrary generated code or model-selected commands are executed. Existing CLI auth
  is reused; API-key environment fallback is stripped. No global configuration is changed.
- At most two concurrent model calls, 2,000 attempted calls across the project, a 120-second
  per-call deadline and bounded stdout/stderr. A shared repository-local budget and file
  locks apply across runtime overrides. Owned CLI process groups are terminated on timeout
  or cancellation, including children. Failed/uncertain calls are not automatically
  retried. A live source-injection probe used a non-secret canary and found no arbitrary
  tool use or leakage; that single observation is not a sandbox proof.
- All services share the local OS account. A compromised Python process could read other
  project credentials. Per-service filesystem/network sandboxing is not implemented.
- No public execution endpoint, recursive delegation service, automatic paid fallback,
  funded-wallet import, mainnet option, real outreach or other-project database access.
- Profile fields require explicit approval. Contact disclosure requires two independent
  owner tokens and two explicit consents through operator-only routes. Profiles are fictional
  and pseudonymous, not guaranteed anonymous. Revocation stops future local disclosure;
  it cannot erase copies already received. Sensitive matchmaking is out of scope.

Fault checks include simultaneous submissions, cross-principal reads, malicious cards,
identity/endpoint substitution, response redirects and size limits, artifact injection,
cancellation races, provider restart, unavailable registry, changed-content replay,
negotiation limits, authorization/settlement crashes, actual provider SIGKILL, lost responses, forged authorization,
budget caps, seller failure after payment, disk-error rollback and duplicate delivery.
Tests also inject verifier infrastructure failure after payment and model-switch/timeout
failure, check source truncation refusal, and reject cross-origin approval requests.

Remaining engineering for deployment: independently sandboxed service identities, external
identity provisioning, key rotation, remote DNS/TLS deployment, load and denial-of-service
limits, retention/deletion policy, third-party security review,
and independent chain confirmation for any testnet settlement. None is claimed completed.
