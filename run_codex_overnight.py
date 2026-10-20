#!/usr/bin/env python3
"""Run one bounded Codex writer; preserve existing source and private receipts."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tarfile

import psutil  # Already pinned in this project's environment.

ROOT = Path(__file__).resolve().parent
CODEX = Path('/opt/homebrew/bin/codex')
SPEC_HASH = 'ec0415d07e8e138c5d2168dd5dcb7e2ae11c3f8df59ed760aa19de68f1349af3'


def command(report):
    return [
        str(CODEX), '--no-daemon', '--ask-for-approval', 'never', 'exec',
        '--ignore-user-config', '--sandbox', 'workspace-write', '--cd', str(ROOT),
        '--model', 'gpt-6-astra', '-c', 'model_reasoning_effort="xhigh"',
        '-c', 'forced_login_method="chatgpt"',
        '-c', 'sandbox_workspace_write.writable_roots=[]',
        '-c', 'sandbox_workspace_write.exclude_slash_tmp=true',
        '-c', 'sandbox_workspace_write.exclude_tmpdir_env_var=true',
        '-c', 'sandbox_workspace_write.network_access=true',
        '-c', 'shell_environment_policy.ignore_default_excludes=false',
        '--disable', 'multi_agent', '--disable', 'multi_agent_v2',
        '--disable', 'hooks', '--disable', 'plugins', '--disable', 'apps',
        '--disable', 'computer_use', '--disable', 'browser_use',
        '--disable', 'browser_use_external', '--disable', 'in_app_browser',
        '--disable', 'worktrees', '--disable', 'memories',
        '--disable', 'skill_mcp_dependency_install',
        '--color', 'never', '--json', '--output-last-message', str(report), '-',
    ]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def other_writers():
    found = []
    for p in psutil.process_iter(['pid', 'name']):
        name = (p.info['name'] or '').lower()
        if not any(agent in name for agent in ('codex', 'claude', 'aider')):
            continue
        try:
            cwd = Path(p.cwd()).resolve()
            if cwd.is_relative_to(ROOT):
                found.append({'pid': p.pid, 'name': name})
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError(f'Cannot inspect potential writer PID {p.pid}') from exc
    return found


def snapshot(run):
    names = sorted(set(filter(None, git('ls-files', '--cached', '--others',
                                       '--exclude-standard', '-z').split(b'\0'))))
    manifest = {}
    with tarfile.open(run / 'source-before.tar.gz', 'x:gz', dereference=False) as archive:
        for raw in names:
            name = os.fsdecode(raw)
            path = ROOT / name
            if path.is_symlink():
                manifest[name] = {'symlink': os.readlink(path)}
            elif path.is_file():
                manifest[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            else:
                raise RuntimeError(f'Cannot snapshot source: {name}')
            archive.add(path, arcname=name, recursive=False)
    with tarfile.open(run / 'source-before.tar.gz', 'r:gz') as archive:
        for name, entry in manifest.items():
            if 'sha256' in entry:
                archived = hashlib.sha256(archive.extractfile(name).read()).hexdigest()
                current = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                if archived != entry['sha256'] or current != archived:
                    raise RuntimeError(f'Source changed during snapshot: {name}')
    (run / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (run / 'git-status-before.txt').write_bytes(git('status', '--short'))


def stop_owned_group(process):
    # start_new_session gives this invocation its own process group.
    # Never kill by executable name or touch an existing service process.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def execute(run, prompt, seconds, env):
    report = run / 'COMPLETION_REPORT.md'
    argv = command(report)
    (run / 'command.txt').write_text(shlex.join(argv) + '\n')
    (run / 'prompt.txt').write_bytes(prompt)
    status = {'state': 'starting', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'timeout_seconds': seconds, 'spec_sha256': SPEC_HASH}
    status_path = run / 'run-status.json'
    status_path.write_text(json.dumps(status, indent=2) + '\n')
    process = None
    code = 1
    try:
        with (run / 'prompt.txt').open('rb') as source, \
             (run / 'events.jsonl').open('xb') as events, \
             (run / 'stderr.log').open('xb') as errors:
            process = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=source,
                                       stdout=events, stderr=errors, start_new_session=True)
            status.update(state='running', pid=process.pid)
            status_path.write_text(json.dumps(status, indent=2) + '\n')
            try:
                code = process.wait(timeout=seconds)
                status['state'] = 'finished' if code == 0 else 'failed'
            except subprocess.TimeoutExpired:
                status['state'], code = 'deadline_reached', 124
            except KeyboardInterrupt:
                status['state'], code = 'interrupted', 130
    except Exception as exc:
        status.update(state='launcher_error', error=str(exc))
    finally:
        if process is not None:
            stop_owned_group(process)
        status.update(exit_code=code, finished_utc=datetime.now(timezone.utc).isoformat())
        if not report.exists() or not report.stat().st_size:
            report.write_text(
                '# Run completion report\n\n'
                f'Runner outcome: {status["state"]}; exit code: {code}.\n\n'
                'Codex did not produce a final report. Implementation completion is unverified.\n'
                'Review events.jsonl, stderr.log and the retained source changes before resuming.\n'
            )
            status['report_source'] = 'launcher_fallback'
        else:
            status['report_source'] = 'codex_final_message'
        status_path.write_text(json.dumps(status, indent=2) + '\n')
        (run / 'git-status-after.txt').write_bytes(git('status', '--short'))
        print(f'Run ended: {status["state"]} (exit {code}). Report: {report}', flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without starting a model')
    parser.add_argument('--hours', type=float, default=8, help='Hard time limit, 0 < hours <= 12 (default 8)')
    args = parser.parse_args()
    if not 0 < args.hours <= 12:
        parser.error('--hours must be greater than zero and at most 12')
    os.umask(0o077)
    if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != ROOT:
        raise RuntimeError('Script must be located at the Git repository root')
    spec = (ROOT / 'BUILD_SPEC.md').read_bytes()
    if hashlib.sha256(spec).hexdigest() != SPEC_HASH:
        raise RuntimeError('BUILD_SPEC.md differs from the preserved attachment; refusing to run')
    if (ROOT / '.codex/config.toml').exists():
        raise RuntimeError('A project Codex config now exists; review it before running')
    subprocess.run([str(CODEX), '--version'], check=True)
    # Exercise the installed CLI parser without starting an agent.
    subprocess.run(command(Path('COMPLETION_REPORT.md'))[:-1] + ['--help'],
                   check=True, stdout=subprocess.DEVNULL)
    auth = subprocess.run([str(CODEX), 'login', 'status'], capture_output=True, text=True)
    if auth.returncode or 'ChatGPT' not in auth.stdout + auth.stderr:
        raise RuntimeError('Existing ChatGPT login is unavailable; no login or paid API fallback attempted')
    writers = other_writers()
    if writers:
        raise RuntimeError(f'Close the existing repository agent session(s) first: {writers}')
    if args.check:
        print('Preflight passed. No agent started. Command:\n' + shlex.join(command(Path('COMPLETION_REPORT.md'))))
        return 0
    base = ROOT / 'local_data/codex-overnight'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Keep the lock inode: unlinking it would permit two different locks for one path.
    with (base / 'writer.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another overnight launcher owns this repository') from exc
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()) + '\n')
        lock.flush()
        if other_writers():
            raise RuntimeError('Another repository agent appeared during preflight')
        now = datetime.now(timezone.utc)
        run = base / ('run-' + now.strftime('%Y%m%dT%H%M%S%fZ'))
        run.mkdir(mode=0o700)
        snapshot(run)
        seconds = max(1, int(args.hours * 3600))
        deadline = now + timedelta(seconds=seconds)
        instructions = f'''Continue the existing Agent Exchange implementation against the exact specification below.
This is a single-writer unattended run in {ROOT}. Hard deadline: {deadline.isoformat()}.
Inspect local instructions, Git status, dependencies and current implementation first.
Audit each requirement with evidence; do not accept existing reports as proof or rebuild working slices.
Preserve all existing source, ignored task/payment state and historical evidence. A source-only backup is in {run}.
Keep BUILD_SPEC.md and this launcher unchanged. Never reset, delete or replace existing stored results.
One source-code writer only: no subagents, worktrees, branches, commits, pushes or global configuration edits.
Do not touch other repositories, Google Docs or CV material. Keep the existing web UI; no desktop rewrite.
No unrestricted execution, sandbox bypass, paid API fallback, real payments, testnet execution or external outreach.
Use the installed project environment and repository-local caches. Public documentation/package downloads and
owned loopback HTTP tests are allowed. Network access is enabled for those purposes; do not use unrelated services.
For this small Mac, keep model calls sequential, retain the specification's finite call ceilings and checkpoint work.
Existing CLI authentication may be used for bounded product-model checks, never additional source-code writers.
If a sandbox, credential or approval requirement blocks work, record it and continue independent authorized work.
Do not ask interactive questions or attempt to remove restrictions. Do not modify global login/configuration.
Allow time before the deadline to verify changes, clean up only processes you started and write your final report.
End with a completion report: completed/partial/blocked requirements, checks actually run and their results,
live calls, payment mode, defects, exact pending permissions and one next step. Distinguish claims from verification.
Exit at verified completion or the deadline; do not loop or automatically restart to fill time.

Exact attached specification follows:

'''
        env = os.environ.copy()
        for name in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
            env.pop(name, None)
        for name, relative in {
            'TMPDIR': '.cache/codex-tmp', 'XDG_CACHE_HOME': '.cache',
            'UV_CACHE_DIR': '.cache/uv', 'PIP_CACHE_DIR': '.cache/pip',
            'npm_config_cache': '.cache/npm',
        }.items():
            path = ROOT / relative
            path.mkdir(parents=True, exist_ok=True)
            env[name] = str(path)
        print(f'One Codex writer; {args.hours:g}-hour maximum. Logs: {run}', flush=True)
        return execute(run, instructions.encode() + spec, seconds, env)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Not started: {exc}', file=sys.stderr)
        sys.exit(1)
