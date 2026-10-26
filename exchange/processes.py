"""Own only child PIDs with matching creation time, command and instance token."""
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time

import httpx
import psutil

from exchange.common import ROOT, DATA, config, init_config, uid, write_json


def process_matches(info):
    try:
        p = psutil.Process(info["pid"])
        return abs(p.create_time()-info["created"]) < 0.01 and info["owner"] in p.cmdline() and "exchange.cli" in p.cmdline()
    except (psutil.Error, KeyError):
        return False


def info(p, owner):
    return {"pid": p.pid, "created": psutil.Process(p.pid).create_time(), "owner": owner}


def status():
    c = config()
    path = DATA / "processes.json"
    record = json.loads(path.read_text()) if path.exists() else {}
    result = {"manager_alive": process_matches(record.get("manager", {})), "services": {}}
    with httpx.Client(timeout=1, trust_env=False) as client:
        for name, peer in c["peers"].items():
            try:
                r = client.get(peer["url"]+"/health")
                result["services"][name] = {"http": r.status_code, **r.json(), "owned": r.json().get("instance") == record.get("owner") and process_matches(record.get("children", {}).get(name, {}))}
            except Exception:
                result["services"][name] = {"status": "offline", "owned": False}
    return result


def start():
    DATA.mkdir(exist_ok=True)
    init_config()
    from exchange.lab_config import ensure_lab_config
    ensure_lab_config()
    current = status()
    if current["manager_alive"]:
        return current
    owner = uid()
    log = (DATA / "supervisor.log").open("ab")
    manager = subprocess.Popen([sys.executable, "-m", "exchange.cli", "supervise", "--owner", owner], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    log.close()
    for _ in range(100):
        if manager.poll() is not None:
            raise RuntimeError("Supervisor failed; inspect local_data/supervisor.log")
        s = status()
        if all(v.get("owned") for v in s["services"].values()):
            return s
        time.sleep(0.1)
    manager.terminate()
    manager.wait(timeout=15)
    raise RuntimeError("Startup did not pass ownership and health checks")


def stop():
    path = DATA / "processes.json"
    if not path.exists():
        return {"stopped": True, "reason": "no ownership record"}
    record = json.loads(path.read_text())
    if process_matches(record.get("manager", {})):
        os.kill(record["manager"]["pid"], signal.SIGTERM)
        for _ in range(150):
            if not process_matches(record["manager"]):
                break
            time.sleep(0.1)
    # Crash recovery: only exact recorded and still-matching children.
    for p in record.get("children", {}).values():
        if process_matches(p):
            os.kill(p["pid"], signal.SIGTERM)
    return {"stopped": not any(process_matches(p) for p in record.get("children", {}).values())}


def reserve_ports(peers):
    reservations = []
    for peer in peers.values():
        s = socket.socket()
        try:
            # Match the server's reuse semantics: closed connections in TIME_WAIT
            # must not prevent restart. This still refuses an active listener.
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            s.bind(("127.0.0.1", peer["port"]))
            reservations.append(s)
        except OSError:
            s.close()
            for old in reservations:
                old.close()
            raise RuntimeError(f"Port {peer['port']} already occupied; no process was killed")
    return reservations


def supervise(owner):
    lock = (DATA / "process.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    c = config()
    reservations=reserve_ports(c['peers'])
    for s in reservations:
        s.close()
    children = {}
    record = {"owner": owner, "manager": info(psutil.Process(), owner), "children": {}}
    running = True
    def halt(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    try:
        for name in c["peers"]:
            out = DATA / name
            out.mkdir(exist_ok=True)
            with (out / "server.log").open("ab") as log:
                p = subprocess.Popen([sys.executable, "-m", "exchange.cli", "serve", name, "--owner", owner], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            children[name] = p
            record["children"][name] = info(p, owner)
        write_json(DATA / "processes.json", record)
        while running:
            # The ledger is optional infrastructure. Its outage must not take
            # down genuinely free A2A work; paid operations fail closed.
            if any(p.poll() is not None for name,p in children.items() if name != 'ledger'):
                break
            time.sleep(0.2)
    finally:
        for name, p in children.items():
            if p.poll() is None and process_matches(record["children"][name]):
                p.terminate()
        for p in children.values():
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()  # exact owned Popen object, no name matching
                p.wait(timeout=3)


def serve(name, owner):
    import uvicorn
    c = config()
    for peer in c["peers"].values():
        peer["instance"] = owner
    peer = c["peers"][name]
    directory = DATA / name
    directory.mkdir(exist_ok=True)
    lock = (directory / "service.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if "services" in peer:
        from exchange.provider import make_provider
        app = make_provider(peer)
    elif name == "registry":
        from exchange.registry import make_registry
        app = make_registry(c)
    elif name == "buyer":
        from exchange.buyer import make_buyer
        app = make_buyer(c)
    elif name == "observer":
        from exchange.observer import make_observer
        app = make_observer(c)
    elif peer.get("lab_agent"):
        from exchange.lab_agent import make_lab_agent
        app = make_lab_agent(c, name)
    else:
        from exchange.ledger import make_ledger
        app = make_ledger(c)
    uvicorn.run(app, host="127.0.0.1", port=peer["port"], access_log=False, log_level="warning", timeout_graceful_shutdown=5)
