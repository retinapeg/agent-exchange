# Interoperability report

Verified on 2026-10-20T01:31:48.185Z; pinned A2A SDK 1.2.3, protocol 1.0, JSON-RPC + SSE.

| Direction / boundary | Actually exercised | Limit |
|---|---|---|
| Official SDK client → Exchange | Agent Card, SendMessage, GetTask, streaming artifact/status | Local HTTP only |
| Exchange client → separate upstream DefaultRequestHandler process | Structured send and immediate Message response | Project-authored harness around independently maintained SDK; not a deployed third-party peer |
| Exchange providers | Send/get/cancel/list, continuation, artifact integrity, scoped replay, version mismatch | Shared implementation; topology alone is not independent interoperability |
| x402 SDK 2.25.0 | v2 schema/headers, EIP-3009 signature, tamper rejection, payment identifier | Contract reads are explicit fixtures; no local-chain/public settlement |
| MCP SDK 2.3.0 | Real stdio initialization, list_tools, read-only calls | Receipt: `local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/mcp-stdio-79fe1017-120e-4ee1-8cab-0aacc66c8112.json`; no task/spending/disclosure tools |
| Continuum/Leo OS envelopes | Strict schema, stub sender → A2A, durable notification cursor, exact-preview approval → buyer HTTP | Both adapters are project-local stubs; neither real project connected or modified |

Evidence: `local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/sdk-client-wire.json`, `reference-server-wire.json`,
`local_data/validation-runs/2de87239-5ddd-4c7a-bd3a-36a7ce29a66b/receipts/x402-sdk-0e17362a-2a73-4e0f-b504-1439daed01df.json`, plus test receipts. Unsupported: push notifications, signed/extended cards,
gRPC, REST binding, arbitrary peer extensions, public ecosystem certification. Cursor replay
and quote contracts are namespaced application features. The upstream SDK serializer handles
required empty pagination fields; golden live checks assert those fields on actual HTTP responses.
