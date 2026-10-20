import argparse
import asyncio
import json

from exchange.common import config, init_config


def main():
    parser = argparse.ArgumentParser(description="Local Agent Exchange")
    parser.add_argument("command", choices=["init", "up", "down", "status", "serve", "supervise", "demo", "showcase", "browser-check", "test", "preflight", "live-pilot", "benchmark", "report", "mcp", "sdk-check", "testnet-init", "testnet", "restart-check", "live-safety"])
    parser.add_argument("peer", nargs="?")
    parser.add_argument("--owner")
    parser.add_argument("--base-port", type=int, default=8710)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config")
    parser.add_argument('--live',action='store_true',help='Explicitly enable bounded authenticated CLI calls for showcase')
    parser.add_argument('--crash',action='store_true',help='Inject SIGKILL into the exact owned provider during restart-check')
    args = parser.parse_args()
    if args.command == "init":
        c = init_config(args.base_port)
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
