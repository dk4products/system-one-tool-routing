/* System One tool-routing demo: vanilla JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const state = { scenarios: [], scenarioId: null, health: null, bench: null, catalog: null };

/* ---------- formatting ---------- */
const fmtInt = n => (n == null ? "–" : Math.round(n).toLocaleString());
const fmtMs = ms => (ms == null ? "–" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`);
const fmtUsd = v => {
  if (v == null) return "–";
  if (v === 0) return "$0";
  if (Math.abs(v) < 0.01) return `$${v.toFixed(4)}`;
  if (Math.abs(v) < 1) return `$${v.toFixed(3)}`;
  if (Math.abs(v) < 100) return `$${v.toFixed(2)}`;
  return `$${Math.round(v).toLocaleString()}`;
};
const fmtPct = p => (p == null ? "–" : `${p > 0 ? "+" : ""}${p.toFixed(0)}%`);
const cls = (p, lowerIsBetter = true) => (p == null ? "" : (lowerIsBetter ? p < 0 : p > 0) ? "good" : p === 0 ? "" : "bad");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const short = n => n.replace("__", " · ");

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r;
}

/* ---------- boot ---------- */
async function boot() {
  $$("#view-toggle button").forEach(b => b.onclick = () => {
    $$("#view-toggle button").forEach(x => x.classList.toggle("active", x === b));
    document.body.className = `view-${b.dataset.view}`;
  });
  $$("#tabs button").forEach(b => b.onclick = () => {
    $$("#tabs button").forEach(x => x.classList.toggle("active", x === b));
    $$(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${b.dataset.tab}`));
  });
  $("#run-btn").onclick = runCompare;
  $("#bench-btn").onclick = runBenchmark;
  $("#prompt").addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runCompare(); });
  $("#prompt").addEventListener("input", () => { state.scenarioId = null; markChip(); });

  const [cat, sc] = await Promise.all([api("/api/catalog").then(r => r.json()), api("/api/scenarios").then(r => r.json())]);
  state.catalog = cat; state.scenarios = sc;
  $("#hero-tools").textContent = cat.tool_count; $("#hero-servers").textContent = cat.server_count;
  $("#hero-real").textContent = cat.real_tool_count; $("#hero-mock").textContent = cat.tool_count - cat.real_tool_count;
  $("#bench-count").textContent = sc.length; $("#bench-calls").textContent = sc.length * 2;
  renderCatalog(cat); renderScenarioChips(sc);
  pollHealth();
}

async function pollHealth() {
  try {
    const h = await api("/api/health").then(r => r.json());
    state.health = h;
    const sel = $("#strategy");
    if (!sel.options.length) {
      h.strategies.forEach(s => sel.add(new Option(s, s, s === h.default_strategy, s === h.default_strategy)));
      $("#topk").value = h.default_top_k;
    }
    const s1 = h.system_one === "ready" ? `ok">System One ready · ${esc(h.device)}`
      : h.system_one === "error" ? `err">System One error` : `wait">Loading System One…`;
    $("#status-chips").innerHTML = `<span class="chip ${s1}</span>` +
      `<span class="chip ok"><span class="dot"></span>${esc(h.model)} · Vertex ${esc(h.region)}</span>`;
    $("#status-chips .chip").insertAdjacentHTML("afterbegin", '<span class="dot"></span>');
    if (h.system_one !== "ready" && h.system_one !== "error") setTimeout(pollHealth, 1500);
  } catch { setTimeout(pollHealth, 2000); }
}

function renderScenarioChips(sc) {
  $("#scenario-chips").innerHTML = sc.map(s =>
    `<button data-id="${s.id}" class="${s.real ? "real" : ""}" title="${esc(s.persona)}${s.real ? " · real MCP tool" : " · mock MCP tool"}">${esc(s.prompt.length > 46 ? s.prompt.slice(0, 44) + "…" : s.prompt)}</button>`).join("");
  $$("#scenario-chips button").forEach(b => b.onclick = () => {
    const s = sc.find(x => x.id === b.dataset.id);
    $("#prompt").value = s.prompt; state.scenarioId = s.id; markChip();
  });
}
const markChip = () => $$("#scenario-chips button").forEach(b => b.classList.toggle("active", b.dataset.id === state.scenarioId));

function renderCatalog(cat) {
  $("#servers").innerHTML = cat.servers.map(s => `
    <div class="card server ${s.real ? "is-real" : ""}"><h4>${esc(s.title)} <span class="muted" style="font-weight:400">· ${s.tools.length} tools</span>
      <span class="pill ${s.real ? "real" : "mock"}">${s.real ? "real" : "mock"}</span></h4>
    <p>${esc(s.description)}</p><p class="src">${esc(s.source)}</p>${s.tools.map(t => `<span class="t">${esc(t)}</span>`).join("")}</div>`).join("");
}

/* ---------- live comparison ---------- */
async function runCompare() {
  const prompt = $("#prompt").value.trim();
  if (!prompt) { $("#prompt").focus(); return; }
  const btn = $("#run-btn");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Running both…';
  try {
    const res = await api("/api/compare", {
      prompt, scenario_id: state.scenarioId, strategy: $("#strategy").value, top_k: +$("#topk").value,
    }).then(r => r.json());
    renderLive(res);
  } catch (e) {
    $("#live-empty").classList.remove("hidden"); $("#live-result").classList.add("hidden");
    $("#live-empty").innerHTML = `<span class="verdict no">Error</span> ${esc(e.message)}`;
  } finally { btn.disabled = false; btn.textContent = "Run comparison"; }
}

function verdict(c) {
  return c === true ? '<span class="verdict ok">Correct tool</span>'
    : c === false ? '<span class="verdict no">Wrong / missed tool</span>' : '<span class="verdict na">Not graded</span>';
}

function renderLive(r) {
  $("#live-empty").classList.add("hidden"); $("#live-result").classList.remove("hidden");
  const b = r.baseline, s = r.system_one, d = r.delta, rt = r.route;
  const total = state.catalog.tool_count;

  $("#pipeline").innerHTML = [
    `<div class="pipe-step"><div class="k">Request</div><div class="v">${total} tools available</div><div class="s">${state.catalog.server_count} MCP servers · ${state.catalog.real_tool_count} real definitions</div></div>`,
    `<div class="pipe-step s1"><div class="k">System One · Laya (local)</div><div class="v">${rt.direct_answer ? "No tool needed" : `${total} → ${rt.selected.length} tools`}</div><div class="s">decided in ${fmtMs(rt.timings_ms.total_ms)} · ${rt.forward_passes} forward passes · 0 tokens</div></div>`,
    `<div class="pipe-step"><div class="k">Claude on Vertex</div><div class="v">${fmtInt(s.input_tokens)} input tokens</div><div class="s">${s.llm_calls} LLM call${s.llm_calls === 1 ? "" : "s"}${s.escalated ? ` · loaded more tools (${esc(s.escalated_servers.join(", "))})` : ""}</div></div>`,
    `<div class="pipe-step"><div class="k">Answer</div><div class="v">${fmtMs(s.total_ms)}</div><div class="s">${s.correct === true ? "correct tool used" : s.correct === false ? "check tool choice" : "end to end"}</div></div>`,
  ].join('<div class="pipe-arrow">→</div>');

  $("#live-kpis").innerHTML = [
    kpi("Input tokens sent to Claude", fmtPct(d.input_tokens_pct), cls(d.input_tokens_pct), `${fmtInt(b.input_tokens)} → ${fmtInt(s.input_tokens)}`),
    kpi("End-to-end latency", fmtPct(d.total_ms_pct), cls(d.total_ms_pct), `${fmtMs(b.total_ms)} → ${fmtMs(s.total_ms)}`),
    kpi("Cost per request", fmtPct(d.cost_pct), cls(d.cost_pct), `${fmtUsd(b.cost_usd)} → ${fmtUsd(s.cost_usd)}`),
    kpi("Tools Claude had to read", `${b.tools_sent} → ${s.tools_sent}`, "good", `incl. 1 escape-hatch tool · picked in ${fmtMs(rt.timings_ms.total_ms)}`),
  ].join("");

  $("#card-baseline").innerHTML = modeCard("Without System One", "All tools → Claude", b);
  $("#card-routed").innerHTML = modeCard("With System One", "Laya shortlist → Claude", s);
  $("#decision-card").innerHTML = decisionCard(rt);
}

const kpi = (label, big, c, sub) => `<div class="kpi"><div class="label">${label}</div><div class="big ${c}">${big}</div><div class="sub">${sub}</div></div>`;
const metric = (k, v) => `<div class="metric"><span>${k}</span><span>${v}</span></div>`;

function modeCard(title, tag, m) {
  const turns = m.turns.map(t => `<tr><td>${t.turn}</td><td class="num">${t.tools_offered}</td><td class="num">${fmtInt(t.tool_definition_tokens)}</td>
      <td class="num">${fmtInt(t.input_tokens)}</td><td class="num">${fmtInt(t.output_tokens)}</td><td class="num">${fmtMs(t.latency_ms)}</td>
      <td>${t.tool_calls.map(c => `<span class="call">${esc(short(c))}</span>`).join(" ") || `<span class="muted">${esc(t.stop_reason)}</span>`}</td></tr>`).join("");
  return `
    <h3>${title} <span class="tag">${tag}</span></h3>
    <div style="display:flex;gap:6px;flex-wrap:wrap">${verdict(m.correct)}${m.escalated ? `<span class="verdict escal">Escape hatch used: loaded ${esc((m.escalated_servers || []).join(", "))} tools</span>` : ""}</div>
    <div class="metrics">
      ${metric("Tools sent", m.tools_sent)}
      ${metric("Input tokens", fmtInt(m.input_tokens))}
      ${metric("Output tokens", fmtInt(m.output_tokens))}
      ${metric("Cost", fmtUsd(m.cost_usd))}
      ${metric("End-to-end", fmtMs(m.total_ms))}
      ${metric("Time to first tool decision", fmtMs(m.first_decision_ms))}
      <div class="eng-only">${metric("Tool-definition tokens", fmtInt(m.tool_definition_tokens))}</div>
      <div class="eng-only">${metric("LLM calls · System One", `${m.llm_calls} · ${fmtMs(m.system_one_ms)}`)}</div>
    </div>
    <div class="calls">${m.tool_calls.map(c => `<span class="call" title="${esc(JSON.stringify(c.input))}">${esc(short(c.tool))}</span>`).join("") || '<span class="muted" style="font-size:12px">No tools called</span>'}</div>
    <div class="answer ${m.error ? "err" : ""}">${esc(m.error || m.answer || "(no answer)")}</div>
    <table class="turns eng-only"><thead><tr><th>Turn</th><th class="num">Tools</th><th class="num">Tool-def tok</th>
      <th class="num">In tok</th><th class="num">Out tok</th><th class="num">Latency</th><th>Called</th></tr></thead><tbody>${turns}</tbody></table>`;
}

function decisionCard(rt) {
  const sel = new Set(rt.selected);
  const t = Object.entries(rt.timings_ms).map(([k, v]) => `<span class="chip">${esc(k.replace(/_ms$/, "").replace(/_/g, " "))}: ${fmtMs(v)}</span>`).join("");
  const rows = rt.ranked.map((x, i) => `
    <div class="rank ${sel.has(x.name) ? "sel" : ""}"><span class="n">${i + 1}</span><span class="nm">${esc(short(x.name))}</span>
    <div class="barwrap" title="${esc(x.description)}"><div class="bar" style="width:${Math.max(2, x.score * 100)}%"></div></div>
    <span class="pct">${x.laya_probability != null ? (x.laya_probability * 100).toFixed(1) + "%" : "–"}</span></div>`).join("");
  return `<h3>System One decision <span class="muted" style="font-weight:400">· strategy <b>${esc(rt.strategy)}</b>, top-${rt.top_k} of ${rt.catalog_size}${rt.direct_answer ? " · direct answer, no tools" : ""}</span></h3>
    <div class="timing">${t}<span class="chip">winner confidence: ${(rt.confidence * 100).toFixed(1)}%</span></div>
    <div class="muted" style="font-size:12px;margin-bottom:6px">Bar = rank score (fused for hybrid). Right column = Laya probability. Highlighted rows were sent to Claude.</div>
    ${rows}`;
}

/* ---------- benchmark ---------- */
async function runBenchmark() {
  const btn = $("#bench-btn");
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Running…';
  $("#bench-progress").classList.remove("hidden"); $("#bench-bar").style.width = "0";
  $("#bench-table-card").classList.remove("hidden"); $("#bench-summary").classList.add("hidden");
  const tbody = $("#bench-table tbody"); tbody.innerHTML = "";
  try {
    const r = await api("/api/benchmark", { strategy: $("#strategy").value, top_k: +$("#topk").value });
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        const msg = JSON.parse(line);
        if (msg.type === "row") {
          $("#bench-bar").style.width = `${((msg.index + 1) / msg.total) * 100}%`;
          $("#bench-label").textContent = `${msg.index + 1} / ${msg.total}`;
          tbody.insertAdjacentHTML("beforeend", benchRow(msg.row));
        } else if (msg.type === "summary") { state.bench = msg.summary; renderBenchSummary(msg.summary); }
      }
    }
  } catch (e) {
    tbody.insertAdjacentHTML("beforeend", `<tr><td colspan="7"><span class="verdict no">Error</span> ${esc(e.message)}</td></tr>`);
  } finally { btn.disabled = false; btn.textContent = "Run benchmark again"; }
}

function arrow(a, b, f) {
  const p = a ? ((b - a) / a) * 100 : 0;
  return `${f(a)} <span class="arrow">→</span> ${f(b)} <span class="${p < 0 ? "down" : "up"}">${fmtPct(p)}</span>`;
}
function benchRow(r) {
  const b = r.baseline, s = r.system_one;
  const ok = c => c ? "✓" : "✗";
  const sc = state.scenarios.find(x => x.id === r.scenario_id);
  return `<tr><td>${sc ? `<span class="pill ${sc.real ? "real" : "mock"}">${sc.real ? "real" : "mock"}</span> ` : ""}${esc(r.prompt)}</td><td class="mono">${(r.expected || []).map(short).slice(0, 1).join("") || "none (chat)"}</td>
    <td class="num">${arrow(b.input_tokens, s.input_tokens, fmtInt)}</td>
    <td class="num">${arrow(b.total_ms, s.total_ms, fmtMs)}</td>
    <td class="num">${arrow(b.cost_usd, s.cost_usd, fmtUsd)}</td>
    <td>${b.error || s.error ? '<span class="verdict no">error</span>' : `${ok(b.correct)} → ${ok(s.correct)}${s.escalated ? ' <span class="verdict escal">esc</span>' : ""}`}</td>
    <td class="mono eng-only">${(r.route.direct_answer ? ["(no tool)"] : r.route.selected.slice(0, 3).map(short)).join("<br>")}</td></tr>`;
}

function renderBenchSummary(sm) {
  const b = sm.baseline, s = sm.system_one, d = sm.delta;
  if (!b || !s) return;
  $("#bench-summary").classList.remove("hidden");
  $("#bench-kpis").innerHTML = [
    kpi("Tool-selection accuracy", `${(s.accuracy * 100).toFixed(0)}%`, s.accuracy >= b.accuracy ? "good" : "bad",
      `all tools: ${(b.accuracy * 100).toFixed(0)}% (${b.correct}/${b.judged}) · System One: ${s.correct}/${s.judged}`),
    kpi("Avg input tokens / request", fmtPct(d.input_tokens_pct), cls(d.input_tokens_pct), `${fmtInt(b.avg_input_tokens)} → ${fmtInt(s.avg_input_tokens)}`),
    kpi("p50 end-to-end latency", fmtPct(d.p50_total_ms_pct), cls(d.p50_total_ms_pct), `${fmtMs(b.p50_total_ms)} → ${fmtMs(s.p50_total_ms)} (incl. ${fmtMs(s.p50_system_one_ms)} System One)`),
    kpi("Cost per 1,000 requests", fmtPct(d.cost_pct), cls(d.cost_pct), `${fmtUsd(b.avg_cost_usd * 1000)} → ${fmtUsd(s.avg_cost_usd * 1000)}`),
  ].join("");

  const bar = (label, bv, sv, f) => {
    const mx = Math.max(bv, sv) || 1;
    return `<div class="cmp"><div class="lbl"><span>${label}</span></div>
      <div class="row"><span class="muted">All tools</span><div class="track"><div class="fill b" style="width:${(bv / mx) * 100}%"></div></div><span class="val">${f(bv)}</span></div>
      <div class="row"><span class="muted">System One</span><div class="track"><div class="fill s" style="width:${(sv / mx) * 100}%"></div></div><span class="val">${f(sv)}</span></div></div>`;
  };
  $("#bench-bars").innerHTML = `<h3>Side by side</h3>
    <div class="legend"><span><i style="background:var(--base)"></i>All ${state.catalog.tool_count} tools → Claude</span><span><i style="background:var(--s1)"></i>System One → Claude</span></div>
    ${bar("Avg input tokens per request", b.avg_input_tokens, s.avg_input_tokens, fmtInt)}
    ${bar("of which: tool definitions", b.avg_tool_definition_tokens, s.avg_tool_definition_tokens, fmtInt)}
    ${bar("p50 end-to-end latency", b.p50_total_ms, s.p50_total_ms, fmtMs)}
    ${bar("p50 time to first tool decision", b.p50_first_decision_ms, s.p50_first_decision_ms, fmtMs)}
    ${bar("Avg cost per request", b.avg_cost_usd, s.avg_cost_usd, fmtUsd)}
    <div class="muted" style="font-size:12px">Escape-hatch escalations (Claude loaded extra servers): ${s.escalations} of ${s.runs}. Model: ${esc(sm.model)}.</div>`;
  renderProjection();
}

function renderProjection() {
  const sm = state.bench; if (!sm) return;
  const el = $("#projection");
  el.innerHTML = `<div class="proj"><h3>What it means at scale</h3>
    <label>Agent requests per day: <span class="vol" id="vol-label"></span></label>
    <input type="range" min="0" max="100" value="33.4" step="0.1" id="vol" />
    <div class="rows" id="proj-rows"></div>
    <div class="note">Projected from this benchmark's averages at list price ($${state.health.price_in}/M input tokens,
    $${state.health.price_out}/M output tokens), with prompt caching off in both modes. Caching lowers the cost of a static tool list,
    but it doesn't fix tool-choice accuracy as catalogs grow, it doesn't relieve context-window pressure, and it stops helping
    once the tool set varies by user or session. System One runs locally and adds no token cost.</div></div>`;
  const update = () => {
    const raw = 1000 * Math.pow(10, $("#vol").value / 100 * 3);  // 1k .. 1M per day, log scale
    const mag = Math.pow(10, Math.floor(Math.log10(raw)) - 1);
    const vol = Math.round(raw / mag) * mag;
    const b = sm.baseline, s = sm.system_one, yr = v => v * vol * 365;
    const hours = (b.p50_total_ms - s.p50_total_ms) * vol * 365 / 3.6e6;
    $("#vol-label").textContent = vol.toLocaleString();
    $("#proj-rows").innerHTML = `
      <div class="r"><span>Annual LLM cost, all tools sent</span><b>${fmtUsd(yr(b.avg_cost_usd))}</b></div>
      <div class="r"><span>Annual LLM cost, with System One</span><b>${fmtUsd(yr(s.avg_cost_usd))}</b></div>
      <div class="r"><span>Input tokens avoided per year</span><b>${fmtInt(yr(b.avg_input_tokens - s.avg_input_tokens) / 1e6)} M</b></div>
      <div class="r"><span>User wait time ${hours >= 0 ? "saved" : "added"} per year</span><b>${fmtInt(Math.abs(hours))} hours</b></div>
      <div class="r total"><span>Annual savings</span><span>${fmtUsd(yr(b.avg_cost_usd - s.avg_cost_usd))}</span></div>`;
  };
  $("#vol").oninput = update; update();
}

boot();
