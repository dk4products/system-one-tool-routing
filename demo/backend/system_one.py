"""System One: Laya-based fast tool routing in front of the LLM.

Given a user request and the full MCP catalog (214 tools: 156 real definitions + 58 mock), decide in ~100-200 ms which
handful of tools the LLM should see, or that no tool is needed at all.

Strategies (measured on the 16 demo scenarios, top-6 recall; see experiment_routing.py):
  * ``tournament`` - pure Laya: tools are judged in groups of 16 in one forward pass, the
                     group winners meet in a final pass.                     15/16
  * ``shortlist``  - bge-small embedding recall to 20 candidates, then one
                     Laya choice over them.                                   15/16
  * ``hybrid``     - reciprocal-rank fusion of both (default).                16/16
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import laya
from sentence_transformers import SentenceTransformer

import config
from catalog import TOOL_BY_NAME, TOOLS

NO_TOOL = "no_tool"
INSTRUCTIONS = "Which tool should the assistant call to handle this request?"
STRATEGIES = ("hybrid", "tournament", "shortlist")


@dataclass
class RankedTool:
    name: str
    server: str
    description: str
    score: float                 # fused or Laya probability, 0..1 (display)
    laya_probability: Optional[float] = None


@dataclass
class RouteDecision:
    strategy: str
    top_k: int
    catalog_size: int
    selected: List[str]                  # qualified tool names passed to the LLM
    ranked: List[RankedTool]
    direct_answer: bool
    confidence: float                    # Laya answer_confidence of the winning label
    timings_ms: Dict[str, float] = field(default_factory=dict)
    forward_passes: int = 0

    def to_dict(self):
        return asdict(self)


class SystemOneRouter:
    def __init__(self):
        self._lock = threading.Lock()
        self.agent = None
        self.encoder = None
        self.device = "unloaded"
        self.load_ms = 0.0
        self.criteria = {t.qualified: f"{t.server} {t.name.replace('_', ' ').strip()}: {t.summary}" for t in TOOLS}
        self.criteria[NO_TOOL] = "no tool needed: greeting, thanks, opinion, or general knowledge answerable directly"

    # ---------------------------------------------------------------------------------
    def load(self):
        t0 = time.perf_counter()
        self.agent = laya.load(config.LAYA_MODEL_PATH, device=config.LAYA_DEVICE)
        self.device = str(getattr(self.agent, "device", "cpu"))
        enc = SentenceTransformer(config.EMBED_MODEL_PATH)
        self.encoder = enc
        self.embed_fn = laya.cached_embed_fn(lambda texts: enc.encode(list(texts), normalize_embeddings=True))
        self.load_ms = (time.perf_counter() - t0) * 1000
        for s in STRATEGIES:                       # warm up kernels (first MPS call compiles)
            self.route("hello, warm up", strategy=s)
        # MPS compiles kernels per input shape; pre-warm the demo prompts so the first live run is
        # representative. Unseen shapes still pay a one-off ~0.3-0.6 s compile.
        from scenarios import SCENARIOS
        for sc in SCENARIOS:
            self.route(sc["prompt"])
        self.load_ms = (time.perf_counter() - t0) * 1000
        return self

    @property
    def ready(self) -> bool:
        return self.agent is not None

    # ---------------------------------------------------------------------------------
    def _question(self, criteria):
        return {"tool": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}}

    def _tournament(self, text):
        t = time.perf_counter()
        r = laya.predict_tournament(self.agent, {"request": text}, self._question(self.criteria), group_size=16)
        ans = r["answers"]["tool"]
        ranked = sorted(ans["probabilities"].items(), key=lambda x: -x[1])
        return ranked, ans, (time.perf_counter() - t) * 1000, r["tournament"]["tool"]["rounds"] + 1

    def _shortlist(self, text, k=20):
        t = time.perf_counter()
        labels = laya.shortlist_choice(text, self.criteria, self.embed_fn, k=k)
        embed_ms = (time.perf_counter() - t) * 1000
        sub = {l: self.criteria[l] for l in labels}
        sub.setdefault(NO_TOOL, self.criteria[NO_TOOL])
        t = time.perf_counter()
        r = self.agent.predict({"request": text}, self._question(sub))
        ans = r["answers"]["tool"]
        ranked = sorted(ans["probabilities"].items(), key=lambda x: -x[1])
        return ranked, ans, embed_ms, (time.perf_counter() - t) * 1000

    # ---------------------------------------------------------------------------------
    def route(self, text: str, strategy: str = None, top_k: int = None) -> RouteDecision:
        strategy = strategy if strategy in STRATEGIES else config.DEFAULT_STRATEGY
        top_k = max(1, min(int(top_k or config.DEFAULT_TOP_K), 20))
        timings: Dict[str, float] = {}
        passes = 0
        t_all = time.perf_counter()
        with self._lock:
            probs: Dict[str, float] = {}
            if strategy in ("tournament", "hybrid"):
                t_rank, t_ans, timings["laya_tournament_ms"], n = self._tournament(text)
                passes += n
                probs.update({l: p for l, p in t_rank})
            if strategy in ("shortlist", "hybrid"):
                s_rank, s_ans, timings["embedding_recall_ms"], timings["laya_choice_ms"] = self._shortlist(text)
                passes += 1
                for l, p in s_rank:
                    probs[l] = max(probs.get(l, 0.0), p)

        if strategy == "tournament":
            order, win_ans = [l for l, _ in t_rank], t_ans
            scores = dict(t_rank)
        elif strategy == "shortlist":
            order, win_ans = [l for l, _ in s_rank], s_ans
            scores = dict(s_rank)
        else:  # reciprocal-rank fusion; the score shown is normalised to the best fused score
            rrf: Dict[str, float] = {}
            for lst in ([l for l, _ in t_rank], [l for l, _ in s_rank]):
                for i, l in enumerate(lst):
                    rrf[l] = rrf.get(l, 0.0) + 1.0 / (60 + i)
            order = [l for l, _ in sorted(rrf.items(), key=lambda x: -x[1])]
            best = rrf[order[0]]
            scores = {l: rrf[l] / best for l in order}
            win_ans = t_ans if t_rank[0][0] == order[0] else s_ans

        confidence = float(win_ans.get("answer_confidence", 0.0))
        # Skipping tools entirely is the riskiest call System One makes, so in hybrid mode both stages
        # must independently put `no_tool` above the threshold (one stage alone misfired on real tools).
        stage_no_tool = []
        if strategy in ("tournament", "hybrid"):
            stage_no_tool.append(dict(t_rank).get(NO_TOOL, 0.0))
        if strategy in ("shortlist", "hybrid"):
            stage_no_tool.append(dict(s_rank).get(NO_TOOL, 0.0))
        direct = order[0] == NO_TOOL and min(stage_no_tool) >= config.DIRECT_ANSWER_THRESHOLD
        tools_only = [l for l in order if l != NO_TOOL]
        selected = [] if direct else tools_only[:top_k]
        ranked = [RankedTool(name=l, server=TOOL_BY_NAME[l].server if l in TOOL_BY_NAME else "-",
                             description=TOOL_BY_NAME[l].description if l in TOOL_BY_NAME else self.criteria[l],
                             score=round(float(scores.get(l, 0.0)), 4),
                             laya_probability=round(float(probs[l]), 4) if l in probs else None)
                  for l in order[: max(top_k + 2, 8)]]
        timings["total_ms"] = (time.perf_counter() - t_all) * 1000
        timings = {k: round(v, 1) for k, v in timings.items()}
        return RouteDecision(strategy=strategy, top_k=top_k, catalog_size=len(TOOLS), selected=selected,
                             ranked=ranked, direct_answer=direct, confidence=round(confidence, 4),
                             timings_ms=timings, forward_passes=passes)
