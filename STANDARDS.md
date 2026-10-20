# Standards and dependencies

Official references retrieved on 2026-10-20 UTC. Installed SDK source resolved concrete
interfaces where examples or versions differed. All dependencies are locked in `uv.lock`.

| Surface | Pinned implementation | Supported boundary |
|---|---|---|
| A2A | `a2a-sdk==1.2.3`, protocol 1.0 | JSON-RPC, SSE, Agent Cards, tasks/artifacts, send/get/cancel/subscribe/list |
| x402 | `x402[evm]==2.25.0`, wire v2 | Official models/headers, EIP-3009 signing and verification fixtures |
| MCP | `mcp==2.3.0` | Official `MCPServer`, stdio initialization and read-only tools |
| HTTP | FastAPI 0.150.0, Uvicorn 0.54.0, HTTPX 0.28.1 | Literal loopback by default |
| Browser verification | Playwright 1.64.0 | Installed Chrome, isolated local test profile |

Sources:

- [A2A specification](https://a2a-protocol.org/latest/specification/) and
  [Python SDK](https://a2a-protocol.org/latest/sdk/python/).
- [A2A SDK source](https://github.com/a2aproject/a2a-python).
- [x402 documentation](https://docs.x402.org/) and
  [payment-identifier extension](https://docs.x402.org/extensions/payment-identifier).
- [MCP specification](https://modelcontextprotocol.io/specification/2026-07-28).
  The installed MCP 2.x SDK uses `MCPServer`, snake_case Python attributes and
  camelCase wire aliases. Old `FastMCP` imports fail explicitly. The online Python
  migration page was unavailable to this session; installed source and live handshake
  establish the actual interface. Negotiated protocol version is recorded in MCP receipts.
- [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
  [CLI reference](https://learn.chatgpt.com/docs/cli/reference), and
  [Claude CLI reference](https://code.claude.com/docs/en/cli-reference).
- [Playwright browser channels](https://playwright.dev/python/docs/browsers).

No A2A 0.3 compatibility is enabled. Push notifications, signed/extended cards, gRPC,
HTTP/JSON REST binding and arbitrary external peer discovery are unsupported. Unsupported
operations and version mismatches are tested. Registry cards are unsigned local claims.

The x402 v2 headers are `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`,
encoded using official base64 helpers. Amounts in SDK requirements are decimal strings.
The `payment-identifier` extension uses official declaration/append helpers. `leo-sim-v1`
is a custom scheme with integer `CREDIT` and `leo:local`; it is not an on-chain standard.

Quotes (`leo.quote.v1`), integration envelopes (`leo.integration.v1`), cursor replay,
selection/reputation, consent and budgets are application features. Ordinary A2A peers
are not assumed to implement these extensions. A signature is not settlement; settlement
is not quality verification.
