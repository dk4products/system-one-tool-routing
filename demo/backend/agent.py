"""Claude (on Vertex AI) tool-use agent, built on the Anthropic SDK.

The same loop runs in both modes; only the tool list differs:
  * baseline   - every MCP tool in the catalog is sent on every turn
  * system_one - only the tools System One selected, plus a `request_more_tools`
                 escape hatch that upgrades the next turn to the full catalog if the
                 shortlist was wrong (counted as an "escalation").
"""
from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

from anthropic import AnthropicVertex

import config
from catalog import SERVERS, TOOL_BY_NAME, TOOLS, execute_tool

ESCALATE = "request_more_tools"
ESCALATE_SPEC = {
    "name": ESCALATE,
    "description": ("Load additional MCP tools when the tools you currently have are not the right fit "
                    "for the request (wrong system, or the needed operation such as search/read/create is "
                    "missing). Available MCP servers: "
                    + "; ".join(f"{s.name} ({s.description})" for s in SERVERS)
                    + ". The requested servers' tools become available on your next step."),
    "input_schema": {"type": "object", "properties": {
        "servers": {"type": "array", "items": {"type": "string", "enum": [s.name for s in SERVERS]},
                    "description": "MCP servers whose tools you need"},
        "reason": {"type": "string", "description": "What capability is missing"}},
        "required": ["servers", "reason"]},
}

SYSTEM = ("You are an enterprise assistant connected to company systems through MCP tools. "
          "Use a tool whenever the request needs live company data or an action; answer directly "
          "only for general questions. Tool results in this demo are simulated sample data. "
          "Keep the final answer to at most 3 short sentences.")

ROUTED_NOTE = (" Your tools were pre-selected for this request by a fast router and may be incomplete. "
               "If the best tool for the job is not among them, call request_more_tools first rather than "
               "making do with a near-fit tool.")


@lru_cache(maxsize=1)
def client() -> AnthropicVertex:
    if not config.VERTEX_PROJECT_ID:
        raise RuntimeError("VERTEX_PROJECT_ID is not set: copy .env.example to .env and set your GCP project")
    return AnthropicVertex(project_id=config.VERTEX_PROJECT_ID, region=config.VERTEX_REGION)


def all_specs() -> List[Dict[str, Any]]:
    return [t.anthropic_spec() for t in TOOLS]


def specs_for(names: List[str]) -> List[Dict[str, Any]]:
    return [TOOL_BY_NAME[n].anthropic_spec() for n in names if n in TOOL_BY_NAME]


@lru_cache(maxsize=512)
def _count_tool_tokens(key: str) -> int:
    """Tokens consumed by the tool definitions alone (count_tokens with vs. without tools)."""
    names = json.loads(key)
    tools = all_specs() if names == ["*"] else specs_for([n for n in names if n != ESCALATE])
    if ESCALATE in names:
        tools = tools + [ESCALATE_SPEC]
    msgs = [{"role": "user", "content": "x"}]
    try:
        with_tools = client().messages.count_tokens(model=config.CLAUDE_MODEL, system=SYSTEM,
                                                    messages=msgs, tools=tools).input_tokens if tools else None
        without = client().messages.count_tokens(model=config.CLAUDE_MODEL, system=SYSTEM,
                                                 messages=msgs).input_tokens
        return (with_tools - without) if tools else 0
    except Exception:
        return round(len(json.dumps(tools)) / 3.6)  # fallback estimate when count_tokens is unavailable


def tool_definition_tokens(names: Optional[List[str]]) -> int:
    key = json.dumps(["*"] if names is None else sorted(names))
    return _count_tool_tokens(key)


def cost_usd(inp: int, out: int) -> float:
    return inp / 1e6 * config.PRICE_IN + out / 1e6 * config.PRICE_OUT


def run_agent(prompt: str, tool_names: Optional[List[str]], allow_escalation: bool = False) -> Dict[str, Any]:
    """Run the tool loop. `tool_names=None` means the full catalog (baseline)."""
    full = tool_names is None
    tools = all_specs() if full else specs_for(tool_names)
    if allow_escalation:
        tools = tools + [ESCALATE_SPEC]
    sent_names = ["*"] if full else list(tool_names) + ([ESCALATE] if allow_escalation else [])

    messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
    turns, calls = [], []
    escalated = False
    escalated_servers: List[str] = []
    system = SYSTEM + (ROUTED_NOTE if allow_escalation else "")
    final_text = ""
    t_start = time.perf_counter()
    first_decision_ms = None
    tool_def_tokens_total = 0
    error = None

    try:
        for turn in range(config.MAX_TURNS):
            kw = dict(model=config.CLAUDE_MODEL, max_tokens=config.MAX_TOKENS, system=system, messages=messages)
            if tools:
                kw["tools"] = tools
            t = time.perf_counter()
            resp = client().messages.create(**kw)
            ms = (time.perf_counter() - t) * 1000
            if first_decision_ms is None:
                first_decision_ms = ms
            used = [b for b in resp.content if b.type == "tool_use"]
            turns.append({"turn": turn + 1, "latency_ms": round(ms, 1),
                          "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                          "tools_offered": len(tools), "_names": [s["name"] for s in tools],
                          "stop_reason": resp.stop_reason, "tool_calls": [b.name for b in used]})
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
            if resp.stop_reason != "tool_use" or not used:
                final_text = "".join(b.text for b in resp.content if b.type == "text").strip()
                break
            results = []
            for b in used:
                if b.name == ESCALATE:
                    escalated = True
                    wanted = [s for s in (b.input.get("servers") or []) if any(x.name == s for x in SERVERS)]
                    have = {s["name"] for s in tools}
                    extra = [t.anthropic_spec() for t in TOOLS
                             if (not wanted or t.server in wanted) and t.qualified not in have]
                    tools = tools + extra
                    escalated_servers.extend(wanted or ["*"])
                    out = json.dumps({"ok": True, "loaded_tools": [s["name"] for s in extra]})
                else:
                    out = execute_tool(b.name, b.input)
                    calls.append({"tool": b.name, "input": b.input})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            messages.append({"role": "user", "content": results})
        else:
            final_text = final_text or "(stopped: reached max agent turns)"
    except Exception as e:  # surface auth / quota problems to the UI instead of a 500
        error = f"{type(e).__name__}: {e}"

    wall_ms = (time.perf_counter() - t_start) * 1000
    # Token cost of the tool definitions per turn, measured outside the timed section.
    for t in turns:
        names = t.pop("_names")
        t["tool_definition_tokens"] = (tool_definition_tokens(None if set(names) == set(TOOL_BY_NAME) else names)
                                       if names else 0)
        tool_def_tokens_total += t["tool_definition_tokens"]

    inp = sum(t["input_tokens"] for t in turns)
    out = sum(t["output_tokens"] for t in turns)
    return {
        "answer": final_text,
        "error": error,
        "tools_sent": len(TOOLS) if full else len(sent_names),
        "tool_names_sent": sent_names,
        "tool_calls": calls,
        "escalated": escalated,
        "escalated_servers": escalated_servers,
        "llm_calls": len(turns),
        "turns": turns,
        "input_tokens": inp,
        "output_tokens": out,
        "tool_definition_tokens": tool_def_tokens_total,
        "cost_usd": round(cost_usd(inp, out), 6),
        "first_decision_ms": round(first_decision_ms or 0.0, 1),
        "llm_ms": round(sum(t["latency_ms"] for t in turns), 1),
        "wall_ms": round(wall_ms, 1),
    }
