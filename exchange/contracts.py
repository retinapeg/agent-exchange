"""Validate application scope before execution or payment authorization."""
from fastapi.responses import JSONResponse
from pydantic import ValidationError


def task_schema(task, services):
    if not isinstance(task, dict) or task.get("service") not in services:
        raise ValueError("unsupported task service")
    if set(task) - {"service", "source", "ranges", "submission", "artifact", "profiles", "backend", "quote_id"}:
        raise ValueError("unknown application fields")
    backend = task.get("backend", "fixture")
    if backend not in ("fixture", "live") or (backend == "live" and task["service"] != "requirements"):
        raise ValueError("unsupported service/backend combination")
    if task["service"] in ("requirements", "csv-audit") and (not isinstance(task.get("source"), str) or len(task["source"]) > 64000):
        raise ValueError("source must be a string up to 64000 characters")
    if task["service"] == "csv-audit" and "ranges" in task:
        if not isinstance(task["ranges"], dict) or any(not isinstance(k, str) or not isinstance(v, list) or len(v) != 2 for k, v in task["ranges"].items()):
            raise ValueError("ranges must map columns to two-element bounds")
    if task["service"] == "verify" and (not isinstance(task.get("submission"), dict) or not isinstance(task.get("artifact"), dict)):
        raise ValueError("verification needs submission and artifact objects")
    if task["service"] == "match":
        from exchange.matchmaking import propose
        propose(task.get("profiles"))  # Strict outward schema and bounded cardinality.
    return task


def schema_errors(app):
    @app.exception_handler(ValidationError)
    async def rejected(request, error):
        # Pydantic diagnostics can echo submitted private input; retain only category.
        return JSONResponse({"category": "schema", "error": "invalid_application_schema"}, 422)
