# Agent Exchange: Consumer Matchmaking Alpha

The main product is now **human-to-human collaboration matching**, not the old agent observatory. Anyone with the web address can register, provide a short structured profile, approve precisely which fields to share, join the matching pool, and see at most one high-scoring partner. Both people must accept before contact information is revealed.

**What is real:** independent accounts, persisted profiles, reciprocal scoring, threshold eligibility, global one-to-one pairing, durable matches, opt-in contact reveal, privacy controls, web UI and a personal MCP draft-only bridge. No artificial model calls, tokens, physics questions, payment ledger, fake probability estimates, or developer credentials are involved in the real-user route.

## Local use (Mac)

Requires Python 3.12+ and `uv` (or Python with FastAPI, Uvicorn and NetworkX installed). Stop the legacy observatory first if it owns 8715: `./exchange.sh down`.

```sh
cd ~/Projects/agent-exchange
./consumer.sh serve
# Open http://127.0.0.1:8715
```

All consumer data are written to ignored `local_data/consumer.sqlite`. The original lab does not have to run, and nothing needs your `local_data/config.json` operator token.

To test the actual multi-person experience without storing fictional users alongside real profiles, run a **separate demo database**:

```sh
EXCHANGE_DEMO=1 ./consumer.sh seed-demo
EXCHANGE_DEMO=1 ./consumer.sh serve
# Open http://127.0.0.1:8715
```

The demo's homepage is explicitly labelled **SYNTHETIC DEMO** and displays the real saved match results of 20 fictional participants in 10 complementary pairs. Do not use it for real people.

## How joining works

1. Click **Join the network** and register with an email and password (10+ characters).
2. Ask your ChatGPT/Claude assistant to draft the six-field profile using **Copy AI prompt**, or type short tags manually. **Do not paste raw chats.** The UI also accepts the six-field JSON draft.
3. Choose what to share. Interests and goals are necessary; skills, working style and timezone are optional.
4. Read the preview, tick explicit consent and click **Approve and join the pool**.
5. Once there are 15 total approved participants, the backend waits briefly to collect simultaneous joins, scores compatible eligible pairs, and assigns each person **at most one** match above the configured threshold (default 75/100). If no match clears the threshold, they remain waiting. Subsequent arrivals can join new rounds.
6. See partner display name, your compatibility score and a few shared, approved reasons. Both participants must accept before either sees the other's email. Declining excludes that exact pair and returns both to the waiting pool. Deleting an account removes approved data and unassigns its partner.

**Scoring:** deterministic, interpretable similarity over approved interest tags (25%), goals (30%), complementary offers/seeks (25%), style (10%), and timezone (10%). Unshared fields score zero. The score is a **heuristic compatibility score, not a calibrated statistical probability**. Eligible graph edges are paired with a maximum-cardinality, then maximum-total-score matching algorithm. One person's individually top-scoring partner cannot always be assigned if that person is another participant's better global match. Match results are stable once proposed; late arrivals do not silently steal partners.

**Cohorts:** if 15 participants join, at most seven pairs can be formed, and at least one remains waiting. If two or more eligible people remain, later arrivals may permit another matching round. In production, each background loop uses a SQLite `BEGIN IMMEDIATE` transaction and `active_members.user_id` unique key to ensure no participant is simultaneously allocated twice, even if multiple requests/workers race.

## MCP (owner-scoped draft-only integration)

The MCP bridge is specifically for assistants that support **local stdio MCP**. It does not imply that arbitrary ChatGPT accounts can use custom write-capable connectors or that third-party apps can read ChatGPT memory.

1. Register at the web UI and open **Account, MCP integration and privacy controls**.
2. Create a secret API token. Copy it immediately, and keep it private.
3. Configure an MCP-capable desktop assistant to run `./consumer.sh mcp` with `AGENT_EXCHANGE_TOKEN` and `AGENT_EXCHANGE_URL=http://127.0.0.1:8715` in its environment. Example client configuration:

```json
{
  "mcpServers": {
    "agent-exchange": {
      "command": "/ABSOLUTE/PATH/agent-exchange/consumer.sh",
      "args": ["mcp"],
      "env": {
        "AGENT_EXCHANGE_URL": "http://127.0.0.1:8715",
        "AGENT_EXCHANGE_TOKEN": "PERSONAL_SECRET_TOKEN"
      }
    }
  }
}
```

Tools: `get_profile_schema`, `preview_profile`, `stage_profile`, `my_match_status`. An agent can stage only a **draft**, not consent, join, accept a match, read other profiles, see unreleased emails, or delete an account. Human approval must happen in the browser. Tokens can be revoked in the browser.

For a genuine remote hosted MCP integration suitable for ChatGPT connectors, a provider-supported OAuth flow and current platform-specific integration requirements remain future work. **Do not publish a shared bearer token as a public MCP server.**

## Production hosting

`Dockerfile.consumer` and `render.yaml` build a self-contained consumer app, listen on `0.0.0.0:8715` behind the host's HTTPS proxy, and store data on a durable persistent disk. The Render Blueprint declares a disk and requires `EXCHANGE_PUBLIC_ORIGIN`, e.g. `https://your-service.onrender.com`. Set `EXCHANGE_SECURE_COOKIES=1` for HTTPS. Run a single application instance with persistent storage in this initial SQLite alpha. Existing lab/observer infrastructure is **not** required. Health check is `/health`.

**Before inviting the general public:** add email address verification/invites and authentication rate limits, security review, data retention/backup process, privacy notice and independent security testing. The current build is suitable for a **controlled alpha**, not unrestricted public registration. Until hosting and these safeguards are set up, `127.0.0.1` is accessible only on the local machine, not to 15 remote people.

## Local verification

```sh
python -m pytest -q tests/test_consumer.py
```

The tests exercise 20 distinct concurrent participants, persisted pairs, threshold failures, reciprocal consent, decline/requeue, data deletion, owner isolation and web endpoints. Demo data and the real matching pool are isolated by database filename.
