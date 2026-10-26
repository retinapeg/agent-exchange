"""Repository-local source manifests and append-only milestone receipts."""
from pathlib import Path
import subprocess
import sys
import tarfile
import os
import json
import socket
import random

from exchange.common import ROOT, DATA, canonical, digest, now, uid, write_json


def manifest():
    excluded = {".git", ".venv", ".cache", ".pytest_cache", "__pycache__", "local_data"}
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(ROOT.rglob("*"))
            if p.is_file() and not excluded.intersection(p.relative_to(ROOT).parts)}


def receipt(name, results, artifacts=(), defects=()):
    source = manifest()
    folder = DATA / "receipts" / (name + "-" + uid())
    write_json(folder / "source-manifest.json", source)
    with tarfile.open(folder / "source.tar.gz", "w:gz") as archive:
        for relative in source:
            archive.add(ROOT / relative, arcname=relative)
    value = {"schema_version": "exchange.milestone.v1", "name": name, "created_at": now(),
             "source_sha256": digest(source), "results": results, "artifacts": list(artifacts),
             "known_defects": list(defects), "construction_usage": None, "construction_cost": None}
    write_json(folder / "receipt.json", value)
    return str(folder.relative_to(ROOT))


def check(name="tests", paths=()):
    # Every invocation gets its own credentials, processes and integer ledger.
    # Repeating validation must never spend or reset the operator's demo wallet.
    runtime = DATA / "validation-runs" / uid()
    runtime.mkdir(parents=True, mode=0o700)
    env = {**os.environ, "EXCHANGE_DATA_DIR": str(runtime)}
    for _ in range(100):
        base = random.SystemRandom().randrange(20000, 55000)
        reserved = []
        try:
            for port in range(base, base + 10):
                sock = socket.socket()
                reserved.append(sock)
                sock.bind(("127.0.0.1", port))
            break
        except OSError:
            continue
        finally:
            for sock in reserved:
                sock.close()
    else:
        raise RuntimeError("No available test port range")
    def control(*args):
        return subprocess.run([sys.executable, "-m", "exchange.cli", *args], cwd=ROOT,
                              env=env, capture_output=True, text=True, timeout=60)
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", *paths]
    output, code = "", 1
    try:
        initialized = control("init", "--base-port", str(base))
        initialized.check_returncode()
        started = control("up")
        started.check_returncode()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        output, code = result.stdout + result.stderr, result.returncode
    finally:
        stopped = control("down")
        final = json.loads(control("status").stdout)
        clean = not final['manager_alive'] and all(v['status'] == 'offline' for v in final['services'].values())
        if not clean:
            code = 1
            output += "\nOwned test services did not stop cleanly.\n"
        location = receipt(name, {"command": [".venv/bin/python", *command[1:]], "exit_code": code,
            "output": output, "runtime_directory": str(runtime.relative_to(ROOT)),
            "isolated_wallet": True, "final_services": final}, [str(runtime.relative_to(ROOT))])
    print(output)
    print("Receipt:", location)
    return code
