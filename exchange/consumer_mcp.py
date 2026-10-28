"""Owner-scoped MCP stdio client for the Agent Exchange consumer service.

Web sign-up is required first. The assistant can only STAGE a profile draft; a
human must approve its fields through the browser before matchmaking begins.
"""
import os
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations


def build_server():
    base = os.getenv('AGENT_EXCHANGE_URL', 'http://127.0.0.1:8715').rstrip('/')
    token = os.getenv('AGENT_EXCHANGE_TOKEN', '')
    if not token:
        raise RuntimeError('Set AGENT_EXCHANGE_TOKEN to a personal key created in your Agent Exchange account')
    app = MCPServer('Agent Exchange Matchmaking', instructions=(
        'Help the authenticated user join a human collaboration matching pool. '
        'Never include raw chat history or sensitive attributes. '
        'Draft only short outward profile tags you actually know, and show them to the user. '
        'Call preview_profile before stage_profile. Staging DOES NOT grant human consent; '
        'the user must open their Agent Exchange webpage and explicitly approve the profile. '
        'Only read the authenticated user\'s own match.'))
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                           idempotent_hint=True, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                            idempotent_hint=False, open_world_hint=False)

    async def request(method, path, payload=None):
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.request(method, base + path, json=payload,
                                          headers={'Authorization': 'Bearer ' + token})
            result.raise_for_status()
            return result.json()

    @app.tool(annotations=read)
    async def get_profile_schema() -> dict:
        """Learn the six permitted profile fields. Never send chat transcripts or sensitive information."""
        return await request('GET', '/api/schema')

    @app.tool(annotations=read)
    async def preview_profile(profile: dict, approved_fields: list[str]) -> dict:
        """Show exactly which short context fields would be shared. No profile is stored."""
        return await request('POST', '/api/preview', {'profile': profile, 'approved_fields': approved_fields})

    @app.tool(annotations=write)
    async def stage_profile(profile: dict, approved_fields: list[str]) -> dict:
        """Save a DRAFT for human browser review, not consent and not activation. Ask the user to approve it in their browser."""
        return await request('POST', '/api/drafts', {'profile': profile, 'approved_fields': approved_fields})

    @app.tool(annotations=read)
    async def my_match_status() -> dict:
        """Read only this owner's profile/match status, score and non-sensitive explanation."""
        return await request('GET', '/api/me')

    return app


def run():
    build_server().run(transport='stdio')


if __name__ == '__main__':
    run()
