import argparse
import asyncio
import json

from exchange.common import config, init_config


def main():
    parser = argparse.ArgumentParser(description="Local Agent Exchange")
    parser.add_argument("command", choices=["init", "up", "down", "status", "serve", "supervise", "demo", "showcase", "browser-check", "test", "preflight", "live-pilot", "benchmark", "report", "mcp", "sdk-check", "testnet-init", "testnet", "restart-check", "live-safety", "match-sim", "lab", "lab-campaign", "lab-report"])
    parser.add_argument("peer", nargs="?")
    parser.add_argument("--owner")
    parser.add_argument("--base-port", type=int, default=8710)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config")
    parser.add_argument('--live',action='store_true',help='Explicitly enable bounded authenticated CLI calls for showcase')
    parser.add_argument('--crash',action='store_true',help='Inject SIGKILL into the exact owned provider during restart-check')
    parser.add_argument('--provider', choices=['fixture', 'claude'], default='fixture', help='match-sim agents; claude makes live model calls')
    parser.add_argument('--budget', type=int, default=0, help='hard model-call budget for match-sim --provider claude')
    parser.add_argument('--dev', action='store_true', help='match-sim on development seeds only; unscored, writes nothing')
    parser.add_argument('--mode', choices=['isolated', 'communication', 'intervention'], default='communication', help='lab condition A, B or C')
    parser.add_argument('--trial', choices=['fixed', 'random'], default='fixed', help='lab inputs: 120 W / 21 C / 0.18 K/W, or fresh seeded values')
    parser.add_argument('--seed', type=int, help='lab: reuse a random trial seed (matched inputs)')
    parser.add_argument('--brain', choices=['fixture', 'claude'], default='fixture', help='lab agent brains; claude makes live CLI calls')
    parser.add_argument('--approve-live', action='store_true', help='lab: explicit operator approval for live Claude calls (max 12 per run)')
    parser.add_argument('--freeze', action='store_true', help='lab-campaign: freeze the plan and seeds without running')
    args = parser.parse_args()
    if args.command == "init":
        init_config(args.base_port)
        from exchange.lab_config import ensure_lab_config
        c = ensure_lab_config()
        result = {"configured": list(c["peers"]), "dashboard": c["peers"]["observer"]["url"]}
    elif args.command in ["up", "down", "status", "serve", "supervise"]:
        from exchange import processes
        if args.command == "serve":
            return processes.serve(args.peer, args.owner)
        if args.command == "supervise":
            return processes.supervise(args.owner)
        result = getattr(processes, {"up": "start", "down": "stop", "status": "status"}[args.command])()
    elif args.command == "demo":
        from exchange.demo import demo
        result = asyncio.run(demo())
    elif args.command == 'showcase':
        from exchange.showcase import showcase
        result=asyncio.run(showcase(args.live))
    elif args.command == 'browser-check':
        from exchange.browser_check import browser_check
        result=asyncio.run(browser_check())
    elif args.command == "test":
        from exchange.evidence import check
        raise SystemExit(check())
    elif args.command in ["preflight", "live-pilot"]:
        from exchange import models
        result = asyncio.run(getattr(models, args.command.replace("-", "_"))())
    elif args.command == "sdk-check":
        from exchange.x402_checks import conformance
        value = conformance()
        result = {k: v for k, v in value.items() if k not in ("headers", "payload")}
    elif args.command == "benchmark":
        from exchange.benchmark import benchmark
        result = benchmark(args.resume)
    elif args.command == "mcp":
        from exchange.mcp_bridge import run
        return run()
    elif args.command == "match-sim":
        from exchange.match_sim import match_sim
        print(match_sim(args.provider, args.budget, args.dev))
        return
    elif args.command == "lab":
        from exchange.lab_cli import lab_run
        result = lab_run(args.mode, args.trial, args.seed, args.brain, args.approve_live)
    elif args.command == "lab-campaign":
        from exchange.lab_cli import campaign, freeze
        result = freeze() if args.freeze else campaign(args.approve_live)
    elif args.command == "lab-report":
        from exchange.lab_cli import report
        result = report()
    elif args.command == "restart-check":
        from exchange.runtime_check import restart_check
        result = restart_check(args.crash)
    elif args.command == "live-safety":
        from exchange.live_safety import probe
        result = asyncio.run(probe())
    elif args.command == "report":
        from exchange.reports import report
        result = report()
    elif args.command in ("testnet-init", "testnet"):
        from exchange.testnet import create_test_account, run_testnet
        result = create_test_account() if args.command == "testnet-init" else asyncio.run(run_testnet(args.config))
    else:
        raise SystemExit("Unhandled command")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
