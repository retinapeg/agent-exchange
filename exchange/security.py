from __future__ import annotations

import hmac
import ipaddress
import json
import time
import re
from urllib.parse import urlsplit

import httpx
from starlette.responses import JSONResponse

from exchange.common import MAX_BODY


class NetworkPolicy:
    """Exact origins. No wildcard private-network exception, redirects or env proxies."""
    def __init__(self, origins, local=True):
        self.origins = frozenset(origins)
        self.local = local
        for origin in self.origins:
            p = urlsplit(origin)
            if p.username or p.password or p.path or p.query or p.fragment or not p.port:
                raise ValueError("origin must have explicit port and no path or credentials")
            try:
                addr = ipaddress.ip_address(p.hostname)
            except ValueError:
                raise ValueError("Use pinned IP origins; DNS rebinding is not supported") from None
            if local:
                if not addr.is_loopback or p.scheme != "http":
                    raise ValueError("Local mode permits only configured literal loopback origins")
            elif p.scheme != "https" or not addr.is_global:
                raise ValueError("Remote mode requires public HTTPS origins and validated TLS")

    def check(self, url):
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.origins or p.username or p.password or p.fragment:
            raise ValueError("Destination is not allowlisted")
        if "%" in p.path or ".." in p.path.split("/") or "\\" in p.path:
            raise ValueError("Unsafe path")
        return url

    async def request(self, method, url, *, token=None, limit=MAX_BODY, **kwargs):
        self.check(url)
        headers = {"A2A-Version": "1.0", **kwargs.pop("headers", {})}
        if token:
            headers["Authorization"] = "Bearer " + token
        async with httpx.AsyncClient(timeout=130, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, headers=headers, **kwargs) as response:
                if 300 <= response.status_code < 400:
                    raise ValueError("Redirects are forbidden")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ValueError("Response exceeds size limit")
                return httpx.Response(response.status_code, headers=response.headers, content=bytes(body), request=response.request)


class Guard:
    """ASGI body bounds and per-receiver credentials, before SDK parsing."""
    def __init__(self, app, peer, public=(), store=None, public_prefixes=(), quiet_prefixes=()):
        self.app, self.peer, self.store = app, peer, store
        self.public = frozenset(public) | {"/health", "/.well-known/agent-card.json"}
        self.public_prefixes = public_prefixes
        self.quiet_prefixes = tuple(quiet_prefixes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin")
        expected = self.peer["url"]
        if headers.get("host") != urlsplit(expected).netloc or (origin and origin != expected):
            return await JSONResponse({"error": "origin_or_host_denied"}, 403)(scope, receive, send)
        principal = None
        auth = headers.get("authorization", "").removeprefix("Bearer ")
        for p, token in self.peer["tokens"].items():
            if hmac.compare_digest(auth, token):
                principal = p
        scope.setdefault("state", {})["principal"] = principal
        if scope["path"] not in self.public and not any(scope['path'].startswith(p) for p in self.public_prefixes) and principal is None:
            return await JSONResponse({"error": "authentication_required"}, 401)(scope, receive, send)
        body = bytearray()
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body.extend(msg.get("body", b""))
            if len(body) > MAX_BODY:
                return await JSONResponse({"error": "payload_too_large"}, 413)(scope, receive, send)
            if not msg.get("more_body", False):
                break
        received = False
        if body and "application/json" in headers.get("content-type", ""):
            try:
                json.loads(body)
            except (ValueError, UnicodeDecodeError, RecursionError):
                return await JSONResponse({"error": "invalid_json"}, 400)(scope, receive, send)
        async def replay():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        status = None
        async def secured_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message['status']
                message.setdefault("headers", []).extend([(b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store")])
            await send(message)
        from exchange.tracing import trace_scope
        from exchange.common import digest
        safe_id = lambda value: value if value and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) else None
        with trace_scope(safe_id(headers.get('x-trace-id')), parent_id=safe_id(headers.get('x-parent-span'))) as context:
            scope['state']['trace'] = context
            # Reading observation endpoints must not manufacture more observed traffic.
            recorded = self.store and scope['path'] not in ('/health','/observe','/snapshot','/','/app.js','/style.css','/.well-known/agent-card.json') \
                and not (self.quiet_prefixes and scope['method'] == 'GET' and scope['path'].startswith(self.quiet_prefixes))
            fields = {**context, 'method':scope['method'], 'path':scope['path'][:180]}
            started = time.monotonic()
            if recorded:
                self.store.event('http.received', principal or 'local-client', self.peer['id'], input_hash=digest(bytes(body)), **fields)
            try:
                return await self.app(scope, replay, secured_send)
            finally:
                if recorded:
                    self.store.event('http.finished', self.peer['id'], principal or 'local-client',
                        latency_ms=round((time.monotonic()-started)*1000), http_status=status, disposition='response' if status else 'disconnected', **fields)
