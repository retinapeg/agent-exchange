from __future__ import annotations

import json
from pathlib import Path

from a2a import types as t
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError, TaskNotCancelableError
from google.protobuf.json_format import MessageToDict, ParseDict

from exchange.common import Database, NS, canonical, digest, now, uid

TERMINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}
INTERRUPTED = TERMINAL | {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}


def proto(data, cls):
    return ParseDict(data, cls())


class TaskStore(Database):
    def __init__(self, path: Path, provider):
        super().__init__(path)
        self.provider = provider
        with self.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, principal TEXT NOT NULL, trace_id TEXT,
              body TEXT NOT NULL, input TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(principal TEXT, key TEXT, digest TEXT, task_id TEXT,
              PRIMARY KEY(principal,key), FOREIGN KEY(task_id) REFERENCES tasks(id));
            CREATE TABLE IF NOT EXISTS task_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE,
              task_id TEXT REFERENCES tasks(id), body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS tasks_principal_cursor ON tasks(principal,updated DESC,id);
            """)

    def get(self, task_id, principal):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=? AND principal=?", (task_id, principal)).fetchone()
        if not row:
            raise TaskNotFoundError()
        return dict(row)

    def submit(self, params, principal, key, trace_id):
        wire = MessageToDict(params)
        msg = wire["message"]
        if not msg.get("messageId") or msg.get("role") != "ROLE_USER":
            raise InvalidParamsError("messageId and user role required")
        parts = msg.get("parts", [])
        if len(parts) != 1 or not isinstance(parts[0].get("data"), dict):
            raise InvalidParamsError("One structured application data part is required")
        payload = parts[0]["data"]
        # Semantic request hash excludes transport-generated message IDs; IDs remain in history.
        fingerprint = digest({"payload": payload, "task": msg.get("taskId"), "context": msg.get("contextId")})
        with self.tx() as db:
            old = db.execute("SELECT * FROM operations WHERE principal=? AND key=?", (principal, key)).fetchone()
            if old:
                if old["digest"] != fingerprint:
                    raise InvalidParamsError("idempotency_key_content_conflict")
                return old["task_id"], False
            task_id = msg.get("taskId") or uid()
            if msg.get("taskId"):
                row = db.execute("SELECT * FROM tasks WHERE id=? AND principal=?", (task_id, principal)).fetchone()
                if not row:
                    raise TaskNotFoundError()
                if row["state"] != "TASK_STATE_INPUT_REQUIRED":
                    raise InvalidParamsError("Only input-required tasks can be continued")
                body = json.loads(row["body"])
                if msg.get("contextId") and msg["contextId"] != body["contextId"]:
                    raise InvalidParamsError("context mismatch")
                version = row["version"] + 1
                body.setdefault("history", []).append(msg)
            else:
                version = 1
                body = {"id": task_id, "contextId": msg.get("contextId") or uid(), "history": [msg], "metadata": {NS: {"trace_id": trace_id, "provider": self.provider}}}
            body["status"] = {"state": "TASK_STATE_SUBMITTED", "timestamp": now()}
            body["metadata"][NS].update(input_version=version, input_sha256=digest(payload))
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,input=excluded.input,version=excluded.version,state=excluded.state,updated=excluded.updated",
                       (task_id, principal, trace_id, canonical(body).decode(), canonical(payload).decode(), version, "TASK_STATE_SUBMITTED", now()))
            db.execute("INSERT INTO operations VALUES(?,?,?,?)", (principal, key, fingerprint, task_id))
            self._event(db, task_id, {"task": body}, trace_id, "task.submitted")
        return task_id, True

    def _event(self, db, task_id, event, trace_id, kind):
        event_id = uid()
        db.execute("INSERT INTO task_events(event_id,task_id,body) VALUES(?,?,?)", (event_id, task_id, canonical(event).decode()))
        self.event(kind, self.provider, "buyer", db=db, task_id=task_id, trace_id=trace_id, output_hash=digest(event), disposition=kind)

    def transition(self, task_id, state, *, text=None, artifact=None, failure=None):
        with self.tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row["state"] in TERMINAL:
                return False
            body = json.loads(row["body"])
            status = {"state": state, "timestamp": now()}
            if text:
                status["message"] = {"messageId": uid(), "taskId": task_id, "contextId": body["contextId"], "role": "ROLE_AGENT", "parts": [{"text": text}]}
                body.setdefault("history", []).append(status["message"])
            body["status"] = status
            if failure:
                body["metadata"][NS]["failure_category"] = failure
            if artifact is not None:
                raw = canonical(artifact)
                a = {"artifactId": uid(), "name": "result.json", "parts": [{"data": artifact, "mediaType": "application/json"}],
                     "metadata": {NS: {"size": len(raw), "sha256": digest(raw), "provider": self.provider,
                     "input_sha256": digest(json.loads(row["input"])), "input_version": row["version"], "created_at": now()}}}
                body["artifacts"] = [a]
                self._event(db, task_id, {"artifactUpdate": {"taskId": task_id, "contextId": body["contextId"], "artifact": a, "lastChunk": True}}, row["trace_id"], "artifact.created")
            db.execute("UPDATE tasks SET body=?,state=?,updated=? WHERE id=?", (canonical(body).decode(), state, now(), task_id))
            self._event(db, task_id, {"statusUpdate": {"taskId": task_id, "contextId": body["contextId"], "status": status}}, row["trace_id"], "task." + state.removeprefix("TASK_STATE_").lower())
            return True

    def cancel(self, task_id, principal):
        row = self.get(task_id, principal)
        if row["state"] in TERMINAL:
            if row["state"] == "TASK_STATE_CANCELED":
                return
            raise TaskNotCancelableError()
        if not self.transition(task_id, "TASK_STATE_CANCELED", text="Future local work stopped; admitted payment is not refunded."):
            raise TaskNotCancelableError()

    def recover(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM tasks WHERE state IN ('TASK_STATE_WORKING','TASK_STATE_SUBMITTED')")]
        for task_id in ids:
            self.transition(task_id, "TASK_STATE_FAILED", text="Provider restarted. Reconcile any payment before explicitly requesting a new task.", failure="storage")

    def stream_events(self, task_id, after=0):
        with self.connect() as db:
            return [{"seq": r["seq"], "event_id": r["event_id"], "event": json.loads(r["body"])} for r in db.execute(
                "SELECT * FROM task_events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 1000", (task_id, after))]
