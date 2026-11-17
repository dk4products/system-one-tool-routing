"""Enterprise MCP tool catalog: real servers plus labelled mocks.

REAL (definitions exactly as the server publishes them; execution is still simulated):
  * playwright  25 tools   @playwright/mcp, pulled live over stdio (real_catalog/build.py --live)
MOCK: 13 hand-written servers in mock_catalog.py (GitHub, Jira, Confluence, Slack, BigQuery, ...).

Add more real servers by dropping their `tools/list` output into real_catalog/<name>.json and
listing them in REAL_ORDER / REAL_SERVER_DESCRIPTIONS. Tool calls never reach a real system:
`execute_tool` returns simulated payloads for both real and mock tools.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import mock_catalog

REAL_DIR = Path(__file__).resolve().parent / "real_catalog"

REAL_SERVER_DESCRIPTIONS = {
    "playwright": "Playwright browser automation: open web pages, click, type, fill forms, take screenshots and "
                  "accessibility snapshots, read console and network",
}
REAL_ORDER = ["playwright"]


@dataclass
class Tool:
    server: str
    name: str
    description: str
    schema: Dict[str, Any]
    real: bool
    sample: Any = None

    @property
    def qualified(self) -> str:
        return f"{self.server}__{self.name}"

    @property
    def summary(self) -> str:
        """First paragraph of the description, used by System One (Laya reads ~10-20 tokens per option)."""
        first = self.description.strip().split("\n\n")[0].replace("\n", " ")
        return first[:240]

    def anthropic_spec(self) -> Dict[str, Any]:
        schema = dict(self.schema or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        return {"name": self.qualified, "description": f"[{self.server} MCP] {self.description}",
                "input_schema": schema}


@dataclass
class Server:
    name: str
    title: str
    description: str
    real: bool
    source: str
    tools: List[Tool] = field(default_factory=list)


def _load_real() -> List[Server]:
    out = []
    for name in REAL_ORDER:
        f = REAL_DIR / f"{name}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        s = Server(name, d.get("title", name), REAL_SERVER_DESCRIPTIONS[name], True, d.get("source", ""))
        s.tools = [Tool(name, t["name"], t.get("description") or "", t.get("inputSchema") or {}, True)
                   for t in d["tools"]]
        out.append(s)
    return out


def _load_mock() -> List[Server]:
    out = []
    for ms in mock_catalog.SERVERS:
        s = Server(ms.name, ms.title, ms.description, False, "hand-written mock (no MCP server connected)")
        s.tools = [Tool(ms.name, t.name, t.description, t.input_schema(), False, t.sample) for t in ms.tools]
        out.append(s)
    return out


SERVERS: List[Server] = _load_real() + _load_mock()
TOOLS: List[Tool] = [t for s in SERVERS for t in s.tools]
TOOL_BY_NAME: Dict[str, Tool] = {t.qualified: t for t in TOOLS}
SERVER_BY_NAME: Dict[str, Server] = {s.name: s for s in SERVERS}
assert len(TOOL_BY_NAME) == len(TOOLS), "duplicate qualified tool names"

# Simulated payloads for the real tools the demo scenarios exercise. Every other real tool gets a
# generic simulated success, so a run never drives a real browser.
REAL_SAMPLES: Dict[str, Any] = {
    "playwright__browser_navigate": {"url": "https://status.example.com", "title": "Service status",
                                     "snapshot": "- heading \"All systems operational\""},
    "playwright__browser_snapshot": {"snapshot": "- heading \"All systems operational\""},
    "playwright__browser_take_screenshot": {"saved": "page-1763290000.png"},
}


def execute_tool(qualified: str, args: Dict[str, Any]) -> str:
    """Simulated MCP `tools/call`. Never contacts a real system."""
    tool = TOOL_BY_NAME.get(qualified)
    if tool is None:
        return json.dumps({"error": f"unknown tool {qualified}"})
    if not tool.real:
        result = tool.sample
    else:
        result = REAL_SAMPLES.get(qualified, {"status": "ok", "message": f"{tool.name} completed (simulated)."})
    return json.dumps({"server": tool.server, "tool": tool.name, "simulated": True, "result": result}, default=str)


def catalog_summary() -> Dict[str, Any]:
    return {"servers": [{"name": s.name, "title": s.title, "description": s.description, "real": s.real,
                         "source": s.source, "tools": [t.name for t in s.tools]} for s in SERVERS],
            "tool_count": len(TOOLS), "server_count": len(SERVERS),
            "real_tool_count": sum(t.real for t in TOOLS), "real_server_count": sum(s.real for s in SERVERS)}
