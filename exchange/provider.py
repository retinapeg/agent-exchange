from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from a2a import types as t
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import RequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.common import ServerCallContextBuilder
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.utils.errors import InvalidParamsError, PushNotificationNotSupportedError, ExtendedAgentCardNotConfiguredError, UnsupportedOperationError
from a2a.utils.proto_utils import validate_proto_required_fields
from fastapi import FastAPI, Request, HTTPException
from google.protobuf.json_format import MessageToDict

from exchange.common import DATA, NS, uid, digest
from exchange.security import Guard
from exchange.services import execute
from exchange.contracts import task_schema, schema_errors
from exchange.tasks import TaskStore, INTERRUPTED, TERMINAL, proto


def card(peer):
    return proto({"name": peer["id"], "description": "Local development identity. Synthetic fixture services; identity and quality are not certified.",
        "version": "0.1.0", "supportedInterfaces": [{"url": peer["url"] + "/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "capabilities": {"streaming": True, "extensions": [{"uri": NS, "description": "Optional application task schema, deduplication and cursor replay; not part of core A2A", "required": False}]},
        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
        "securitySchemes": {"peerBearer": {"httpAuthSecurityScheme": {"scheme": "bearer", "description": "Per-receiver local development credential"}}},
        "securityRequirements": [{"schemes": {"peerBearer": {"list": []}}}],
        "skills": [{"id": s, "name": s, "description": "Structured " + s + (" service; fixture or explicit live model" if s == "requirements" else " service; deterministic fixture"), "tags": [s]} for s in peer["services"]]}, t.AgentCard)


class Context(ServerCallContextBuilder):
    def build(self, request):
        return ServerCallContext(state={"principal": request.state.principal, "headers": dict(request.headers)})


class Provider(RequestHandler):
    def __init__(self, peer, store=None):
        self.peer = peer
        self.store = store or TaskStore(DATA / peer["id"] / "tasks.sqlite", peer["id"])
        self.workers = {}
        self.slots = asyncio.Semaphore(4)

    def principal(self, ctx):
        return ctx.state["principal"]

    def read(self, task_id, ctx, history_length=None):
        body = json.loads(self.store.get(task_id, self.principal(ctx))["body"])
        if history_length is not None:
            if history_length < 0:
                raise InvalidParamsError("historyLength cannot be negative")
            body["history"] = body.get("history", [])[-history_length:] if history_length else []
        return proto(body, t.Task)

    def validate(self, params):
        validate_proto_required_fields(params)
        w = MessageToDict(params)
        try:
            p = w["message"]["parts"][0]["data"]
            task_schema(p, self.peer["services"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise InvalidParamsError(str(e)) from None
        conf = params.configuration
        if conf.HasField("task_push_notification_config"):
            raise PushNotificationNotSupportedError()
        if conf.accepted_output_modes and "application/json" not in conf.accepted_output_modes:
            from a2a.utils.errors import ContentTypeNotSupportedError
            raise ContentTypeNotSupportedError()

    async def start(self, params, ctx):
        if self.principal(ctx) not in ("buyer", "operator", "test-other"):
            raise InvalidParamsError("read-only principal cannot submit tasks")
        self.validate(params)
        headers = ctx.state["headers"]
        key = headers.get("idempotency-key") or params.message.message_id
        if not key or len(key) > 128:
            raise InvalidParamsError("invalid idempotency key")
        if headers.get("x-exchange-order"):
            from exchange.commerce import validate_admission
            from exchange.failures import ExchangeFailure
            try:
                validate_admission(self.store, headers["x-exchange-order"], self.principal(ctx), MessageToDict(params)["message"]["parts"][0]["data"], key)
            except ExchangeFailure as e:
                raise InvalidParamsError(str(e)) from None
        # Bound admitted work as well as executing work.
        if len(self.workers) >= 64:
            with self.store.connect() as db:
                duplicate = db.execute("SELECT 1 FROM operations WHERE principal=? AND key=?", (self.principal(ctx), key)).fetchone()
            if not duplicate:
                raise UnsupportedOperationError("Provider capacity reached; retry same operation later")
        task_id, new = self.store.submit(params, self.principal(ctx), key, headers.get("x-trace-id") or uid())
        if new:
            worker = asyncio.create_task(self.run(task_id, self.principal(ctx)))
            self.workers[task_id] = worker
            worker.add_done_callback(lambda _: self.workers.pop(task_id, None))
        return task_id

    async def run(self, task_id, principal):
        async with self.slots:
            if not self.store.transition(task_id, "TASK_STATE_WORKING", text="Input admitted; validating service request."):
                return
            try:
                row = self.store.get(task_id, principal)
                payload = json.loads(row["input"])
                await asyncio.sleep(self.peer.get("delay", 0.1))
                if payload["service"] == "csv-audit" and "ranges" not in payload:
                    self.store.transition(task_id, "TASK_STATE_INPUT_REQUIRED", text="Please supply ranges as a map of numeric columns to [minimum, maximum], and repeat the source. An empty map explicitly requests no range checks.")
                    return
                if self.peer.get("fault") == "fail_once" and row["version"] == 1:
                    marker = self.store.path.parent / "fault-used"
                    try:
                        with marker.open("x") as f:
                            f.write(task_id)
                        raise RuntimeError("injected_provider_failure")
                    except FileExistsError:
                        pass
                self.store.transition(task_id, "TASK_STATE_WORKING", text="Processing source; output will require independent verification.")
                if payload.get("backend") == "live":
                    from exchange.models import model_artifact
                    result = await model_artifact(payload, row["trace_id"])
                else:
                    result = execute(payload)
                await asyncio.sleep(self.peer.get("delay", 0.1))
                if self.peer.get("fault") == "bad_artifact":
                    result = {"misleading": "completed does not imply correct"}
                self.store.transition(task_id, "TASK_STATE_COMPLETED", artifact=result)
            except asyncio.CancelledError:
                # Explicit cancellation and shutdown both leave an observable terminal state.
                self.store.transition(task_id, "TASK_STATE_CANCELED", text="Owned local worker cancelled; effects already committed remain.")
                raise
            except Exception as e:
                category = "schema" if isinstance(e, (ValueError, KeyError, TypeError)) else "provider"
                self.store.transition(task_id, "TASK_STATE_FAILED", text=f"Service failed ({type(e).__name__}); explicit new submission required.", failure=category)

    async def on_message_send(self, params, context):
        task_id = await self.start(params, context)
        if not params.configuration.return_immediately:
            await self.wait(task_id, context)
        n = params.configuration.history_length if params.configuration.HasField("history_length") else None
        return self.read(task_id, context, n)

    async def wait(self, task_id, context):
        async with asyncio.timeout(150):
            while self.store.get(task_id, self.principal(context))["state"] not in INTERRUPTED:
                await asyncio.sleep(0.03)

    async def events(self, task_id, context, after=0):
        async with asyncio.timeout(150):
            while True:
                row = self.store.get(task_id, self.principal(context))
                events = self.store.stream_events(task_id, after)
                for e in events:
                    after = e["seq"]
                    event = e["event"]
                    key, value = next(iter(event.items()))
                    cls = {"task": t.Task, "statusUpdate": t.TaskStatusUpdateEvent, "artifactUpdate": t.TaskArtifactUpdateEvent}[key]
                    yield proto(value, cls)
                if row["state"] in INTERRUPTED:
                    return
                await asyncio.sleep(0.03)

    async def on_message_send_stream(self, params, context):
        task_id = await self.start(params, context)
        async for e in self.events(task_id, context):
            yield e

    async def on_subscribe_to_task(self, params, context):
        # Cursor is read BEFORE the snapshot so a concurrent update cannot be lost.
        self.store.get(params.id, self.principal(context))
        with self.store.connect() as db:
            after = db.execute("SELECT COALESCE(MAX(seq),0) FROM task_events WHERE task_id=?", (params.id,)).fetchone()[0]
        task = self.read(params.id, context)
        if t.TaskState.Name(task.status.state) in TERMINAL:
            raise UnsupportedOperationError("Terminal task: use GetTask or the application replay endpoint")
        yield task
        async for e in self.events(params.id, context, after):
            yield e

    async def on_get_task(self, params, context):
        return self.read(params.id, context, params.history_length if params.HasField("history_length") else None)

    async def on_cancel_task(self, params, context):
        self.store.cancel(params.id, self.principal(context))
        if params.id in self.workers:
            self.workers[params.id].cancel()
        return self.read(params.id, context)

    async def on_list_tasks(self, params, context):
        size = params.page_size if params.HasField("page_size") else 50
        if not 1 <= size <= 100:
            raise InvalidParamsError("pageSize must be between 1 and 100")
        principal = self.principal(context)
        wire = MessageToDict(params)
        filters = {k: v for k, v in wire.items() if k in ("contextId", "status", "statusTimestampAfter")}
        query_hash = digest(filters)
        clauses, arguments = ["principal=?"], [principal]
        if params.context_id:
            clauses.append("json_extract(body,'$.contextId')=?")
            arguments.append(params.context_id)
        if params.status:
            clauses.append("state=?")
            arguments.append(t.TaskState.Name(params.status))
        if params.HasField("status_timestamp_after"):
            clauses.append("julianday(updated)>=julianday(?)")
            arguments.append(params.status_timestamp_after.ToJsonString())
        where = " AND ".join(clauses)
        with self.store.tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS pagination(token TEXT PRIMARY KEY, principal TEXT, query_hash TEXT, updated TEXT, task_id TEXT, expires REAL)")
            db.execute("DELETE FROM pagination WHERE expires<?", (time.time(),))
            total = db.execute("SELECT COUNT(*) FROM tasks WHERE " + where, arguments).fetchone()[0]
            if params.page_token:
                cursor = db.execute("SELECT * FROM pagination WHERE token=? AND principal=? AND query_hash=?", (params.page_token, principal, query_hash)).fetchone()
                if not cursor:
                    raise InvalidParamsError("invalid, expired or differently scoped page token")
                where += " AND (updated<? OR (updated=? AND id>?))"
                arguments.extend([cursor["updated"], cursor["updated"], cursor["task_id"]])
            rows = db.execute("SELECT * FROM tasks WHERE " + where + " ORDER BY updated DESC,id ASC LIMIT ?", [*arguments, size+1]).fetchall()
            token = ""
            if len(rows) > size:
                last = rows[size-1]
                token = uid()
                db.execute("INSERT INTO pagination VALUES(?,?,?,?,?,?)", (token, principal, query_hash, last["updated"], last["id"], time.time()+600))
        tasks = []
        for row in rows[:size]:
            body = json.loads(row["body"])
            history = params.history_length if params.HasField("history_length") else 0
            if history < 0:
                raise InvalidParamsError("historyLength cannot be negative")
            body["history"] = body.get("history", [])[-history:] if history else []
            task = proto(body, t.Task)
            if not params.include_artifacts:
                task.ClearField("artifacts")
            tasks.append(task)
        return t.ListTasksResponse(tasks=tasks, page_size=size, total_size=total, next_page_token=token)

    async def on_create_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()
    async def on_get_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()
    async def on_list_task_push_notification_configs(self, params, context):
        raise PushNotificationNotSupportedError()
    async def on_delete_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()
    async def on_get_extended_agent_card(self, params, context):
        raise ExtendedAgentCardNotConfiguredError()


def make_provider(peer):
    handler = Provider(peer)
    @asynccontextmanager
    async def lifespan(app):
        handler.store.recover()
        yield
        workers = list(handler.workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    schema_errors(app)
    app.routes.extend(create_agent_card_routes(card(peer), cache_control="max-age=60"))
    app.routes.extend(create_jsonrpc_routes(handler, "/a2a", Context()))

    @app.get("/health")
    async def health():
        return {"status": "ok", "peer": peer["id"], "identity": "local-development", "protocol": "1.0", "instance": peer.get("instance")}

    @app.get("/events/{task_id}")
    async def replay(task_id: str, request: Request, after: int = 0):
        handler.store.get(task_id, request.state.principal)
        return {"extension": NS, "events": handler.store.stream_events(task_id, after)}

    @app.get("/artifacts/{task_id}/{artifact_id}")
    async def artifact(task_id: str, artifact_id: str, request: Request):
        row = handler.store.get(task_id, request.state.principal)
        artifacts = json.loads(row["body"]).get("artifacts", [])
        for a in artifacts:
            if a["artifactId"] == artifact_id:
                return a
        raise HTTPException(404)

    @app.get("/observe")
    async def observe(request: Request, after: int = 0):
        if request.state.principal not in ["observer", "operator"]:
            raise HTTPException(403)
        return {"events": handler.store.events(after)}

    # Application-level quotes and payment admissions are separate from A2A states.
    from exchange.commerce import add_commerce
    add_commerce(app, peer, handler.store)
    if "match" in peer["services"]:
        from exchange.matchmaking import add_disclosures
        add_disclosures(app, DATA / peer["id"] / "disclosures.sqlite")
    return Guard(app, peer, store=handler.store)
