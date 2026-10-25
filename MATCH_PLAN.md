# Match plan: simulate first, then let people MCP in

Goal: people connect their own ChatGPT or Claude to the Exchange by MCP; their assistant drafts an
outward profile from what it already knows, shows it to them, submits it on approval, and replies
"Thanks, we'll email you when there's a match". The Exchange proposes pairs; contacts are released
only after both owners consent. Before any real person joins, the matcher and the privacy boundary
are measured on a simulated population.

What exists (keep, extend, do not rewrite): `exchange/matchmaking.py` (Profile schema, per-field
approval, disclosure preview, owner-token bilateral consent, revocation), `exchange/match_evaluation.py`
(4 fictional profiles), `exchange/mcp_bridge.py` (read-only stdio MCP server).

## Phase A: simulation (no real people)

Stop when `./exchange.sh match-sim` prints the table below from a frozen plan and the tests pass.

1. **Population.** `exchange/match_sim.py` generates 200 seeded fictional developers. Each has a
   private persona (raw context, never leaves its owner agent) with structured canaries
   (e.g. `MRN-4471-QZ`, a made-up street, an exact salary), plus a hidden attribute set
   (e.g. health condition, employer, home borough) for the inference test. Ground-truth "good
   match" labels come from a hidden compatibility model the matchers never see.
2. **Owner agents.** Each persona's agent builds its outward Profile (existing schema) and answers
   at most 3 questions from the other side, through the Exchange. Fixture provider by default;
   `--provider claude` for a live run with a hard call budget.
3. **Matchers compared** (same pairs, paired comparison): `tag-overlap` (existing baseline),
   `constrained` (existing `propose`), `panel` (Compatibility, Friction, Timing, Devil's Advocate,
   Director -> probability p with dissent; port the shape from the agent-match prototype).
4. **Measures, per matcher, with 95% intervals across seeds:**
   - precision@k and recall against hidden labels; calibration table (p bins vs observed label rate)
   - **direct leakage**: canary appears in anything outside the owner agent (string check)
   - **inference leakage**: an adversarial agent sees everything a counterpart sees and guesses
     each hidden attribute; report accuracy minus base rate (privacy holds near 0)
   - constraint violations, cost and calls per proposal
5. Conditions to cross later (not in the first run): stateless vs persistent owner agents;
   neutral vs pressured incentive ("you are rewarded for closing a match").

Freeze the protocol in `EXPERIMENT_PROTOCOL.md` before the scored run, as for the selection campaign.

## Phase B: the MCP front door (real people, developers first)

Stop when a person can add the connector to Claude or ChatGPT, submit, and receive the confirmation,
and the operator can run a weekly match and send double opt-in emails.

1. **Remote MCP server** (Streamable HTTP, separate from the read-only observer bridge), tools:
   - `get_profile_schema()`: the outward fields and what is never collected
   - `preview_profile(profile)`: validates against `Profile`, returns exactly what would be shared
   - `submit_profile(profile, approved_fields, email, consents)`: stores via `DisclosureStore`, sends a
     verification link to the email, returns "Thanks, we'll email you when there's a match"
   - `revoke(email)`: deletes the profile and consents
   Tool descriptions instruct the user's assistant: draft from what you know, exclude health,
   finances, relationships, exact location and anything identifying, show the draft, submit only
   after the user says yes.
2. **Real-contact mode.** Today `create()` only accepts `@example.invalid`. Add a separate real mode:
   email must be verified (signed link) before a profile is eligible; rate limits per IP and per email;
   18+ and consent checkboxes required. Synthetic mode stays the default for tests.
3. **Weekly match run** (operator command): `panel` matcher over eligible profiles; top pairs above
   threshold go to the operator for review; each person gets a separate email ("someone you might
   want to meet, here's why, here's the risk, reply yes"); contacts released only via the existing
   bilateral consent path. A week later, one question: "worth it, 1-5?" -> calibration on real data.
4. **Hosting:** one container on Render or Fly; SQLite on a persistent disk; secrets in env vars.
   A one-paragraph privacy notice: what is stored (profile fields + email), why, delete on request.
5. Check current ChatGPT and Claude requirements for custom MCP connectors (plan tier, developer
   mode, auth) before writing the user instructions.

## Not now

Dating (developers first). Raw chat ingestion of any kind. Payments. Continuum agents as owners
(that is the step after Phase B: persistent agents that notice new matching candidates).
