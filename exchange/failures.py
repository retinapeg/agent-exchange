"""Stable application failure categories, separate from A2A task states."""
import sqlite3
import httpx
import jsonschema

CATEGORIES = {"transport", "authentication", "version", "schema", "provider",
              "task-quality", "verification", "payment", "storage", "policy"}


class RpcFailure(RuntimeError):
    def __init__(self, error):
        self.code = error.get("code")
        self.category = {-32009: "version", -32602: "schema", -32600: "schema", -32601: "version"}.get(self.code, "provider")
        super().__init__(error)


class ExchangeFailure(ValueError):
    def __init__(self, category, message):
        if category not in CATEGORIES:
            raise ValueError("unknown failure category")
        self.category = category
        super().__init__(message)


def category(error):
    if isinstance(error, RpcFailure):
        return error.category
    if isinstance(error, ExchangeFailure):
        return error.category
    if isinstance(error, sqlite3.Error):
        return "storage"
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return "authentication" if status in (401, 403) else "payment" if status == 402 else "transport"
    if isinstance(error, (httpx.TransportError, OSError, TimeoutError)):
        return "transport"
    if isinstance(error, (jsonschema.ValidationError, KeyError, TypeError)):
        return "schema"
    if isinstance(error, ValueError):
        return "policy"
    return "provider"
