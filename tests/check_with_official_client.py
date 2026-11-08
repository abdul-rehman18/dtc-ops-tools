"""Connect to the MCP server with the official MCP Python client, the same way an MCP host does.

Not part of the pytest suite because the official client needs Python 3.10 or newer.
    pip install mcp
    python tests/check_with_official_client.py
"""
import asyncio
import pathlib
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = pathlib.Path(__file__).resolve().parents[1] / "dtc_ops" / "mcp_server.py"


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("negotiated:", init.protocol_version, init.server_info.name)
            print("tools:", [t.name for t in (await s.list_tools()).tools])
            res = await s.call_tool("stock_brief", {"offline": True})
            print(res.content[0].text.splitlines()[0])
            res = await s.call_tool("find_fact", {"metric": "suggested_transfer"})
            fid = res.content[0].text.splitlines()[1].split(",")[0]
            print((await s.call_tool("explain_number", {"fact_id": fid})).content[0].text)


asyncio.run(main())
