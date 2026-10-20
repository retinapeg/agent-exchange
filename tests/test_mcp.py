import sys
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from exchange.common import ROOT, DATA, write_json, uid


async def test_real_mcp_stdio_handshake_list_and_read():
    params = StdioServerParameters(command=sys.executable,args=['-m','exchange.cli','mcp'],cwd=str(ROOT),env={'EXCHANGE_DATA_DIR':str(DATA)})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            assert {t.name for t in listed.tools} == {'discover','run_status','payment_status'}
            assert all(t.annotations.read_only_hint for t in listed.tools)
            result = await session.call_tool('discover',{'capability':'requirements'})
            assert not result.is_error
            missing = await session.call_tool('run_status',{'run_id':'nonexistent'})
            assert not missing.is_error
            forbidden = await session.call_tool('dispatch',{})
            assert forbidden.is_error
            write_json(DATA/'receipts'/('mcp-stdio-'+uid()+'.json'), {'initialization':init.model_dump(by_alias=True),'tools':[t.model_dump(by_alias=True) for t in listed.tools],'discovery':result.model_dump(by_alias=True),'unsupported_dispatch_rejected':forbidden.is_error})
