from pathlib import Path
import hmac
import secrets
import json
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from exchange.client import PeerClient
from exchange.security import Guard
from exchange.common import DATA, Database, uid
from exchange.integration import ObserverAdapter


def make_observer(c):
    peer = c["peers"]["observer"]
    from exchange.lab import Lab, routes as lab_routes
    lab = Lab(c)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lab.lifespan)
    client = PeerClient(c, "observer")
    operator_client = PeerClient(c, 'operator')
    adapter = ObserverAdapter(DATA / 'observer/integration.sqlite')
    sessions = {}
    cursors, observed = {}, {}

    def authenticated(request):
        if sessions.get(request.cookies.get('exchange-session'), 0) <= time.time():
            raise HTTPException(401)

    async def receive_notifications():
        r=await client.http('buyer','GET',f'/integration/events?after={adapter.cursor()}')
        r.raise_for_status()
        for item in r.json()['events']:
            adapter.receive(item['seq'],item['envelope'],'agent-exchange')

    @app.post('/submit',status_code=202)
    async def submit(request:Request):
        authenticated(request)
        value=await request.json()
        # The UI cannot skip review of a simulated payment or introduce another mode.
        if isinstance(value,dict) and value.get('payment_mode')=='simulator':
            value['require_approval']=True
        r=await operator_client.http('buyer','POST','/submit',json=value,headers={'Idempotency-Key':request.headers.get('idempotency-key','')})
        return JSONResponse(r.json(),r.status_code)

    @app.post('/approvals/{approval_id}')
    async def decide(approval_id:str,request:Request):
        authenticated(request)
        value=await request.json()
        if not isinstance(value,dict) or set(value)!={'binding','approve'} or type(value['approve']) is not bool:
            raise HTTPException(422)
        from exchange.failures import ExchangeFailure
        import httpx
        try:
            await receive_notifications()
            return await adapter.decide(operator_client,approval_id,value['binding'],value['approve'])
        except ExchangeFailure as e: raise HTTPException(409,str(e)) from None
        except httpx.HTTPStatusError as e: return JSONResponse(e.response.json(),e.response.status_code)

    @app.post('/runs/{run_id}/resume',status_code=202)
    async def resume(run_id:str,request:Request):
        authenticated(request)
        r=await operator_client.http('buyer','POST','/runs/'+run_id+'/resume')
        return JSONResponse(r.json(),r.status_code)

    @app.get("/health")
    async def health():
        return {"status": "ok", "peer": "observer", "instance": peer.get("instance")}

    @app.get("/")
    async def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html", headers={"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"})

    @app.get("/app.js")
    async def script():
        return FileResponse(Path(__file__).parent / "static" / "app.js")

    @app.get("/style.css")
    async def style():
        return FileResponse(Path(__file__).parent / "static" / "style.css")

    @app.get("/lab.js")
    async def lab_script():
        return FileResponse(Path(__file__).parent / "static" / "lab.js")

    @app.get("/lab.css")
    async def lab_style():
        return FileResponse(Path(__file__).parent / "static" / "lab.css")

    lab_routes(app, lab, authenticated)

    @app.post("/session")
    async def login(request: Request):
        body = await request.json()
        if not hmac.compare_digest(str(body.get("token", "")), peer["tokens"]["operator"]):
            raise HTTPException(401)
        session = secrets.token_urlsafe(32)
        for old, expires in list(sessions.items()):
            if expires <= time.time():
                sessions.pop(old, None)
        if len(sessions) >= 64:
            sessions.pop(next(iter(sessions)))
        sessions[session] = time.time() + 3600
        response = JSONResponse({"ok": True})
        response.set_cookie("exchange-session", session, httponly=True, samesite="strict", max_age=3600)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        sessions.pop(request.cookies.get("exchange-session"), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie("exchange-session")
        return response

    @app.get("/snapshot")
    async def snapshot(request: Request):
        authenticated(request)
        agents, runs, quotes, issues = [], [], [], []
        ledger = None
        approvals, performance = [], {}
        for name, p in c["peers"].items():
            if name == "observer":
                continue
            try:
                r = await client.http(name, "GET", f"/observe?after={cursors.get(name, 0)}")
                r.raise_for_status()
                for event in r.json()["events"]:
                    observed[event["event_id"]] = event
                    cursors[name] = max(cursors.get(name, 0), event["seq"])
                if "services" in p:
                    q = await client.http(name, "GET", "/quotes")
                    q.raise_for_status()
                    quotes.extend(q.json()["quotes"])
                    for unknown in q.json()["unresolved"]:
                        issues.append({"peer": name, "error": "payment outcome unknown: " + unknown["order_id"]})
                if name == "ledger":
                    r = await client.http(name, "GET", "/summary")
                    r.raise_for_status()
                    ledger = r.json()
            except Exception as e:
                issues.append({"peer": name, "error": type(e).__name__})
        try:
            r = await client.http("registry", "GET", "/agents")
            r.raise_for_status()
            agents = r.json()["agents"]
            r = await client.http("buyer", "GET", "/runs")
            r.raise_for_status()
            runs = r.json()["runs"]
            r=await client.http('buyer','GET','/approvals'); r.raise_for_status()
            approvals=r.json()['approvals']
            r=await client.http('buyer','GET','/performance'); r.raise_for_status()
            performance=r.json()['history']
            await receive_notifications()
        except Exception as e:
            issues.append({"peer": "buyer/registry", "error": type(e).__name__})
        receipts = [json.loads(p.read_text()) for p in sorted((DATA / "models").glob("*/receipt.json"),key=lambda p:p.stat().st_mtime)]
        estimates = [r["estimated_inference_usd"] for r in receipts if r.get("estimated_inference_usd") is not None]
        models = {"calls": len(receipts), "completed": sum(r["status"] == "completed" for r in receipts), "failed": sum(r["status"] == "failed" for r in receipts),
                  "known_estimates": len(estimates), "estimated_usd": sum(estimates) if estimates else None,
                  'configured_backend':c['model']['backend'],'configured_model':c['model']['model'],
                  'recent':[{k:r.get(k) for k in ('call_id','trace_id','purpose','backend','observed_model','requested_model','status','usage','estimated_inference_usd','latency_ms')} for r in receipts[-15:]]}
        model_db=DATA/'models/calls.sqlite'
        if model_db.exists():
            for event in Database(model_db).events(cursors.get('models',0)):
                observed[event['event_id']]=event
                cursors['models']=event['seq']
        events = sorted(observed.values(), key=lambda e: e["created_at"])[-300:]
        observed.clear()
        observed.update({e["event_id"]: e for e in events})
        return {"agents": agents, "runs": runs, "events": events, "quotes": quotes, "ledger": ledger, "models": models,
                'approvals':approvals,'performance':performance,'integration_cursor':adapter.cursor(),
                "issues": issues, "costs": {"construction_usage": None, "inference_cost": None, "actual_service_expenditure": 0, "payment_mode": "free / local simulator"},
                "permissions": [{"capability": "public testnet", "state": "requires explicit operator configuration"}, {"capability": "real cross-project adapters", "state": "endpoints not authorised"}]}
    # Session-authenticated actions are public to the bearer guard only; each
    # route still checks the HttpOnly operator session and same-origin Host/Origin.
    # Lab routes check the operator session (or operator bearer) themselves; polling reads are not logged.
    return Guard(app, peer, public=["/", "/app.js", "/style.css", "/lab.js", "/lab.css", "/session", "/snapshot", "/logout",'/submit'],
                 public_prefixes=('/approvals/','/runs/','/lab/'),store=adapter,quiet_prefixes=('/lab/',))
