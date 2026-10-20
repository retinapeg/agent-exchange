"""Independent reference fixture: only the upstream SDK server, no exchange imports.

This is an SDK reference binding check, not a third-party deployed service claim.
"""
import sys
from uuid import uuid4

import uvicorn
from starlette.applications import Starlette
from a2a import types as t
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes


class ReferenceExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        await event_queue.enqueue_event(t.Message(message_id=str(uuid4()), role=t.Role.ROLE_AGENT,
            parts=[t.Part(text="Reference SDK received a structured message.")]))

    async def cancel(self, context, event_queue):
        raise RuntimeError("Immediate-message-only reference fixture")


port = int(sys.argv[1])
card = t.AgentCard(name="upstream-reference", description="SDK immediate message fixture", version="1.0",
    supported_interfaces=[t.AgentInterface(url=f"http://127.0.0.1:{port}/a2a", protocol_binding="JSONRPC", protocol_version="1.0")],
    capabilities=t.AgentCapabilities(streaming=False), default_input_modes=["application/json"], default_output_modes=["text/plain"],
    skills=[t.AgentSkill(id="reference", name="Reference", description="Reference message", tags=["reference"])])
handler = DefaultRequestHandler(ReferenceExecutor(), InMemoryTaskStore(), card)
app = Starlette(routes=create_agent_card_routes(card)+create_jsonrpc_routes(handler, "/a2a"))
uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")
