"""Pull real MCP tool definitions into real_catalog/<server>.json.

  .venv/bin/python demo/backend/real_catalog/build.py      # re-pull Playwright over stdio

To add another server, call its `tools/list` the same way (stdio or streamable HTTP with your
own credentials) and save {"server", "title", "url", "source", "tools": [...]} next to this file.
"""
import asyncio
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


async def fetch_playwright():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command="npx", args=["-y", "@playwright/mcp@latest", "--browser", "chromium"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.list_tools()
            return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in res.tools]


def main():
    tools = asyncio.run(fetch_playwright())
    out = {"server": "playwright", "title": "Playwright", "url": "npx @playwright/mcp@latest",
           "source": "live tools/list over stdio (@playwright/mcp@latest)", "tools": tools}
    (HERE / "playwright.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"playwright  {len(tools)} tools")


if __name__ == "__main__":
    main()
