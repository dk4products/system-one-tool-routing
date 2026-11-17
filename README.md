# System One tool routing: Laya in front of Claude

Agent harnesses that connect many MCP servers send every tool definition to the LLM on every
turn. This demo puts a **System One** model, [Laya](https://github.com/NandhaKishorM/laya),
in front of the LLM. Laya is a local, non-autoregressive decision model that answers in one
forward pass. It decides in about 150 ms which few tools the request needs, and Claude only
sees those. The UI runs every request both ways and compares tokens, latency, cost and
tool-choice accuracy.

```
user request ──► System One (Laya, local, ~150 ms, 0 tokens) ──► top-6 tools + escape hatch ──► Claude on Vertex ──► answer
                        106 tools / 14 MCP servers in                          (vs. all 106 tools in the baseline)
```

## Setup (fresh clone)

`laya/`, `models/`, `.venv/` and `.env` are not in git (about 3.7 GB, re-created below).

```bash
git clone https://github.com/NandhaKishorM/laya.git                # System One library
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ./laya fastapi "uvicorn[standard]" "anthropic[vertex]" sentence-transformers python-dotenv mcp
.venv/bin/python -c "from huggingface_hub import snapshot_download as d; d('convaiinnovations/laya', local_dir='models/laya'); d('BAAI/bge-small-en-v1.5', local_dir='models/bge-small-en-v1.5')"
ln -sfn laya/multilingual models/laya-multilingual; ln -sfn laya/typed-decisions models/laya-typed-decisions
(cd laya && ../.venv/bin/python verify/laya_smoke_test.py --models ../models)   # optional sanity check
cp .env.example .env                                                 # adjust Vertex project / model if needed
```

| Path | What |
|---|---|
| `laya/` | Laya repo clone (installed editable into `.venv`) |
| `models/laya/` | Laya checkpoints (English, multilingual, typed-decisions), about 2.2 GB |
| `models/bge-small-en-v1.5/` | Small embedding model used for recall in the hybrid strategy |
| `.env` | Vertex project, region, model, prices, routing defaults |

## Quick start

```bash
gcloud auth application-default login     # Claude on Vertex uses your ADC
./run.sh                                  # http://localhost:8000
```

The first start takes about 15 s: it loads Laya onto MPS and pre-warms it. The status chip
turns green when it's ready.

## Using the demo

- **Leader view** (default) shows the headline numbers: token, cost and latency deltas,
  accuracy, and an annual projection with a requests-per-day slider.
- **Engineer view** adds:
  - the strategy and top-K controls
  - System One's ranked decision with Laya probabilities and per-stage timings
  - per-turn token and latency tables
  - tool-definition token counts, measured with Vertex `count_tokens`
- **Live comparison** runs one request through both pipelines at the same time.
- **Benchmark** runs 20 graded scenarios (40 agent runs) and streams the results.
- **Tool catalog** lists the 14 MCP servers and their 106 tools, each labelled real or mock.

## Tool catalog

**106 tools on 14 servers.** **Playwright** (25 tools) is a real MCP server: its `tools/list` is pulled live over
stdio by `demo/backend/real_catalog/build.py`. The other 13 servers (81 tools) are hand-written mocks:
GitHub, Jira, Confluence, Slack, BigQuery, Cloud Storage, Calendar, Outlook, ServiceNow, Datadog/PagerDuty,
Connected Vehicle, Filesystem and Web. Tool *execution* is simulated for every tool, so the demo never touches a real
system. To make the numbers representative, replace mocks with your own servers' real `tools/list` output.
Real definitions are usually several times heavier than these mocks, so the token savings grow.

## Measuring

Run the **Benchmark** tab, or call the API directly:

```bash
curl -sN -XPOST localhost:8000/api/benchmark -H 'content-type: application/json' -d '{}' > results.ndjson
```

Each line holds one scenario with both modes' tokens, latency, cost and correctness. The last line is the summary.
For a routing-only experiment with no LLM cost, run `cd demo/backend && ../../.venv/bin/python experiment_routing.py`.
It reports top-1 and top-6 recall for each strategy: a flat Laya choice, embedding only, `shortlist`, `tournament`
and `hybrid`.

## How it works (`demo/backend`)

| File | Role |
|---|---|
| `catalog.py` | Merges real servers (`real_catalog/*.json`) and mock servers (`mock_catalog.py`) into one catalog; `execute_tool` returns simulated payloads for both. |
| `real_catalog/` | Real MCP tool definitions (`<server>.json`). `build.py` re-pulls Playwright over stdio; add your own servers the same way. |
| `system_one.py` | `SystemOneRouter`. Each tool becomes a Laya `choice` option, plus a `no_tool` option. The `tournament` strategy uses `laya.predict_tournament`; `shortlist` uses bge recall followed by `agent.predict`; `hybrid` fuses the two. Returns the top-K tools, or none when `no_tool` wins with high confidence. |
| `agent.py` | Claude tool-use loop on `AnthropicVertex`. Every routed run also gets a `request_more_tools(servers=[...])` escape hatch. The hatch lists every server in one line, so if the shortlist misses, Claude can load the right server's tools mid-run. |
| `pipeline.py` | Runs baseline and routed side by side, grades tool calls against the scenarios, and aggregates the benchmark. |
| `app.py` | FastAPI: `/api/health`, `/api/catalog`, `/api/scenarios`, `/api/route` (System One only, no LLM), `/api/compare`, `/api/benchmark` (NDJSON stream). |
| `scenarios.py` | The 20 graded requests. |

Design choices worth calling out:

1. **Shortlist, not a single pick.** Zero-shot Laya puts the correct tool first only about
   80% of the time, but it lands in the top 6 almost always. Claude still makes the final
   choice from a short, relevant list.
2. **A safety net instead of blind trust.** The `request_more_tools` escape hatch, together
   with a system-prompt note that the tools were pre-selected, turned the one routing miss
   into a correct answer in testing. Without the note, Claude settled for a near-fit tool. This is the
   most important harness lesson in the demo.
3. **Direct answers need agreement.** Claude gets only the escape hatch when *both* stages put `no_tool` at ≥ 0.70.
   One stage alone can mistake a terse document-search request for small talk.

## Honest caveats

- **The escape hatch loads whole servers.** Escalating to a large server, such as one with 70+ tools, adds all of
  its definitions, so the savings for that request shrink. Hierarchical escalation (server → tool group), or a
  second System One pass inside the server, would fix it.
- **Real descriptions are harder for Laya.** Laya only reads about 10–20 tokens per option, and many real tools
  open with near-identical text ("Get…", "List…"). The embedding stage carries more of the weight on the real
  catalog, and fine-tuning on routing logs is the obvious next step.

- **Latency is flat at this catalog size.** Claude's time is dominated by per-call
  overhead and output generation, not by reading the tool definitions. The latency win grows
  with larger catalogs (hundreds of tools) or with smaller and faster models. Cost and
  context savings appear right away.
- **MPS compiles kernels per input shape.** Laya's p50 is about 165 ms, but a first-seen
  prompt length can take 0.3–0.6 s once. CPU on this Mac is about 1 s. A CUDA GPU runs about
  35 ms per question (see `laya/BENCHMARKS.md`).
- **Prompt caching is off in both modes.** Caching would cut the baseline's cost for a
  static tool list. It doesn't fix accuracy dilution or context pressure, and it doesn't
  help when the tool set changes per user.
- **The checkpoints are zero-shot.** For production, fine-tune or calibrate on your own
  routing logs. Laya supports `fit()` and temperature calibration. Then re-check the
  thresholds.
- **The sample is small.** Twenty scenarios is a demo, not an evaluation. Extend
  `scenarios.py` with real traffic before quoting the numbers.
- **The other systems are simulated.** MCP tool results are mocked. Only Laya and Claude
  are real.
