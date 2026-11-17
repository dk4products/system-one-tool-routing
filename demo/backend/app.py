"""FastAPI backend for the System One tool-routing demo.

Run:  ./run.sh   (or: cd demo/backend && ../../.venv/bin/uvicorn app:app --port 8000)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from catalog import catalog_summary
from pipeline import SCENARIO_BY_ID, compare, summarize
from scenarios import SCENARIOS
from system_one import STRATEGIES, SystemOneRouter

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="System One tool routing demo")
router = SystemOneRouter()
_state = {"status": "loading", "error": None}


def _load():
    try:
        router.load()
        _state["status"] = "ready"
    except Exception as e:
        _state["status"], _state["error"] = "error", f"{type(e).__name__}: {e}"


@app.on_event("startup")
def startup():
    threading.Thread(target=_load, daemon=True).start()


def _require_ready():
    if not router.ready or _state["status"] != "ready":
        raise HTTPException(503, f"System One model is {_state['status']}: {_state['error'] or 'please wait'}")


class RouteReq(BaseModel):
    prompt: str
    strategy: Optional[str] = None
    top_k: Optional[int] = None


class CompareReq(RouteReq):
    scenario_id: Optional[str] = None
    modes: List[str] = ["baseline", "system_one"]


class BenchReq(BaseModel):
    scenario_ids: Optional[List[str]] = None
    strategy: Optional[str] = None
    top_k: Optional[int] = None


@app.get("/api/health")
def health():
    return {"system_one": _state["status"], "error": _state["error"], "device": router.device,
            "load_ms": round(router.load_ms), "model": config.CLAUDE_MODEL, "region": config.VERTEX_REGION,
            "project": config.VERTEX_PROJECT_ID, "strategies": STRATEGIES,
            "default_strategy": config.DEFAULT_STRATEGY, "default_top_k": config.DEFAULT_TOP_K,
            "price_in": config.PRICE_IN, "price_out": config.PRICE_OUT}


@app.get("/api/catalog")
def catalog():
    return catalog_summary()


@app.get("/api/scenarios")
def scenarios():
    return SCENARIOS


@app.post("/api/route")
def route(req: RouteReq):
    """System One only: no LLM call. Useful to show the decision itself."""
    _require_ready()
    return router.route(req.prompt, strategy=req.strategy, top_k=req.top_k).to_dict()


@app.post("/api/compare")
def compare_ep(req: CompareReq):
    _require_ready()
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    return compare(router, req.prompt, req.strategy, req.top_k, req.scenario_id, tuple(req.modes))


@app.post("/api/benchmark")
def benchmark(req: BenchReq):
    """Streams NDJSON: one line per scenario, then a final summary line."""
    _require_ready()
    ids = req.scenario_ids or [s["id"] for s in SCENARIOS]

    def gen():
        rows = []
        for i, sid in enumerate(ids):
            sc = SCENARIO_BY_ID[sid]
            row = compare(router, sc["prompt"], req.strategy, req.top_k, sid)
            rows.append(row)
            yield json.dumps({"type": "row", "index": i, "total": len(ids), "row": row}) + "\n"
        yield json.dumps({"type": "summary", "summary": summarize(rows)}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
