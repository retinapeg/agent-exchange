# Unattended Agent Exchange run

Prepared for the installed `/opt/homebrew/bin/codex` version **0.163.0**.
`BUILD_SPEC.md` is the latest conversation attachment, `Pasted text(3).txt`,
copied byte for byte: 24,447 bytes; SHA-256
`ec0415d07e8e138c5d2168dd5dcb7e2ae11c3f8df59ed760aa19de68f1349af3`.
Existing source was untracked on `main`, with no commits. Setup changed no
existing source or global configuration. This preparation does not run the build.

## Run once

Exit any existing Codex/Claude writer for this repository first. Do not start
another writer or edit the project in another chat while the run is active.
The lock prevents concurrent uses of this launcher; process inspection also
rejects an existing Codex/Claude/Aider process whose working directory is this
repository. Shared desktop sessions and arbitrary editors are not fully detectable.

```sh
cd "$HOME/Projects/agent-exchange" || exit 1
/usr/bin/caffeinate -i .venv/bin/python run_codex_overnight.py --hours 8
```

This stays in the foreground without interactive approval questions. Keep this
terminal open and the Mac plugged in; do not close a laptop lid. Ctrl-C interrupts
the owned run. `caffeinate` prevents idle sleep while the launcher is running.
For a check that makes no model call:

```sh
cd "$HOME/Projects/agent-exchange" || exit 1
.venv/bin/python run_codex_overnight.py --check
```

The launcher invokes `/opt/homebrew/bin/codex --no-daemon --ask-for-approval never exec`
with `--sandbox workspace-write`, `--ignore-user-config`, explicit project-only
write settings, JSON logging and `--output-last-message`. The approval option is
before `exec`, as required by this installed CLI. It retains the currently
configured `gpt-6-astra` / `xhigh` model choice and existing ChatGPT authentication.
No alternate auth home or global configuration changes are made.

Network access is enabled for local HTTP tests, documentation and dependencies.
This is a filesystem write sandbox, not a network allowlist or a guarantee that
other readable files cannot be accessed. `/tmp` and external writable roots are
excluded; temporary files and package caches are directed into this repository.
User-configured MCP servers and hooks are not loaded; hooks, plugins, apps,
computer/browser control, memory updates and multi-agent tools are disabled for
this run. Browser smoke tests can use the project's local Playwright setup.

Blocked operations must be recorded and skipped, not escalated. Approval `never`
does not grant permissions the sandbox denies. The eight-hour limit is a hard
wall-clock ceiling, not a promise of completion or a token/spend limit. No
automatic retries or restart loop are configured. Run only one invocation.

## Evidence and reports

Each launch creates `local_data/codex-overnight/run-<UTC timestamp>/` containing:

- `source-before.tar.gz` and `source-manifest.json`: verified source backup,
  including untracked source, excluding Git-ignored environments, credentials,
  databases, receipts and caches. Existing ignored data is left in place.
- `prompt.txt` and `command.txt`: the complete input and exact command used.
- `events.jsonl` and `stderr.log`: private event and diagnostic logs.
- `COMPLETION_REPORT.md`: Codex's final message, or an explicitly unverified
  fallback if it exits without one.
- `run-status.json`: exit code, deadline/interruption/failure status and report
  source; exit code zero alone is not proof of implementation completion.
- Git status before and after the run.

Logs live under the repository's already-ignored `local_data/`, with private
permissions. Keep them private: tool output may contain project content.
The initial setup backup and verification report are in
`local_data/codex-overnight/setup-20261020T010200855965Z/`.

The launcher cleans up its own process group. Children deliberately detached into
another session require the project's ownership-aware shutdown commands; inspect
the final report for any remaining owned service processes. It never kills by
name or stops a pre-existing service.

CLI behavior reference: [OpenAI non-interactive mode](https://developers.openai.com/codex/noninteractive/)
and [configuration reference](https://developers.openai.com/codex/config-reference/),
checked 20 October 2026 alongside local CLI help.
