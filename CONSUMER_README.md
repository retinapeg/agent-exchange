# Agent Exchange: Consumer Matchmaking Alpha

The main product is now **human-to-human collaboration matching**, not the old agent observatory. Invited alpha participants register, approve a short AI-drafted summary, and join the shared matchmaking pool. Matching starts with **two people**, not fifteen. A qualifying match may expose each participant's **explicitly opted-in LinkedIn link immediately**. Email remains private until both parties accept.

**What is real:** independent accounts, persisted profiles, reciprocal scoring, threshold eligibility, global one-to-one pairing, durable matches, participant-authorised LinkedIn contact reveal, reciprocal email approval, privacy controls, web UI and a personal MCP draft-only bridge. No artificial model calls, tokens, physics questions, payment ledger, fake probability estimates, or developer credentials are involved in the real-user route.

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

1. Click **Join the pool** and register with an email and password (10+ characters).
2. Ask your ChatGPT/Claude assistant to draft the six-field profile using **Copy AI prompt**, or type short tags manually. **Do not paste raw chats.** The UI also accepts the six-field JSON draft.
3. Choose what to share. Interests and goals are necessary; skills, working style and timezone are optional.
4. Read the preview, tick explicit consent and click **Approve and join the pool**.
5. Once two approved participants have joined, the backend waits briefly for simultaneous joins, scores eligible pairings, and assigns each person **at most one** qualifying match above the configured threshold (default 75/100). If only two people are present and they score below 75, **both still see the same score and collaboration ideas**, without being assigned an official match. If no match clears the threshold, they remain waiting. Subsequent arrivals can join new rounds.
6. Both participants see the same compatibility score and specific ideas for working together. When a pair clears the threshold, an in-app “You've got a match!” message displays the person's name and any **LinkedIn profile they expressly opted to share**. Both must accept before revealing email. A declined pair is requeued and won't be paired again. Declining excludes that exact pair and returns both to the waiting pool. Deleting an account removes approved data and unassigns its partner.

**Scoring:** deterministic, interpretable similarity over approved interest tags (25%), goals (30%), complementary offers/seeks (25%), style (10%), and timezone (10%). Unshared fields score zero. The score is a **heuristic compatibility score, not a calibrated statistical probability**. Eligible graph edges are paired with a maximum-cardinality, then maximum-total-score matching algorithm. One person's individually top-scoring partner cannot always be assigned if that person is another participant's better global match. Match results are stable once proposed; late arrivals do not silently steal partners.

**Cohorts:** if 15 participants join, at most seven exclusive pairs can be formed in a round. One person remains available for the next join. If two or more eligible people remain, later arrivals may permit another matching round. In production, each background loop uses a SQLite `BEGIN IMMEDIATE` transaction and `active_members.user_id` unique key to ensure no participant is simultaneously allocated twice, even if multiple requests/workers race.

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

## Friends-only consent rule

Each invitee is a **voluntary participant**, not an arbitrary LinkedIn member. They approve the AI-derived context used for matching and may separately opt into showing their self-supplied LinkedIn URL to a qualifying partner. Consent here governs information released by Agent Exchange. It does **not** grant an outside app technical access to all prior ChatGPT conversations. Raw-chat ingestion and public LinkedIn directory searching are not part of this alpha.

The in-app announcement currently appears when a participant refreshes or polls for their match. Automatic email delivery has **not** been deployed. The original consumer product still needs a supported ChatGPT/MCP connection to avoid the copy/paste context fallback.

## Production hosting

`Dockerfile.consumer` and `render.yaml` build a self-contained consumer app, listen on `0.0.0.0:8715` behind the host's HTTPS proxy, and store data on a durable persistent disk. The Render Blueprint declares a disk and requires `EXCHANGE_PUBLIC_ORIGIN`, e.g. `https://your-service.onrender.com`. Set `EXCHANGE_SECURE_COOKIES=1` for HTTPS. Run a single application instance with persistent storage in this initial SQLite alpha. Existing lab/observer infrastructure is **not** required. Health check is `/health`.

**Before inviting the general public:** add email address verification/invites and authentication rate limits, security review, data retention/backup process, privacy notice and independent security testing. The current build is suitable for a **controlled alpha**, not unrestricted public registration. Until hosting and these safeguards are set up, `127.0.0.1` is accessible only on the local machine, not to 15 remote people.

## Local verification

```sh
python -m pytest -q tests/test_consumer.py
```

The tests exercise 20 distinct concurrent participants, persisted pairs, threshold failures, reciprocal consent, decline/requeue, data deletion, owner isolation and web endpoints. Demo data and the real matching pool are isolated by database filename.
