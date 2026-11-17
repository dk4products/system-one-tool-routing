"""Offline routing-strategy experiment (no LLM). Measures top-1 and top-K recall of each strategy."""
import os
import sys
import time

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import laya  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

from catalog import SERVERS, TOOLS  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
agent = laya.load(os.path.join(ROOT, "models", "laya"))
enc = SentenceTransformer(os.path.join(ROOT, "models", "bge-small-en-v1.5"))
embed_fn = laya.cached_embed_fn(lambda t: enc.encode(list(t), normalize_embeddings=True))

criteria = {t.qualified: f"{t.server} {t.name.replace('_', ' ').strip()}: {t.summary}" for t in TOOLS}
NONE = "no_tool"
crit_none = dict(criteria, **{NONE: "no tool needed: greeting, thanks, or general knowledge answerable directly"})
K = 6


def topk(probs, k=K):
    return [l for l, _ in sorted(probs.items(), key=lambda x: -x[1])[:k]]


def flat(q):
    r = agent.predict({"request": q}, {"tool": {"type": "choice", "instructions": "Which tool handles the request?",
                                                 "criteria": crit_none}}, max_len=1024, head_max_len=512)
    return topk(r["answers"]["tool"]["probabilities"])


def shortlist(q, k=20):
    labels = laya.shortlist_choice(q, crit_none, embed_fn, k=k)
    sub = {l: crit_none[l] for l in labels}
    if NONE not in sub:
        sub[NONE] = crit_none[NONE]
    r = agent.predict({"request": q}, {"tool": {"type": "choice", "instructions": "Which tool handles the request?",
                                                 "criteria": sub}})
    return topk(r["answers"]["tool"]["probabilities"])


def embed_only(q):
    return laya.shortlist_choice(q, crit_none, embed_fn, k=K)


def tournament(q):
    r = laya.predict_tournament(agent, {"request": q}, {"tool": {"type": "choice",
                                "instructions": "Which tool handles the request?", "criteria": crit_none}},
                                group_size=16)
    return topk(r["answers"]["tool"]["probabilities"])


srv_crit = {s.name: f"{s.title}: {s.description}" for s in SERVERS}
srv_crit[NONE] = "no tool needed: greeting, thanks, or general knowledge answerable directly"


def hierarchical(q):
    r = agent.predict({"request": q}, {"server": {"type": "choice",
                      "instructions": "Which system or MCP server is needed for this request?", "criteria": srv_crit}})
    sp = r["answers"]["server"]["probabilities"]
    ranked = sorted(sp.items(), key=lambda x: -x[1])
    picked, cum = [], 0.0
    for name, p in ranked:
        picked.append(name)
        cum += p
        if cum >= 0.9 or len(picked) >= 3:
            break
    if picked[0] == NONE and sp[NONE] > 0.6:
        return [NONE]
    sub = {t.qualified: criteria[t.qualified] for t in TOOLS if t.server in picked}
    r2 = agent.predict({"request": q}, {"tool": {"type": "choice", "instructions": "Which tool handles the request?",
                                                  "criteria": sub}})
    return topk(r2["answers"]["tool"]["probabilities"])


strategies = {"flat85": flat, "embed_only": embed_only, "shortlist20": shortlist,
              "tournament": tournament, "hierarchical": hierarchical}
for fn in strategies.values():
    fn("warm up")
for name, fn in strategies.items():
    h1 = hk = 0
    ts = []
    misses = []
    for sc in SCENARIOS:
        exp = set(sc["expected"]) or {NONE}
        t = time.perf_counter()
        out = fn(sc["prompt"])
        ts.append((time.perf_counter() - t) * 1000)
        h1 += out[0] in exp
        hit = bool(exp & set(out))
        hk += hit
        if not hit:
            misses.append((sc["id"], out[:3]))
    print(f"{name:13s} top1={h1}/{len(SCENARIOS)} top{K}={hk}/{len(SCENARIOS)} p50={np.median(ts):.0f}ms")
    for m in misses:
        print("    miss", m)


def fused(q, k=K):
    a = tournament(q) + [None] * 0
    b = shortlist(q)
    score = {}
    for lst in (a, b):
        for i, l in enumerate(lst):
            score[l] = score.get(l, 0) + 1.0 / (60 + i)
    return [l for l, _ in sorted(score.items(), key=lambda x: -x[1])][:k]


print("--- variants")
for name, fn, kk in [("tournament@8", tournament, 8), ("shortlist@8", shortlist, 8), ("fused@6", fused, 6),
                     ("fused@8", fused, 8)]:
    h1 = hk = 0
    for sc in SCENARIOS:
        exp = set(sc["expected"]) or {NONE}
        out = fn(sc["prompt"])[:kk]
        h1 += out[0] in exp
        hk += bool(exp & set(out))
        if not exp & set(out):
            print("    miss", name, sc["id"], out[:3])
    print(f"{name:13s} top1={h1} topk={hk}/{len(SCENARIOS)}")
