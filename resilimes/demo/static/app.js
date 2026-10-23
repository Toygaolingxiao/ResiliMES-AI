const JOB_COLORS = {
  "LOT-1001": "#3ecf8e",
  "LOT-1002": "#8eb6ff",
  "LOT-1003": "#f0b429",
  "LOT-1004": "#d7a1ff",
  "LOT-1005": "#ff8f8f",
  "LOT-1006": "#7ee0d6",
  "LOT-2001": "#ffd27a",
};

const state = { scenario: "litho_down", report: null };

const scenariosEl = document.querySelector("#scenarios");
const runButton = document.querySelector("#run");
const statusEl = document.querySelector("#status");
const incidentEl = document.querySelector("#incident");

runButton.addEventListener("click", () => {
  const incident = incidentEl.value.trim();
  if (incident) run({ incident });
  else run({ scenario: state.scenario });
});

document.addEventListener("DOMContentLoaded", init);

async function init() {
  const health = await getJson("/api/health");
  paintMode(health);
  const payload = await getJson("/api/scenarios");
  paintScenarios(payload.scenarios);
  await run({ scenario: "litho_down" });
}

function paintMode(health) {
  const badge = document.querySelector("#mode-badge");
  const banner = document.querySelector("#banner");
  const mock = health.llm === "mock" || health.data === "sample";
  badge.textContent = health.label;
  badge.className = mock ? "badge mock" : "badge live";
  document.querySelector("#clock").textContent = `Scenario clock ${formatClock(health.horizon)} UTC`;
  if (health.llm === "mock" && health.data === "sample") {
    banner.hidden = false;
    banner.textContent =
      "Offline mock — schedules, the critic, and the Meterless engines are real; Nightshift and Zetaris are not called. Add credentials and run without RESILIMES_MODE=mock to go live. Secrets are never shown.";
  } else {
    banner.hidden = false;
    banner.textContent = `Live path: data ${health.data}, model lane ${health.nemotron_model}. Secrets stay in the environment.`;
  }
}

function paintScenarios(items) {
  scenariosEl.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scenario" + (item.id === state.scenario ? " active" : "");
    button.innerHTML = `<strong>${item.title}</strong><span>${item.summary}</span>`;
    button.addEventListener("click", () => {
      state.scenario = item.id;
      incidentEl.value = "";
      for (const node of scenariosEl.querySelectorAll(".scenario")) node.classList.remove("active");
      button.classList.add("active");
      run({ scenario: item.id });
    });
    scenariosEl.appendChild(button);
  }
}

async function run(body) {
  runButton.disabled = true;
  statusEl.textContent = "Scout, specialist, planner, and critic are running…";
  try {
    const report = await postJson("/api/recover", body);
    state.report = report;
    render(report);
    statusEl.textContent = report.blocked
      ? "Request refused."
      : `${report.verdict ? report.verdict.verdict : "done"} · ${report.mode.label}`;
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    runButton.disabled = false;
  }
}

function render(report) {
  document.querySelector("#empty").hidden = true;
  const result = document.querySelector("#result");
  result.hidden = false;
  document.querySelector("#clock").textContent = `Scenario clock ${formatClock(report.horizon)} UTC`;
  document.querySelector("#narrative").textContent = report.narrative || "";
  document.querySelector("#before-label").textContent = report.before_label;
  document.querySelector("#after-label").textContent = report.after_label;
  renderKpis(report);
  const scale = scaleOf(report);
  renderGantt(document.querySelector("#gantt-before"), report.gantt && report.gantt.before, report.horizon, scale);
  renderGantt(document.querySelector("#gantt-after"), report.gantt && report.gantt.after, report.horizon, scale);
  renderLots(report.outcomes || []);
  renderDecision(report);
  renderTrace(report.trace || []);
}

function renderKpis(report) {
  const host = document.querySelector("#kpis");
  host.innerHTML = "";
  if (!report.kpis) {
    host.innerHTML = `<article class="kpi"><p class="label">No schedule</p><p class="value">—</p><p class="delta flat">${escapeHtml(report.block_reason || "Read only")}</p></article>`;
    return;
  }
  const cards = [
    ["On-time delivery", "on_time_delivery_pct", "%", 1, true],
    ["Weighted tardiness", "weighted_tardiness_min", " min", 0, false],
    ["Makespan", "makespan_min", " min", 0, false],
    ["Lots at risk", "lots_at_risk", "", 0, false],
  ];
  for (const [label, key, suffix, digits, upGood] of cards) {
    const before = report.kpis.before[key];
    const after = report.kpis.after[key];
    const delta = report.kpis.delta[key];
    const improved = upGood ? delta > 0.05 : delta < -0.05;
    const worse = upGood ? delta < -0.05 : delta > 0.05;
    const tone = improved ? "good" : worse ? "bad" : "flat";
    const sign = delta > 0 ? "+" : "";
    const article = document.createElement("article");
    article.className = "kpi";
    article.innerHTML = `
      <p class="label">${label}</p>
      <p class="value">${Number(after).toFixed(digits)}${suffix}</p>
      <p class="delta ${tone}">${sign}${Number(delta).toFixed(digits)}${suffix}</p>
      <p class="delta flat">was ${Number(before).toFixed(digits)}${suffix}</p>`;
    host.appendChild(article);
  }
}

function renderGantt(host, gantt, horizon, scale) {
  host.innerHTML = "";
  if (!gantt) {
    host.innerHTML = `<p class="delta flat">No chart for this result.</p>`;
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "gantt";
  for (const row of gantt.rows) {
    const line = document.createElement("div");
    line.className = "gantt-row";
    const label = document.createElement("div");
    label.className = "gantt-label";
    label.innerHTML = `${row.equipment_id}<small>${row.status}</small>`;
    const track = document.createElement("div");
    track.className = "track";
    if (row.available_at_min > 0) {
      const shade = document.createElement("div");
      shade.className = "shade";
      shade.style.left = "0";
      shade.style.width = `${(row.available_at_min / scale) * 100}%`;
      track.appendChild(shade);
    }
    for (const bar of row.bars) {
      const node = document.createElement("div");
      node.className = "bar";
      node.style.left = `${(bar.start_min / scale) * 100}%`;
      node.style.width = `${Math.max(1.2, ((bar.end_min - bar.start_min) / scale) * 100)}%`;
      node.style.background = JOB_COLORS[bar.job_id] || "#d7f5e8";
      node.title = `${bar.job_id} ${bar.step} ${bar.start_min}–${bar.end_min} min`;
      node.textContent = `${bar.job_id} ${bar.step}`;
      track.appendChild(node);
    }
    line.append(label, track);
    wrap.appendChild(line);
  }
  const axis = document.createElement("div");
  axis.className = "axis";
  for (let minute = 0; minute <= scale; minute += Math.max(60, Math.round(scale / 4 / 60) * 60)) {
    const tick = document.createElement("span");
    tick.textContent = formatClock(shift(horizon, minute)).slice(11, 16);
    axis.appendChild(tick);
  }
  host.append(wrap, axis);
}

function renderLots(rows) {
  const body = document.querySelector("#lots");
  body.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    const tardy = `${row.before_tardiness_min} → ${row.after_tardiness_min}`;
    tr.innerHTML = `
      <td>${row.job_id}</td>
      <td>${row.priority}</td>
      <td>${row.before_equipment || "—"}</td>
      <td>${row.after_equipment || "held"}</td>
      <td class="${row.after_tardiness_min < row.before_tardiness_min ? "good" : row.after_tardiness_min > row.before_tardiness_min ? "bad" : ""}">${tardy}</td>`;
    body.appendChild(tr);
  }
}

function renderDecision(report) {
  const host = document.querySelector("#decision");
  const verdict = report.verdict ? report.verdict.verdict : report.blocked ? "blocked" : "—";
  const rejected = report.rejected_alternative && report.rejected_alternative.critique;
  const violation = rejected && rejected.violations && rejected.violations[0];
  const contract = report.contract;
  host.innerHTML = `
    <p><span class="pill">${escapeHtml(verdict)}</span>
      ${contract ? `<span class="pill">contract verified</span>` : ""}</p>
    <p>${escapeHtml(report.verdict ? report.verdict.rationale : report.narrative)}</p>
    ${violation ? `<p>Rejected alternative · ${escapeHtml(violation.constraint)}: ${escapeHtml(violation.detail)}</p>` : ""}
    ${contract ? `<p class="evidence">Profile ${escapeHtml(contract.modelProfile)} · ${escapeHtml(contract.contractId)}</p>` : ""}
    ${report.provider_call ? `<p class="evidence">Explainer ${escapeHtml(report.provider_call.provider)} · ${escapeHtml(report.provider_call.model)} · ${Math.round(report.provider_call.latency_ms)} ms${report.provider_call.mocked ? " · mock" : ""}</p>` : ""}`;
}

function renderTrace(events) {
  const list = document.querySelector("#trace");
  list.innerHTML = "";
  for (const event of events) {
    const item = document.createElement("li");
    const evidence = (event.evidence || []).slice(0, 2).map((line) => `<div class="evidence">${escapeHtml(line)}</div>`).join("");
    item.innerHTML = `<div class="agent">${escapeHtml(event.agent)}</div><div><h3>${escapeHtml(event.title)}</h3><p>${escapeHtml(event.summary)}</p>${evidence}</div>`;
    list.appendChild(item);
  }
}

function scaleOf(report) {
  let max = 240;
  for (const side of [report.gantt && report.gantt.before, report.gantt && report.gantt.after]) {
    if (!side) continue;
    for (const row of side.rows) {
      max = Math.max(max, row.available_at_min || 0);
      for (const bar of row.bars) max = Math.max(max, bar.end_min);
    }
  }
  return Math.ceil(max / 60) * 60;
}

function shift(horizon, minutes) {
  return new Date(Date.parse(horizon) + minutes * 60000).toISOString();
}

function formatClock(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "").slice(0, 16);
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
