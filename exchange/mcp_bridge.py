"""Actual MCP stdio server with read-only tools and the observer credential."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from exchange.common import config
from exchange.client import PeerClient


def server():
    app = MCPServer('Agent Exchange observer', instructions='Read-only local development discovery/status. No dispatch, spending or disclosure tools.')
    client = PeerClient(config(), 'observer')
    annotation = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @app.tool(annotations=annotation)
    async def discover(capability: str = '') -> dict:
        """Read configured Agent Cards and their measured freshness; no network scanning."""
        from urllib.parse import quote
        response = await client.http('registry','GET','/agents?capability='+quote(capability, safe=''))
        response.raise_for_status()
        return response.json()

    @app.tool(annotations=annotation)
    async def run_status(run_id: str) -> dict:
        """Read one buyer run's status and verification result without dispatching work."""
        response = await client.http('buyer','GET','/runs')
        response.raise_for_status()
        for run in response.json()['runs']:
            if run['id'] == run_id:
                result = run.get('result') or {}
                return {'run_id':run_id, 'status':run['status'], 'verifier':result.get('verifier'), 'payment':result.get('payment')}
        return {'run_id':run_id,'status':'not-found-in-recent-window'}

    @app.tool(annotations=annotation)
    async def payment_status() -> dict:
        """Read simulator balances and payment states. Cannot authorise or settle."""
        response = await client.http('ledger','GET','/summary')
        response.raise_for_status()
        value = response.json()
        return {k:v for k,v in value.items() if k != 'orders'}
    return app


def run():
    server().run(transport='stdio')
