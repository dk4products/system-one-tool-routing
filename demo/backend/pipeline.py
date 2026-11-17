"""Side-by-side pipeline: the same request with and without System One in front of Claude."""
from __future__ import annotations

import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import config
from agent import run_agent
from scenarios import SCENARIOS
from system_one import SystemOneRouter

SCENARIO_BY_ID = {s["id"]: s for s in SCENARIOS}
_pool = ThreadPoolExecutor(max_workers=8)


def _judge(expected: Optional[List[str]], calls: List[Dict[str, Any]]) -> Optional[bool]:
    if expected is None:
        return None
    called = {c["tool"] for c in calls}
    return not called if not expected else bool(called & set(expected))


def _pct(new: float, old: float) -> Optional[float]:
    return None if not old else round((new - old) / old * 100, 1)


def compare(router: SystemOneRouter, prompt: str, strategy: str = None, top_k: int = None,
            scenario_id: str = None, modes=("baseline", "system_one")) -> Dict[str, Any]:
    expected = SCENARIO_BY_ID[scenario_id]["expected"] if scenario_id in SCENARIO_BY_ID else None

    baseline_f = _pool.submit(run_agent, prompt, None, False) if "baseline" in modes else None
    out: Dict[str, Any] = {"prompt": prompt, "scenario_id": scenario_id, "expected": expected,
                           "model": config.CLAUDE_MODEL}

    if "system_one" in modes:
        decision = router.route(prompt, strategy=strategy, top_k=top_k)
        routed = run_agent(prompt, decision.selected, allow_escalation=True)
        routed["system_one_ms"] = decision.timings_ms["total_ms"]
        routed["total_ms"] = round(routed["wall_ms"] + routed["system_one_ms"], 1)
        routed["first_decision_ms"] = round(routed["first_decision_ms"] + routed["system_one_ms"], 1)
        routed["correct"] = _judge(expected, routed["tool_calls"])
        out["route"] = decision.to_dict()
        out["system_one"] = routed
    if baseline_f:
        base = baseline_f.result()
        base["system_one_ms"] = 0.0
        base["total_ms"] = base["wall_ms"]
        base["correct"] = _judge(expected, base["tool_calls"])
        out["baseline"] = base

    if "baseline" in out and "system_one" in out:
        b, s = out["baseline"], out["system_one"]
        out["delta"] = {
            "input_tokens_pct": _pct(s["input_tokens"], b["input_tokens"]),
            "tool_definition_tokens_pct": _pct(s["tool_definition_tokens"], b["tool_definition_tokens"]),
            "total_ms_pct": _pct(s["total_ms"], b["total_ms"]),
            "cost_pct": _pct(s["cost_usd"], b["cost_usd"]),
            "tools_sent_pct": _pct(s["tools_sent"], b["tools_sent"]),
            "input_tokens_saved": b["input_tokens"] - s["input_tokens"],
            "cost_saved_usd": round(b["cost_usd"] - s["cost_usd"], 6),
            "ms_saved": round(b["total_ms"] - s["total_ms"], 1),
        }
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def agg(mode):
        rs = [r[mode] for r in rows if mode in r and not r[mode].get("error")]
        if not rs:
            return None
        judged = [r["correct"] for r in rs if r.get("correct") is not None]
        return {
            "runs": len(rs),
            "accuracy": round(sum(judged) / len(judged), 4) if judged else None,
            "correct": sum(judged), "judged": len(judged),
            "avg_input_tokens": round(statistics.mean(r["input_tokens"] for r in rs)),
            "avg_output_tokens": round(statistics.mean(r["output_tokens"] for r in rs)),
            "avg_tool_definition_tokens": round(statistics.mean(r["tool_definition_tokens"] for r in rs)),
            "avg_tools_sent": round(statistics.mean(r["tools_sent"] for r in rs), 1),
            "p50_total_ms": round(statistics.median(r["total_ms"] for r in rs), 1),
            "p50_first_decision_ms": round(statistics.median(r["first_decision_ms"] for r in rs), 1),
            "p50_system_one_ms": round(statistics.median(r["system_one_ms"] for r in rs), 1),
            "avg_cost_usd": round(statistics.mean(r["cost_usd"] for r in rs), 6),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rs), 6),
            "escalations": sum(1 for r in rs if r.get("escalated")),
        }
    b, s = agg("baseline"), agg("system_one")
    out = {"baseline": b, "system_one": s, "n": len(rows), "model": config.CLAUDE_MODEL}
    if b and s:
        out["delta"] = {
            "input_tokens_pct": _pct(s["avg_input_tokens"], b["avg_input_tokens"]),
            "p50_total_ms_pct": _pct(s["p50_total_ms"], b["p50_total_ms"]),
            "cost_pct": _pct(s["avg_cost_usd"], b["avg_cost_usd"]),
            "accuracy_pts": (round((s["accuracy"] - b["accuracy"]) * 100, 1)
                             if s["accuracy"] is not None and b["accuracy"] is not None else None),
        }
    return out
