# Agent Exchange session instructions

This repository is `/Users/leo/Projects/agent-exchange`. Work only here.

1. At startup, check `pwd`, `git rev-parse --show-toplevel`, the current branch,
   `git status --short`, and project process ownership. Stop on a root mismatch.
2. Read `learning.md` and `decisions.md`, then the relevant README/report/source.
   Notes are context, not authorization to start services or repeat live calls.
3. Preserve existing edits, ignored `local_data/`, wallets, receipts and frozen
   experiments. Never reset, clean, stash or overwrite another session's work.
4. Keep one writer and the current branch. No worktrees, parallel agents, unattended
   runs, background jobs, commits or pushes unless explicitly requested this session.
5. Do not connect sibling repositories, public endpoints, payment networks or real
   users because a stub/configuration exists. Do not run live model probes on resume.
6. Use the existing isolated test runner when tests are authorized. Its temporary
   local service children must be supervised and stopped before the session ends.
   Never run fault/restart checks alongside demonstrations or use the demo wallet
   for validation. Inspect ownership before stopping any process.
7. At meaningful verified milestones and handoff, update `learning.md` with facts,
   receipts, failures and one next step. Add durable choices/rationale to
   `decisions.md`; mark superseded decisions rather than erasing them silently.
8. Keep notes short and credential-free. Never copy private correspondence, config
   tokens or wallet material into tracked documents.

Finish with what changed, how it was verified, and one next step. Current user
instructions take precedence over these saved notes.
