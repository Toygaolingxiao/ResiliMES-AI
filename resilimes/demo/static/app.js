const AREA_TONE = {
  light: {
    Lithography: { fill: "#dbe1fb", ink: "#1e1b4b" },
    Etch: { fill: "#cff4f6", ink: "#0c4a4e" },
    CMP: { fill: "#e6d9f7", ink: "#3b0764" },
    Deposition: { fill: "#d4f3e8", ink: "#064e3b" },
    Metrology: { fill: "#fde7c7", ink: "#7c4a03" },
    Clean: { fill: "#d7e6f5", ink: "#1e3a5f" },
  },
  dark: {
    Lithography: { fill: "#312e81", ink: "#e0e7ff" },
    Etch: { fill: "#155e75", ink: "#cffafe" },
    CMP: { fill: "#5b21b6", ink: "#f3e8ff" },
    Deposition: { fill: "#115e59", ink: "#ccfbf1" },
    Metrology: { fill: "#92400e", ink: "#ffedd5" },
    Clean: { fill: "#1e3a5f", ink: "#e0f2fe" },
  },
};

function areaTone(area) {
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const table = AREA_TONE[theme];
  return table[area] || table.Deposition;
}

const STEPS = [
  ["detect", ["scout", "contract"], "stepDetect"],
  ["data", ["query", "sense"], "stepData"],
  ["plan", ["plan"], "stepPlan"],
  ["check", ["critique"], "stepCheck"],
  ["explain", ["explain"], "stepExplain"],
  ["save", ["commit"], "stepSave"],
];

const KEY_CARDS = [
  ["on_time_delivery_pct", "kpiOtd", "%", 1, "otdTip", "dot"],
  ["weighted_tardiness_min", "kpiTardy", "dur", 0, "tardyTip", "bar"],
  ["lots_at_risk", "kpiRisk", "", 0, "riskTip", "ring"],
];

const ANALYZE_KEYS = [
  ["on_time_delivery_pct", "kpiOtd", "%", 1, "otdTip"],
  ["weighted_tardiness_min", "kpiTardy", "dur", 0, "tardyTip"],
  ["makespan_min", "kpiSpan", "dur", 0, "spanTip"],
  ["mean_lead_min", "kpiLead", "dur", 0, "leadTip"],
  ["mean_wait_min", "kpiWait", "dur", 0, "waitTip"],
  ["mean_x_factor", "kpiX", "x", 2, "xTip"],
  ["utilization_pct", "kpiUtil", "%", 1, "utilTip"],
  ["setup_changes", "kpiChange", "", 0, "changeTip"],
  ["lots_at_risk", "kpiRisk", "", 0, "riskTip"],
];

let COPY = { en: {}, zh: {}, ja: {} };
const ALERT = {
  litho_down: "LITHO-02",
  rush_order: "LITHO-01",
  material_shortage: "RESIST-UV",
  rework: "LOT-1004",
  qtime: "DEP-01",
};

const state = {
  lang: localStorage.getItem("resilimes.lang") || "en",
  theme: localStorage.getItem("resilimes.theme") === "dark" ? "dark" : "light",
  view: "tool",
  tab: "recover",
  routeJob: "",
  activeScenario: "",
  report: null,
  steps: [],
  horizon: "",
  health: null,
  bay: [],
  overview: null,
  scenarioItems: [],
  running: false,
  incidentText: "",
  utilSide: "after",
};

const $ = (id) => document.querySelector(id);

document.addEventListener("DOMContentLoaded", init);

async function init() {
  COPY = await getJson("/assets/i18n.json");
  state.health = await getJson("/api/health");
  state.horizon = state.health.horizon;
  const payload = await getJson("/api/scenarios");
  state.scenarioItems = payload.scenarios;
  state.bay = payload.bay || [];
  state.overview = payload.overview || null;
  applyTheme();
  paint();
  $("#theme").addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
    paint();
  });
  $("#version").addEventListener("click", (event) => {
    event.stopPropagation();
    const note = $("#note");
    note.hidden = !note.hidden;
    if (!note.hidden) {
      const rect = event.currentTarget.getBoundingClientRect();
      note.style.left = `${rect.left}px`;
      note.style.top = `${rect.bottom + 6}px`;
    }
  });
  $("#run-custom").addEventListener("click", () => {
    const incident = $("#incident").value.trim();
    if (incident) run({ incident });
  });
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.addEventListener("click", () => {
      state.lang = button.getAttribute("data-lang");
      localStorage.setItem("resilimes.lang", state.lang);
      paint();
    });
  });
  document.addEventListener("click", (event) => {
    const route = $("#route");
    if (route && !route.hidden && !(event.target.closest && event.target.closest("#route, .bar"))) closeRoute();
    const note = $("#note");
    if (note && !note.hidden && !(event.target.closest && event.target.closest("#note, #version"))) note.hidden = true;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeRoute();
      $("#note").hidden = true;
    }
  });
}

function applyTheme() {
  if (state.theme === "dark") document.documentElement.dataset.theme = "dark";
  else delete document.documentElement.dataset.theme;
  localStorage.setItem("resilimes.theme", state.theme);
}

function t() {
  return COPY[state.lang] || COPY.en;
}

function taglineFor(copy) {
  const id = (state.report && state.report.scenario_id) || state.activeScenario || "";
  if (id === "scale") return copy.taglineScale;
  if (id && copy.scenarios && copy.scenarios[id]) return copy.scenarios[id][0];
  return copy.taglineIdle;
}

function paint() {
  const copy = t();
  document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang === "ja" ? "ja" : "en";
  $("#tagline").textContent = taglineFor(copy);
  $("#version").textContent = state.health && state.health.version ? state.health.version : "";
  $("#note").textContent = copy.versionNote;
  $("#lang-label").textContent = copy.lang;
  $("#disruption-label").textContent = copy.disruption;
  $("#tools-label").textContent = copy.toolsLabel;
  $("#materials-label").textContent = copy.materialsLabel;
  $("#describe-label").textContent = copy.describe;
  $("#incident").placeholder = copy.placeholder;
  $("#run-custom").textContent = copy.runLong;
  $("#clock").textContent = `${copy.clock} ${formatClock(state.horizon)} UTC`;
  paintMode(copy);
  const banner = $("#banner");
  banner.hidden = true;
  $("#theme").textContent = state.theme === "dark" ? copy.themeDark : copy.themeLight;
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.setAttribute("aria-pressed", button.getAttribute("data-lang") === state.lang ? "true" : "false");
  });
  paintTabs();
  paintScenarios();
  paintBay();
  paintRecover();
  paintAnalyze();
  paintVerify();
  if (state.running && !state.report) $("#status").textContent = copy.working;
  else if (!state.running && !state.report) $("#status").textContent = "";
}

function paintTabs() {
  const copy = t();
  const host = $("#tabs");
  host.innerHTML = "";
  const tips = { recover: copy.tabRecoverTip, analyze: copy.tabAnalyzeTip, verify: copy.tabVerifyTip };
  for (const [id, label] of [["recover", copy.tabRecover], ["analyze", copy.tabAnalyze], ["verify", copy.tabVerify]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", state.tab === id ? "true" : "false");
    button.title = tips[id] || "";
    button.textContent = label;
    button.addEventListener("click", () => {
      state.tab = id;
      paintTabs();
      showPanel();
    });
    host.appendChild(button);
  }
  showPanel();
}

function showPanel() {
  for (const id of ["recover", "analyze", "verify"]) {
    const panel = $(`#panel-${id}`);
    panel.hidden = state.tab !== id;
  }
}

function paintScenarios() {
  const host = $("#scenarios");
  const copy = t();
  host.innerHTML = "";
  const recommended = (state.overview && state.overview.recommended) || "litho_down";
  for (const item of state.scenarioItems || []) {
    const text = copy.scenarios[item.id] || [item.title, item.summary];
    const primary = item.id === recommended;
    const row = document.createElement("div");
    row.className = "scenario" + (item.id === state.activeScenario ? " active" : "") + (primary ? " recommended" : "");
    const words = document.createElement("div");
    const mark = primary ? `<em>${escapeHtml(copy.recommended)}</em>` : "";
    const impact = scenarioImpact(item.id, copy);
    words.innerHTML = `<strong>${mark}${escapeHtml(text[0])}</strong><span>${escapeHtml(impact || text[1])}</span>`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = primary ? "run" : "run quiet";
    button.textContent = copy.run;
    button.disabled = state.running;
    button.addEventListener("click", () => {
      $("#incident").value = "";
      run({ scenario: item.id });
    });
    row.append(words, button);
    host.appendChild(row);
  }
  $("#run-custom").disabled = state.running;
  $("#run-custom").className = "run quiet";
}

function scenarioImpact(id, copy) {
  const impacts = state.overview && state.overview.impacts;
  const row = impacts && impacts[id];
  if (!row) return id === "scale" ? copy.impactScale : "";
  const otd = fill(copy.impactOtd, {
    before: `${Number(row.otd_before).toFixed(1)}%`,
    after: `${Number(row.otd_after).toFixed(1)}%`,
  });
  const tardy = fill(copy.impactTardy, {
    before: formatDuration(row.tardy_before),
    after: formatDuration(row.tardy_after),
  });
  return `${otd} · ${tardy}`;
}

function bayStatus() {
  const status = {};
  for (const item of state.bay) status[item.id] = item.status;
  if (!state.report) return status;
  const rows = state.report.gantt && state.report.gantt.after && state.report.gantt.after.rows;
  if (rows) {
    for (const row of rows) status[row.equipment_id] = row.status;
  }
  if (state.report.scenario_id === "material_shortage") status["RESIST-UV"] = "short";
  return status;
}

function paintBay() {
  const copy = t();
  const tools = $("#tools");
  const materials = $("#materials");
  const legend = $("#bay-legend");
  tools.innerHTML = "";
  materials.innerHTML = "";
  legend.innerHTML = "";
  for (const [klass, label] of [["up", copy.legendUp], ["down", copy.legendDown], ["maint", copy.legendMaint]]) {
    const li = document.createElement("li");
    li.innerHTML = `<i class="swatch ${klass}"></i><span>${escapeHtml(label)}</span>`;
    legend.appendChild(li);
  }
  const scaleRows = state.report && state.report.scenario_id === "scale" && state.report.load && state.report.load.after && state.report.load.after.rows;
  const materialHost = $("#materials-label");
  if (scaleRows) {
    materialHost.hidden = true;
    materials.hidden = true;
    const counts = {};
    const down = {};
    for (const row of scaleRows) {
      counts[row.area] = (counts[row.area] || 0) + 1;
      if (row.status === "DOWN" || row.status === "MAINTENANCE") down[row.area] = true;
    }
    const order = ["Deposition", "Lithography", "Metrology", "Etch", "Clean", "CMP"];
    for (const area of order) {
      if (!counts[area]) continue;
      const li = document.createElement("li");
      const status = down[area] ? "DOWN" : "IDLE";
      const name = (copy.areas && copy.areas[area]) || area;
      li.innerHTML = `<span class="lamp ${lampClass(status, "tool")}"></span><span>${escapeHtml(name)}</span><small>${counts[area]}</small>`;
      tools.appendChild(li);
    }
    return;
  }
  materialHost.hidden = false;
  materials.hidden = false;
  for (const tool of currentTools()) {
    const li = document.createElement("li");
    li.dataset.id = tool.id;
    const detail = toolDetail(tool, copy);
    li.innerHTML = `<span class="lamp ${lampClass(tool.status, "tool")}"></span><span>${escapeHtml(tool.id)}</span><small>${escapeHtml(detail)}</small>`;
    li.title = `${tool.id} · ${detail}`;
    tools.appendChild(li);
  }
  for (const item of currentMaterials()) {
    const li = document.createElement("li");
    li.dataset.id = item.id;
    const qty = fill(copy.onHand, { qty: item.on_hand, unit: item.unit || "" });
    li.innerHTML = `<span class="lamp ${lampClass(item.status, "material")}"></span><span>${escapeHtml(item.id)}</span><small>${escapeHtml(qty)}</small>`;
    materials.appendChild(li);
  }
}

function currentTools() {
  const gantt = state.report && state.report.gantt && state.report.gantt.after;
  if (gantt && gantt.rows) return gantt.rows.map(toolFromRow);
  return (state.overview && state.overview.tools) || [];
}

function toolFromRow(row) {
  const bars = (row.bars || []).filter((bar) => !bar.held);
  const now = bars.find((bar) => bar.start_min <= 0 && bar.end_min > 0);
  const nxt = !now && bars.length ? bars.slice().sort((a, b) => a.start_min - b.start_min)[0] : null;
  return {
    id: row.equipment_id,
    status: row.status,
    lot: now ? now.job_id : "",
    eta_min: now ? now.end_min : null,
    next_lot: nxt ? nxt.job_id : "",
    next_min: nxt ? nxt.start_min : null,
    down_until_min: row.status === "DOWN" || row.status === "MAINTENANCE" ? row.available_at_min : null,
  };
}

function currentMaterials() {
  const rows = (state.overview && state.overview.materials) || [];
  if (state.report && state.report.scenario_id === "material_shortage") {
    return rows.map((item) => item.id === "RESIST-UV" ? { ...item, on_hand: 0, status: "short" } : item);
  }
  return rows;
}

function toolDetail(tool, copy) {
  if (tool.status === "DOWN") return fill(copy.downUntil, { time: shiftClock(tool.down_until_min) });
  if (tool.status === "MAINTENANCE") return fill(copy.maintUntil, { time: shiftClock(tool.down_until_min) });
  if (tool.lot) return fill(copy.runningLot, { lot: shortLot(tool.lot), time: shiftClock(tool.eta_min) });
  if (tool.next_lot) return fill(copy.nextLot, { lot: shortLot(tool.next_lot), time: shiftClock(tool.next_min) });
  return copy.idleTool;
}

function lampClass(status, kind) {
  if (kind === "material" && (status === "short" || status === "DOWN")) return "short";
  if (status === "DOWN" || status === "short") return "down";
  if (status === "MAINTENANCE") return "maint";
  if (status === "RUNNING" || status === "IDLE" || status === "ok") return "up";
  return "";
}

function statusLabel(status) {
  const names = t().status || {};
  return names[status] || status;
}

function flash(id) {
  const row = document.querySelector(`.bay li[data-id="${id}"]`);
  if (!row) return;
  const lamp = row.querySelector(".lamp");
  lamp.classList.remove("flash");
  void lamp.offsetWidth;
  lamp.classList.add("flash");
}

function paintRecover() {
  const report = state.report;
  const empty = $("#empty");
  const story = $("#story");
  const cards = $("#cards");
  const stepper = $("#stepper");
  const result = $("#result");
  const showStory = Boolean(report) || state.running;
  empty.hidden = showStory;
  if (!showStory) paintOverview();
  story.hidden = !showStory;
  cards.hidden = !report || !report.kpis;
  stepper.hidden = !showStory;
  result.hidden = !report || (!report.gantt && !report.load);
  if (state.running && !report) {
    $("#headline").textContent = state.incidentText;
    $("#refusal").textContent = "";
  } else if (report) {
    const brief = report.brief && report.brief[state.lang];
    $("#headline").textContent = brief ? brief.headline : state.incidentText;
    $("#refusal").textContent = refusalLine(report);
  }
  if (report && report.kpis) renderCards(report);
  if (showStory) paintStepper();
  if (report && (report.gantt || report.load)) renderCharts(report);
}

function refusalLine(report) {
  const rejected = report.rejected_alternative && report.rejected_alternative.critique;
  const violation = rejected && rejected.violations && rejected.violations[0];
  return formatFinding(violation);
}

function renderCards(report) {
  const copy = t();
  const host = $("#cards");
  host.innerHTML = "";
  for (const [key, labelKey, kind, digits, tipKey, icon] of KEY_CARDS) {
    const tone = (report.kpis.tones && report.kpis.tones[key]) || { tone: "flat" };
    const card = document.createElement("article");
    card.className = "kpi";
    const mark = document.createElement("span");
    mark.className = "icon";
    mark.innerHTML = iconSvg(icon);
    const title = document.createElement("div");
    title.className = "title";
    title.append(document.createTextNode(copy[labelKey]), infoButton(copy[tipKey]));
    const value = document.createElement("div");
    value.className = "value";
    value.textContent = formatMeasure(report.kpis.after[key], kind, digits);
    const sub = document.createElement("div");
    sub.className = "sub";
    const aside = tone.comparable === false ? ` · ${copy.heldAside}` : "";
    sub.innerHTML = `${escapeHtml(formatMeasure(report.kpis.before[key], kind, digits))} <span class="${escapeHtml(tone.tone)}">${escapeHtml(signedMeasure(report.kpis.delta[key], kind, digits))}</span>${escapeHtml(aside)}`;
    const details = document.createElement("button");
    details.type = "button";
    details.className = "details";
    details.textContent = copy.details;
    details.addEventListener("click", () => {
      state.tab = "analyze";
      paintTabs();
    });
    card.append(mark, title, details, value, sub);
    host.appendChild(card);
  }
}

function iconSvg(kind) {
  if (kind === "bar") return '<svg viewBox="0 0 14 14" aria-hidden="true"><rect x="1" y="8" width="3" height="5" rx="1" fill="currentColor"/><rect x="5.5" y="4" width="3" height="9" rx="1" fill="currentColor"/><rect x="10" y="1" width="3" height="12" rx="1" fill="currentColor"/></svg>';
  if (kind === "ring") return '<svg viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  return '<svg viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="4" fill="currentColor"/></svg>';
}

function paintStepper() {
  const copy = t();
  const host = $("#stepper");
  host.innerHTML = "";
  host.setAttribute("aria-label", copy.loopLabel);
  const seen = new Map(state.steps.map((step) => [step.phase, step]));
  let active = "";
  for (const step of state.steps) {
    if (STEPS.some(([, phases]) => phases.includes(step.phase))) active = step.phase;
  }
  const list = document.createElement("ol");
  let done = 0;
  for (const [, phases, key] of STEPS) {
    const step = phases.map((phase) => seen.get(phase)).filter(Boolean).pop();
    if (step) done += 1;
    const running = Boolean(step) && phases.includes(active) && state.running;
    const li = document.createElement("li");
    li.className = running ? "on" : step ? "done" : "";
    li.textContent = nodeLabel(key);
    if (step) {
      const text = `${nodeLabel(key)} · ${stepOutput(step.phase, step.slots || {}, copy)}`;
      li.addEventListener("pointerenter", (event) => showPlainTip(event, text));
      li.addEventListener("pointerleave", hideTip);
    }
    list.appendChild(li);
  }
  const pct = Math.round((100 * done) / STEPS.length);
  const side = document.createElement("div");
  side.innerHTML = `<div class="meter-line"><i style="width:${pct}%"></i></div>`;
  const label = document.createElement("div");
  label.className = "progress-label";
  const current = STEPS.find(([, phases]) => phases.includes(active));
  label.textContent = state.running && current ? `${pct}% · ${nodeLabel(current[2])}` : `${pct}%`;
  bindTip(label, copy.progressTip);
  const stack = document.createElement("div");
  stack.append(side, label);
  host.append(list, stack);
}

function optimalityGap(opt) {
  const heuristic = Number(opt.heuristic_tardiness_min) || 0;
  const bound = opt.bound_tardiness_min == null ? null : Number(opt.bound_tardiness_min);
  if (bound == null || heuristic <= 0) return 0;
  return Math.max(0, Math.round((100 * (heuristic - bound)) / heuristic));
}

function optimalityLine(opt, copy) {
  if (!opt || opt.available !== true) return "";
  const seconds = (Number(opt.runtime_ms || 0) / 1000).toFixed(2);
  const delta = formatDuration(opt.delta_min > 0 ? opt.delta_min : opt.makespan_delta_min);
  const fill = (template) => template
    .replaceAll("{delta}", delta)
    .replaceAll("{seconds}", seconds)
    .replaceAll("{gap}", String(optimalityGap(opt)));
  const neighborhood = opt.mode === "lns" || opt.status === "KEPT" || opt.status === "UNKNOWN" || opt.status === "INFEASIBLE" || opt.status === "SKIPPED";
  if (neighborhood) {
    if (opt.improved && opt.delta_min > 0) return fill(copy.optLnsTardy);
    if (opt.improved && opt.makespan_delta_min > 0) return fill(copy.optLnsSpan);
    return fill(copy.optKept);
  }
  if (opt.status === "FEASIBLE") {
    if (opt.bound_tardiness_min == null) return fill(copy.optKept);
    return fill(copy.optFeasible);
  }
  if (opt.proved && opt.delta_min > 0) return fill(copy.optProvedTardy);
  if (opt.proved && opt.makespan_delta_min > 0) return fill(copy.optProvedSpan);
  if (opt.proved) return copy.optProvedZero;
  return fill(copy.optKept);
}

function paintOptimality(report) {
  const node = $("#optimality");
  if (!node) return;
  const opt = report && report.optimality;
  const text = optimalityLine(opt, t());
  node.hidden = !text;
  node.textContent = text;
  node.className = "opt-badge" + (opt && opt.proved ? " proved" : "");
}

function renderCharts(report) {
  paintOptimality(report);
  if (report.load) {
    renderScale(report);
    return;
  }
  const copy = t();
  const beforeName = (copy.chartBefore && copy.chartBefore[report.scenario_id]) || report.before_label;
  const afterName = (copy.chartAfter && copy.chartAfter[report.scenario_id]) || report.after_label;
  $("#before-label").textContent = beforeName;
  $("#after-label").textContent = afterName;
  paintViews();
  const scale = scaleOf(report);
  renderGantt($("#gantt-before"), report.gantt.before, report.horizon, scale, false);
  renderGantt($("#gantt-after"), report.gantt.after, report.horizon, scale, true);
  renderLegend(report);
}

function paintAnalyze() {
  const host = $("#panel-analyze");
  const copy = t();
  host.innerHTML = "";
  const report = state.report;
  if (!report || !report.kpis) {
    host.appendChild(emptyLine(copy.analyzeEmpty));
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "analyze";
  const gap = optimalityCard(report);
  const parts = [figuresCard(report), utilCard(report), waitCard(report), qtimeCard(report), bottleneckCard(report), lotsCard(report)];
  if (gap) parts.unshift(gap);
  wrap.append(...parts);
  host.appendChild(wrap);
}

function optimalityCard(report) {
  const opt = report.optimality;
  const copy = t();
  const text = optimalityLine(opt, copy);
  if (!text) return null;
  const card = document.createElement("article");
  card.className = "card wide";
  card.id = "optimality-card";
  card.appendChild(cardHead(copy.optTitle, copy.optNote));
  const line = document.createElement("p");
  line.className = "opt-line" + (opt.proved ? " proved" : "");
  line.textContent = text;
  card.appendChild(line);
  const table = document.createElement("table");
  table.className = "compare";
  const head = document.createElement("thead");
  head.innerHTML = `<tr><th></th><th class="num">${escapeHtml(copy.optHeuristic)}</th><th class="num">${escapeHtml(copy.optBest)}</th><th class="num">${escapeHtml(copy.optBound)}</th></tr>`;
  const body = document.createElement("tbody");
  const bound = opt.bound_tardiness_min == null ? "—" : formatDuration(opt.bound_tardiness_min);
  const rows = [
    [copy.kpiTardy, formatDuration(opt.heuristic_tardiness_min), formatDuration(opt.best_tardiness_min), bound],
    [copy.kpiSpan, formatDuration(opt.heuristic_makespan_min), formatDuration(opt.best_makespan_min), "—"],
  ];
  for (const [name, left, mid, right] of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<th>${escapeHtml(name)}</th><td class="num">${escapeHtml(left)}</td><td class="num">${escapeHtml(mid)}</td><td class="num">${escapeHtml(right)}</td>`;
    body.appendChild(tr);
  }
  table.append(head, body);
  card.appendChild(table);
  const changed = (opt.reference && opt.reference.changed) || [];
  if (opt.improved && changed.length) {
    const title = document.createElement("p");
    title.className = "note-inline";
    title.textContent = copy.optChanged;
    card.appendChild(title);
    const moves = document.createElement("table");
    moves.innerHTML = `<thead><tr><th>${escapeHtml(copy.lot)}</th><th>${escapeHtml(copy.step)}</th><th>${escapeHtml(copy.from)}</th><th>${escapeHtml(copy.to)}</th><th class="num">${escapeHtml(copy.optStart)}</th></tr></thead>`;
    const moveBody = document.createElement("tbody");
    for (const row of changed.slice(0, 12)) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="mono">${escapeHtml(row.job_id)}</td><td class="mono">${escapeHtml(row.step)}</td><td class="mono">${escapeHtml(row.from_equipment || "—")}</td><td class="mono">${escapeHtml(row.equipment_id)}</td><td class="num">${escapeHtml(formatDuration(row.start_min))}</td>`;
      moveBody.appendChild(tr);
    }
    moves.appendChild(moveBody);
    card.appendChild(moves);
  }
  return card;
}

function figuresCard(report) {
  const copy = t();
  const card = document.createElement("article");
  card.className = "card wide";
  card.appendChild(cardHead(copy.figures, copy.figuresNote));
  const table = document.createElement("table");
  table.className = "compare";
  const head = document.createElement("tr");
  for (const label of ["", copy.before, copy.after, copy.change]) {
    const th = document.createElement("th");
    th.textContent = label;
    if (label) th.className = "num";
    head.appendChild(th);
  }
  const body = document.createElement("tbody");
  const headRow = document.createElement("thead");
  headRow.appendChild(head);
  for (const [key, labelKey, kind, digits, tipKey] of ANALYZE_KEYS) {
    if (report.kpis.before[key] === undefined) continue;
    const tone = (report.kpis.tones && report.kpis.tones[key]) || { tone: "flat", comparable: true };
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.append(document.createTextNode(copy[labelKey]), infoButton(copy[tipKey]));
    if (tone.comparable === false) {
      const note = document.createElement("div");
      note.className = "note-inline";
      note.textContent = copy.heldOut;
      th.appendChild(note);
    }
    tr.appendChild(th);
    for (const [value, extra] of [
      [formatMeasure(report.kpis.before[key], kind, digits), "num"],
      [formatMeasure(report.kpis.after[key], kind, digits), "num"],
      [signedMeasure(report.kpis.delta[key], kind, digits), `num ${tone.tone}`],
    ]) {
      const td = document.createElement("td");
      td.className = extra;
      td.textContent = value;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  const moved = report.kpis.lots_moved || [];
  const tr = document.createElement("tr");
  const movedName = document.createElement("th");
  movedName.append(document.createTextNode(copy.kpiMoved), infoButton(copy.movedTip));
  tr.appendChild(movedName);
  for (const [value, extra] of [["—", "num"], [String(moved.length), "num"], [moved.join(", ") || "—", "num flat mono"]]) {
    const td = document.createElement("td");
    td.className = extra;
    td.textContent = value;
    if (extra.startsWith("num") && value !== "—") bindTip(td, copy.movedTip);
    tr.appendChild(td);
  }
  body.appendChild(tr);
  table.append(headRow, body);
  card.appendChild(table);
  const down = downNote(report.kpis.down || {}, copy);
  if (down) card.appendChild(down);
  return card;
}

function utilCard(report) {
  const copy = t();
  const card = document.createElement("article");
  card.className = "card";
  const head = cardHead(copy.byArea, copy.utilNote);
  const toggles = document.createElement("div");
  toggles.className = "toggles";
  for (const [id, label] of [["before", copy.before], ["after", copy.after]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-pressed", state.utilSide === id ? "true" : "false");
    button.addEventListener("click", () => {
      state.utilSide = id;
      paintAnalyze();
    });
    toggles.appendChild(button);
  }
  head.appendChild(toggles);
  card.appendChild(head);
  const areas = ((report.kpis.areas || {})[state.utilSide] || []).slice().sort((a, b) => b.utilization_pct - a.utilization_pct);
  for (const row of areas) {
    const line = document.createElement("div");
    line.className = "area";
    const name = document.createElement("span");
    name.textContent = (copy.areas && copy.areas[row.area]) || row.area;
    const bar = document.createElement("span");
    bar.className = "meter";
    const fill = document.createElement("i");
    fill.style.width = `${Math.max(0, Math.min(100, row.utilization_pct))}%`;
    bar.appendChild(fill);
    const fig = document.createElement("span");
    fig.textContent = `${Number(row.utilization_pct).toFixed(1)}%`;
    fig.className = "num";
    bindTip(fig, copy.areaTip);
    line.append(name, bar, fig);
    card.appendChild(line);
  }
  return card;
}

function waitCard(report) {
  const copy = t();
  const card = document.createElement("article");
  card.className = "card";
  card.appendChild(cardHead(copy.whereWait, copy.waitNote));
  const after = (report.kpis.waits && report.kpis.waits.after) || [];
  const before = new Map(((report.kpis.waits && report.kpis.waits.before) || []).map((row) => [`${row.from_step}→${row.to_step}`, row.avg_min]));
  const peak = Math.max(1, ...after.map((row) => row.avg_min));
  const tone = (report.kpis.tones && report.kpis.tones.mean_wait_min) || { tone: "flat", comparable: true };
  for (const row of after.slice(0, 4)) {
    const key = `${row.from_step}→${row.to_step}`;
    const line = document.createElement("div");
    line.className = "wait-row";
    const name = document.createElement("span");
    name.textContent = `${row.from_step} → ${row.to_step}`;
    const bar = document.createElement("span");
    bar.className = "wait-bar";
    const fill = document.createElement("i");
    fill.style.width = `${Math.max(4, (row.avg_min / peak) * 100)}%`;
    bar.appendChild(fill);
    const fig = document.createElement("span");
    const prior = before.get(key);
    let klass = "flat";
    if (tone.comparable !== false && prior !== undefined && row.avg_min !== prior) klass = row.avg_min < prior ? "good" : "bad";
    fig.className = klass;
    fig.textContent = formatDuration(row.avg_min);
    bindTip(fig, copy.waitPair.replace("{from}", row.from_step).replace("{to}", row.to_step).replace("{n}", String(row.n)));
    line.append(name, bar, fig);
    card.appendChild(line);
  }
  return card;
}

function qtimeCard(report) {
  const copy = t();
  const card = document.createElement("article");
  card.className = "card";
  card.appendChild(cardHead(copy.qtimeTitle, copy.qtimeNote));
  const qtime = report.kpis.qtime || {};
  const before = qtime.before || {};
  const after = qtime.after || {};
  const grid = document.createElement("div");
  grid.className = "qtime-grid";
  for (const [label, tip, left, right] of [
    [copy.compliance, copy.qtimeTip, before.compliance_pct, after.compliance_pct],
    [copy.violations, copy.violationTip, before.violations, after.violations],
    [copy.atRisk, copy.atRiskTip, before.at_risk, after.at_risk],
  ]) {
    const line = document.createElement("div");
    line.className = "qtime-row";
    const name = document.createElement("span");
    name.append(document.createTextNode(label), infoButton(tip));
    const fig = document.createElement("span");
    fig.className = "num";
    const leftText = label === copy.compliance ? `${Number(left || 0).toFixed(1)}%` : String(left || 0);
    const rightText = label === copy.compliance ? `${Number(right || 0).toFixed(1)}%` : String(right || 0);
    fig.textContent = `${leftText} → ${rightText}`;
    bindTip(fig, tip);
    line.append(name, fig);
    grid.appendChild(line);
  }
  card.appendChild(grid);
  const rows = (after.rows || []).filter((row) => row.state !== "met");
  if (rows.length) {
    const list = document.createElement("ul");
    list.className = "qtime-list";
    for (const row of rows.slice(0, 4)) {
      const item = document.createElement("li");
      const gap = row.gap_min == null ? copy.held : formatDuration(row.gap_min);
      item.textContent = `${row.job_id} ${row.from_step} → ${row.to_step} · ${gap} · ${row.state}`;
      list.appendChild(item);
    }
    card.appendChild(list);
  }
  return card;
}

function bottleneckCard(report) {
  const copy = t();
  const card = document.createElement("article");
  card.className = "card";
  const head = cardHead(copy.bottleneckTitle, copy.bottleneckNote);
  head.appendChild(infoButton(copy.bottleneckTip));
  card.appendChild(head);
  const bottleneck = report.kpis.bottleneck || {};
  const area = bottleneck.area || "—";
  const name = document.createElement("p");
  name.className = "bottleneck-name";
  name.textContent = (copy.areas && copy.areas[area]) || area;
  const fig = document.createElement("p");
  fig.className = "num bottleneck-fig";
  const before = Number(bottleneck.before_pct || 0).toFixed(1);
  const after = Number(bottleneck.after_pct || 0).toFixed(1);
  fig.textContent = `${before}% → ${after}%`;
  bindTip(fig, copy.bottleneckTip);
  card.append(name, fig);
  return card;
}

function lotsCard(report) {
  const copy = t();
  const card = document.createElement("article");
  card.className = "card wide";
  const note = report.scenario_id === "scale" ? copy.lotNoteScale : copy.lotNote;
  card.appendChild(cardHead(copy.lots, note));
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr><th>${escapeHtml(copy.lot)}</th><th class="num">${escapeHtml(copy.pri)}</th><th>${escapeHtml(copy.step)}</th><th>${escapeHtml(copy.from)}</th><th>${escapeHtml(copy.to)}</th><th class="num">${escapeHtml(copy.tardy)}</th></tr></thead>`;
  const body = document.createElement("tbody");
  const changed = (report.outcomes || []).filter((row) => row.moved_from && row.moved_to && row.moved_from !== row.moved_to);
  const outcomeRows = report.scenario_id === "scale" ? changed.slice(0, 12) : (report.outcomes || []);
  for (const row of outcomeRows) {
    const from = row.moved_from || row.before_equipment || "—";
    const to = row.moved_to || row.after_equipment || copy.held;
    const step = row.moved_step || "—";
    const better = row.after_tardiness_min < row.before_tardiness_min;
    const worse = row.after_tardiness_min > row.before_tardiness_min;
    const tone = better ? "good" : worse ? "bad" : "flat";
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="mono">${escapeHtml(row.job_id)}</td><td class="num">${row.priority}</td><td class="mono">${escapeHtml(step)}</td><td class="mono">${escapeHtml(from)}</td><td class="mono">${escapeHtml(to)}</td><td class="num ${tone}">${escapeHtml(formatDuration(row.before_tardiness_min))} → ${escapeHtml(formatDuration(row.after_tardiness_min))}</td>`;
    bindTip(tr.lastElementChild, copy.tardyCellTip);
    body.appendChild(tr);
  }
  table.appendChild(body);
  card.appendChild(table);
  return card;
}

function paintVerify() {
  const host = $("#panel-verify");
  const copy = t();
  host.innerHTML = "";
  const report = state.report;
  if (!report) {
    host.appendChild(emptyLine(copy.verifyEmpty));
    return;
  }
  const card = document.createElement("article");
  card.className = "card";
  const verdict = report.verdict ? report.verdict.verdict : "—";
  const head = cardHead(copy.tabVerify, copy.verifyLead);
  card.appendChild(head);
  const summary = document.createElement("p");
  const pill = document.createElement("span");
  pill.className = `pill ${verdict}`;
  pill.textContent = (copy.verdicts && copy.verdicts[verdict]) || verdict;
  summary.appendChild(pill);
  if (report.verdict && verdict !== "accept") {
    const why = rationaleText(report.verdict);
    if (why) summary.append(document.createTextNode(` ${why}`));
  }
  card.appendChild(summary);
  const validation = report.validation;
  if (!validation || !validation.details) {
    card.appendChild(legacyChecks(report, copy));
    host.appendChild(card);
    return;
  }
  const counts = document.createElement("p");
  counts.className = "note-inline";
  counts.textContent = `${validation.passed} ${copy.passed} · ${validation.failed} ${copy.failed} · ${validation.skipped} ${copy.skipped}`;
  card.appendChild(counts);
  const table = document.createElement("table");
  table.className = "checks";
  table.innerHTML = `<thead><tr><th>${escapeHtml(copy.check)}</th><th>${escapeHtml(copy.category)}</th><th>${escapeHtml(copy.checkStatus)}</th><th class="num">${escapeHtml(copy.violations)}</th><th>${escapeHtml(copy.reason)}</th></tr></thead>`;
  const body = document.createElement("tbody");
  const lang = state.lang || "en";
  for (const row of validation.details) {
    const tr = document.createElement("tr");
    const name = (row.name && (row.name[lang] || row.name.en)) || row.id;
    const category = (copy.categories && copy.categories[row.category]) || row.category;
    const status = copy[row.status] || row.status;
    const reasons = checkReasons(report, row, copy);
    const reasonCell = reasons.length
      ? `<details class="check-reasons"><summary>${escapeHtml(copy.reason)}</summary><ul>${reasons.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul></details>`
      : "—";
    tr.innerHTML = `<td>${escapeHtml(name)}</td><td>${escapeHtml(category)}</td><td><span class="pill ${escapeHtml(row.status)}">${escapeHtml(status)}</span></td><td class="num">${(row.violations || []).length}</td><td>${reasonCell}</td>`;
    body.appendChild(tr);
  }
  table.appendChild(body);
  card.appendChild(table);
  host.appendChild(card);
}

function checkReasons(report, row, copy) {
  const reasons = (row.violations || []).map((item) => formatFinding(item)).filter(Boolean);
  const rejected = report.rejected_alternative && report.rejected_alternative.critique;
  for (const item of (rejected && rejected.violations) || []) {
    if (item.constraint !== row.constraint && item.constraint !== row.id) continue;
    const line = formatFinding(item);
    if (line && !reasons.includes(line)) reasons.push(`${copy.refusedPlan}: ${line}`);
  }
  return reasons;
}

function legacyChecks(report, copy) {
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr><th>${escapeHtml(copy.check)}</th><th>${escapeHtml(copy.result)}</th><th>${escapeHtml(copy.reason)}</th></tr></thead>`;
  const body = document.createElement("tbody");
  for (const row of report.checks || []) {
    const tr = document.createElement("tr");
    const name = (copy.checks && copy.checks[row.constraint]) || row.constraint;
    const result = copy[row.result] || row.result;
    tr.innerHTML = `<td>${escapeHtml(name)}</td><td><span class="pill ${escapeHtml(row.result)}">${escapeHtml(result)}</span></td><td>${escapeHtml(row.reason || "—")}</td>`;
    body.appendChild(tr);
  }
  table.appendChild(body);
  return table;
}

function cardHead(title, note) {
  const head = document.createElement("div");
  head.className = "card-head";
  const h = document.createElement("h3");
  h.textContent = title;
  const p = document.createElement("p");
  p.textContent = note;
  head.append(h, p);
  return head;
}

function emptyLine(text) {
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = text;
  return p;
}

function downNote(down, copy) {
  const before = describeDown(down.before || [], copy);
  const after = describeDown(down.after || [], copy);
  if (!before && !after) return null;
  const note = document.createElement("p");
  note.className = "down-note";
  const lamp = document.createElement("span");
  lamp.className = "lamp down";
  const text = before === after ? `${copy.downWindow}: ${after}` : `${copy.before} ${before} · ${copy.after} ${after}`;
  note.append(lamp, document.createTextNode(text));
  bindTip(note, copy.downTip);
  return note;
}

function describeDown(rows, copy) {
  return rows.map((row) => {
    const word = row.status === "MAINTENANCE" ? copy.maint : copy.down;
    return `${row.equipment_id} · ${word} · ${formatDuration(row.down_min)}`;
  }).join(", ");
}

function infoButton(text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "info";
  button.textContent = "?";
  button.setAttribute("aria-label", text);
  bindTip(button, text);
  return button;
}

function bindTip(node, text) {
  if (!node) return;
  if (node.tagName !== "BUTTON") node.setAttribute("aria-label", text);
  node.addEventListener("pointerenter", (event) => showPlainTip(event, text));
  node.addEventListener("focus", (event) => showPlainTip(event, text));
  node.addEventListener("pointerleave", hideTip);
  node.addEventListener("blur", hideTip);
}

function showPlainTip(event, text) {
  const tip = $("#tip");
  tip.textContent = text;
  tip.hidden = false;
  const x = event.clientX || (event.target.getBoundingClientRect().left);
  const y = event.clientY || (event.target.getBoundingClientRect().bottom);
  tip.style.left = `${Math.min(x + 12, window.innerWidth - 340)}px`;
  tip.style.top = `${Math.min(y + 16, window.innerHeight - 80)}px`;
}

async function run(body) {
  if (state.running) return;
  state.running = true;
  state.steps = [];
  state.report = null;
  state.tab = "recover";
  state.activeScenario = body.scenario || "";
  state.incidentText = incidentOf(body);
  closeRoute();
  paint();
  const alertId = ALERT[body.scenario];
  if (alertId) flash(alertId);
  try {
    const response = await fetch("/api/recover/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Request failed (${response.status})`);
    }
    await readSse(response, (kind, payload) => {
      if (kind === "step") {
        state.steps.push(payload);
        paintStepper();
        paintScenarios();
        if (payload.phase === "alert" && body.scenario) flash(ALERT[body.scenario]);
      } else if (kind === "report") {
        state.report = payload;
        paint();
      } else if (kind === "error") {
        throw new Error(payload.detail || "Recovery failed");
      }
    });
    const report = state.report;
    $("#status").textContent = report && report.blocked
      ? t().refused
      : doneStatus(report);
  } catch (error) {
    $("#status").textContent = error.message;
  } finally {
    state.running = false;
    paintScenarios();
    paintStepper();
  }
}

function incidentOf(body) {
  if (body.incident) return body.incident;
  const item = (state.scenarioItems || []).find((row) => row.id === body.scenario);
  return item ? item.incident : "";
}

async function readSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const parsed = parseSse(block);
      if (parsed) onEvent(parsed.kind, parsed.payload);
      cut = buffer.indexOf("\n\n");
    }
  }
}

function parseSse(block) {
  let kind = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) kind = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!data) return null;
  return { kind, payload: JSON.parse(data) };
}

function stepOutput(phase, slots, copy) {
  if (phase === "scout") {
    const raw = String(slots.intent || "").replace(/^plant\./, "");
    const label = (copy.intents && copy.intents[raw]) || raw.replaceAll("_", " ");
    const conf = typeof slots.confidence === "number" ? ` · ${Math.round(slots.confidence * 100)}%` : "";
    return `${label}${conf}`;
  }
  if (phase === "query") {
    const source = slots.source === "zetaris" ? copy.sourceZetaris : copy.sourceSample;
    return `${source} · ${slots.reads ?? 0} ${copy.reads}`;
  }
  if (phase === "sense") return `${slots.facts ?? 0} ${copy.facts}`;
  if (phase === "plan") return `${slots.operations ?? 0} ${copy.ops} · ${slots.holds ?? 0} ${copy.holds}`;
  if (phase === "critique") return String((copy.verdicts && copy.verdicts[slots.verdict]) || slots.verdict || "");
  if (phase === "explain") {
    const model = String(slots.model || "").split("/").pop();
    return [
      slots.provider,
      model,
      slots.completion_id,
      slots.meterless_request_id,
      slots.provider_model,
    ].filter(Boolean).join(" · ");
  }
  if (phase === "commit") return `${slots.events ?? 0} ${copy.events}`;
  return "";
}

function renderScale(report) {
  const copy = t();
  const beforeName = (copy.chartBefore && copy.chartBefore.scale) || report.before_label;
  const afterName = (copy.chartAfter && copy.chartAfter.scale) || report.after_label;
  $("#before-label").textContent = beforeName;
  $("#after-label").textContent = afterName;
  const host = $("#views");
  host.innerHTML = "";
  const timing = report.timing || {};
  const seconds = (ms) => `${(Number(ms || 0) / 1000).toFixed(2)} s`;
  const line = document.createElement("p");
  line.className = "scale-stat";
  line.textContent = [
    `${copy.scheduleWord} ${seconds(timing.schedule_ms)}`,
    `${copy.criticWord} ${seconds(timing.critic_ms)}`,
    `${Number(timing.lots || 0).toLocaleString(copy === COPY.zh ? "zh-Hans" : copy === COPY.ja ? "ja" : "en")} ${copy.lots.toLowerCase()}`,
    `${timing.tools || 0} ${copy.toolsWord}`,
    `${timing.steps || 0} ${copy.stepsWord}`,
    `${timing.checks_passed || 0} ${copy.passed.toLowerCase()}`,
  ].join(" · ");
  host.appendChild(line);
  renderHeat($("#gantt-before"), report.load.before, report.horizon);
  renderHeat($("#gantt-after"), report.load.after, report.horizon);
  renderScaleLegend(report);
}

function heatColor(util) {
  const share = Math.max(0, Math.min(100, Number(util) || 0));
  return `color-mix(in srgb, var(--accent) ${Math.round(share)}%, var(--track))`;
}

function renderHeat(host, side, horizon) {
  host.innerHTML = "";
  if (!side) return;
  const wrap = document.createElement("div");
  wrap.className = "heat";
  const axis = document.createElement("div");
  axis.className = "heat-axis";
  const blank = document.createElement("span");
  const ticks = document.createElement("div");
  ticks.className = "heat-ticks";
  const bucket = Number(side.bucket_min) || 60;
  for (let index = 0; index < side.buckets; index += 2) {
    const tick = document.createElement("span");
    tick.style.gridColumn = `${index + 1} / span 2`;
    tick.textContent = clockLabel(horizon, index * bucket);
    ticks.appendChild(tick);
  }
  axis.append(blank, ticks);
  const rows = document.createElement("div");
  rows.className = "heat-rows";
  for (const row of side.rows) {
    const line = document.createElement("div");
    line.className = "heat-row";
    const label = document.createElement("div");
    label.className = "heat-label";
    label.textContent = row.equipment_id;
    const tone = areaTone(row.area);
    label.style.color = tone.ink;
    const cells = document.createElement("div");
    cells.className = "heat-cells";
    cells.style.gridTemplateColumns = `repeat(${side.buckets}, minmax(0, 1fr))`;
    for (const cell of row.cells) {
      const mark = document.createElement("i");
      if (!cell || cell.down || cell.util == null) {
        mark.className = "heat-cell down";
      } else {
        mark.className = "heat-cell";
        mark.style.background = heatColor(cell.util);
      }
      cells.appendChild(mark);
    }
    line.append(label, cells);
    rows.appendChild(line);
  }
  wrap.append(axis, rows);
  host.appendChild(wrap);
}

function clockLabel(horizon, minutes) {
  const when = new Date(Date.parse(horizon) + minutes * 60000);
  const hh = String(when.getUTCHours()).padStart(2, "0");
  const mm = String(when.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function renderScaleLegend(report) {
  const host = $("#legend");
  const copy = t();
  host.innerHTML = "";
  const note = document.createElement("li");
  note.textContent = `${copy.scaleWindow}. ${copy.scaleNote}`;
  host.appendChild(note);
  const beforeAreas = (report.kpis && report.kpis.areas && report.kpis.areas.before) || [];
  const afterAreas = (report.kpis && report.kpis.areas && report.kpis.areas.after) || [];
  const afterPct = {};
  for (const row of afterAreas) afterPct[row.area] = row.utilization_pct;
  for (const row of beforeAreas) {
    const item = document.createElement("li");
    const name = (copy.areas && copy.areas[row.area]) || row.area;
    const after = afterPct[row.area];
    item.textContent = `${name} ${Number(row.utilization_pct).toFixed(0)}% → ${Number(after || 0).toFixed(0)}%`;
    host.appendChild(item);
  }
}

function paintViews() {
  const host = $("#views");
  const copy = t();
  host.innerHTML = "";
  for (const [id, label] of [["tool", copy.byTool], ["lot", copy.byLot]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-pressed", state.view === id ? "true" : "false");
    button.addEventListener("click", () => {
      state.view = id;
      closeRoute();
      if (state.report) renderCharts(state.report);
    });
    host.appendChild(button);
  }
}

function renderGantt(host, gantt, horizon, scale, draw) {
  host.innerHTML = "";
  if (!gantt) return;
  const origin = scale.start_min;
  const span = scale.end_min - origin;
  const byLot = host.id !== "gantt-now" && state.view === "lot";
  const wrap = document.createElement("div");
  wrap.className = "gantt" + (draw ? " draw" : "") + (byLot ? " lot" : "");
  wrap.dataset.scale = String(scale.end_min);
  const rows = byLot ? lotRows(gantt) : gantt.rows;
  for (const row of rows) {
    const line = document.createElement("div");
    const downRow = row.status === "DOWN" || row.status === "MAINTENANCE";
    line.className = "gantt-row" + (row.bottleneck && !byLot ? " bottleneck" : "") + (downRow ? " down-row" : "");
    const label = document.createElement("div");
    label.className = "gantt-label";
    if (byLot) {
      label.innerHTML = `${escapeHtml(row.job_id)}<small>P${row.priority}</small>`;
    } else {
      label.textContent = row.equipment_id;
    }
    const track = document.createElement("div");
    track.className = "track";
    if (byLot) track.dataset.links = "1";
    if (!byLot && row.available_at_min > 0 && span > 0) {
      const visStart = Math.max(0, origin);
      const visEnd = Math.min(row.available_at_min, scale.end_min);
      if (visEnd > visStart) {
        const shade = document.createElement("div");
        shade.className = row.status === "MAINTENANCE" ? "shade maint" : "shade down";
        shade.style.left = `${((visStart - origin) / span) * 100}%`;
        shade.style.width = `${((visEnd - visStart) / span) * 100}%`;
        if (row.available_at_min > scale.end_min) shade.classList.add("continues");
        const until = formatClock(shift(horizon, row.available_at_min)).slice(11, 16);
        shade.title = `${row.equipment_id} · ${row.status === "MAINTENANCE" ? t().maint : t().down} · ${until}`;
        track.appendChild(shade);
      }
    }
    for (const bar of row.bars) {
      const node = document.createElement("div");
      const tone = areaTone(bar.area || row.area);
      node.className = "bar" + (bar.held ? " held" : "") + (bar.moved ? " moved" : "") + (bar.fresh ? " fresh" : "") + (bar.rework ? " rework" : "") + (bar.moved && !draw ? " leaving" : "");
      if (state.routeJob === bar.job_id) node.classList.add("selected");
      node.dataset.start = String(bar.start_min);
      node.dataset.end = String(bar.end_min);
      if (!bar.held) {
        node.style.backgroundColor = tone.fill;
        node.style.color = tone.ink;
      }
      node.title = bar.held ? (formatFinding(bar) || bar.job_id) : bar.job_id;
      const name = document.createElement("span");
      name.className = "bar-label";
      name.textContent = bar.held
        ? (byLot ? t().held : `${shortLot(bar.job_id)} ${t().held}`)
        : shortLot(bar.job_id);
      node.appendChild(name);
      const toolId = bar.equipment_id || row.equipment_id;
      node.addEventListener("pointerenter", (event) => showTip(event, bar, toolId, horizon));
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        hideTip();
        openRoute(event, bar.job_id, gantt, horizon);
      });
      node.addEventListener("pointermove", moveTip);
      node.addEventListener("pointerleave", hideTip);
      track.appendChild(node);
    }
    line.append(label, track);
    wrap.appendChild(line);
  }
  const axis = document.createElement("div");
  axis.className = "axis";
  if (span > 0) {
    for (let minute = origin; minute <= scale.end_min; minute += scale.step_min) {
      const tick = document.createElement("span");
      const atStart = minute === origin;
      const atEnd = minute === scale.end_min;
      tick.textContent = atStart ? t().now : formatClock(shift(horizon, minute)).slice(11, 16);
      tick.style.left = `${((minute - origin) / span) * 100}%`;
      if (atStart) {
        tick.className = "now-tick";
        tick.style.transform = "translateX(0)";
      } else if (atEnd) {
        tick.style.transform = "translateX(-100%)";
      } else {
        tick.style.transform = "translateX(-50%)";
      }
      axis.appendChild(tick);
    }
  }
  wrap.appendChild(axis);
  host.appendChild(wrap);
  wrap.querySelectorAll(".track").forEach((track) => {
    layoutTrack(track, scale);
    if (track.dataset.links === "1") drawLinks(track);
  });
  drawDues(wrap, gantt, scale);
}

function drawDues(wrap, gantt, scale) {
  const track = wrap.querySelector(".track");
  const axis = wrap.querySelector(".axis");
  const span = scale.end_min - scale.start_min;
  if (!track || !axis || !span) return;
  const wrapBox = wrap.getBoundingClientRect();
  const trackBox = track.getBoundingClientRect();
  const origin = trackBox.left - wrapBox.left;
  const width = trackBox.width;
  let any = false;
  for (const due of gantt.dues || []) {
    if (due.due_min < scale.start_min) continue;
    any = true;
    const cap = document.createElement("span");
    cap.className = "due-tick";
    cap.textContent = `${shortLot(due.job_id)} ${t().due}`;
    bindTip(cap, t().dueTip);
    if (due.due_min > scale.end_min) {
      cap.classList.add("edge");
      axis.appendChild(cap);
      continue;
    }
    const mark = document.createElement("div");
    mark.className = "due-line";
    const pct = ((due.due_min - scale.start_min) / span) * 100;
    mark.style.left = `${origin + (pct / 100) * width}px`;
    mark.style.bottom = `${axis.offsetHeight + 4}px`;
    wrap.appendChild(mark);
    cap.style.left = `${pct}%`;
    if (pct > 88) cap.style.transform = "translateX(-100%)";
    else if (pct < 6) cap.style.transform = "translateX(0)";
    else cap.style.transform = "translateX(-50%)";
    axis.appendChild(cap);
  }
  if (any) axis.classList.add("with-due");
}

function lotRows(gantt) {
  const lots = new Map();
  for (const row of gantt.rows) {
    for (const bar of row.bars) {
      if (!lots.has(bar.job_id)) lots.set(bar.job_id, { job_id: bar.job_id, priority: bar.priority, bars: [] });
      lots.get(bar.job_id).bars.push({ ...bar, equipment_id: row.equipment_id, area: row.area });
    }
  }
  return [...lots.values()].sort((a, b) => a.priority - b.priority || a.job_id.localeCompare(b.job_id));
}

function drawLinks(track) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "links");
  const bars = [...track.querySelectorAll(".bar:not(.held)")].sort((a, b) => Number(a.dataset.start) - Number(b.dataset.start));
  for (let index = 0; index < bars.length - 1; index += 1) {
    const left = bars[index];
    const right = bars[index + 1];
    const x1 = left.offsetLeft + left.offsetWidth;
    const x2 = right.offsetLeft;
    if (x2 - x1 < 6) continue;
    const y = left.offsetTop + left.offsetHeight / 2;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(x1));
    line.setAttribute("y1", String(y));
    line.setAttribute("x2", String(x2));
    line.setAttribute("y2", String(y));
    line.setAttribute("stroke", "currentColor");
    line.setAttribute("stroke-width", "1");
    svg.appendChild(line);
  }
  track.appendChild(svg);
}

function openRoute(event, jobId, gantt, horizon) {
  const copy = t();
  const steps = [];
  for (const row of gantt.rows) {
    for (const bar of row.bars) {
      if (bar.job_id === jobId && !bar.held) steps.push({ ...bar, equipment_id: row.equipment_id, area: row.area });
    }
  }
  steps.sort((a, b) => a.start_min - b.start_min);
  state.routeJob = jobId;
  document.querySelectorAll(".bar").forEach((node) => node.classList.toggle("selected", node.title === jobId));
  const host = $("#route");
  host.innerHTML = "";
  const title = document.createElement("h3");
  title.textContent = `${jobId} · ${copy.route}`;
  const list = document.createElement("ol");
  steps.forEach((step, index) => {
    const item = document.createElement("li");
    const area = (copy.areas && copy.areas[step.area]) || step.area || "";
    item.textContent = `${step.step} · ${step.equipment_id} · ${area} · ${formatClock(shift(horizon, step.start_min)).slice(11, 16)}–${formatClock(shift(horizon, step.end_min)).slice(11, 16)}`;
    list.appendChild(item);
    const next = steps[index + 1];
    if (next && next.start_min > step.end_min) {
      const gap = document.createElement("li");
      gap.className = "gap";
      gap.textContent = `${copy.waitGap} ${formatDuration(next.start_min - step.end_min)}`;
      list.appendChild(gap);
    }
  });
  host.append(title, list);
  host.hidden = false;
  host.style.left = `${Math.min(event.clientX + 12, window.innerWidth - 340)}px`;
  host.style.top = `${Math.min(event.clientY + 12, window.innerHeight - 220)}px`;
}

function closeRoute() {
  state.routeJob = "";
  const host = $("#route");
  if (host) host.hidden = true;
  document.querySelectorAll(".bar.selected").forEach((node) => node.classList.remove("selected"));
}

function layoutTrack(track, scale) {
  const width = track.clientWidth;
  const origin = scale.start_min;
  const span = scale.end_min - origin;
  if (!width || !span) return;
  track.querySelectorAll(".rail-label, .side-label").forEach((node) => node.remove());
  placeHeld(track);
  const items = [...track.querySelectorAll(".bar:not(.held)")]
    .map((node) => ({ node, start: Number(node.dataset.start), end: Number(node.dataset.end) }))
    .sort((a, b) => a.start - b.start);
  items.forEach((item) => {
    item.left = ((item.start - origin) / span) * width;
    item.raw = ((item.end - item.start) / span) * width;
  });
  const laneEnds = [];
  items.forEach((item) => {
    let lane = laneEnds.findIndex((end) => item.start >= end);
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(item.end);
    } else laneEnds[lane] = item.end;
    item.lane = lane;
  });
  const laneCount = Math.max(1, laneEnds.length);
  const inset = 4;
  const nowClear = 6;
  const gap = 4;
  const rails = [];
  const sides = [];
  items.forEach((item) => {
    const later = items.filter((other) => other.lane === item.lane && other.left > item.left + 0.5);
    const nextLeft = later.length ? Math.min(...later.map((other) => other.left)) : width;
    const room = Math.max(0, nextLeft - item.left - 1);
    const floor = Math.min(3, room);
    item.draw = room <= 0 ? 0 : Math.min(Math.max(item.raw, floor), room);
    item.node.style.left = `${item.left}px`;
    item.node.style.width = `${item.draw}px`;
    if (laneCount > 1) {
      item.node.style.top = `${2 + item.lane * 34}px`;
      item.node.style.height = "30px";
      item.node.classList.add("stacked");
    } else {
      item.node.style.top = "";
      item.node.style.height = "";
      item.node.classList.remove("stacked");
    }
    const label = item.node.querySelector(".bar-label");
    const text = label ? label.textContent : "";
    const need = textWidth(text);
    const chip = need + 6;
    item.node.classList.remove("lane-above", "lane-below", "silent");
    if (label) label.style.paddingLeft = "";
    if (!text) {
      item.node.classList.add("silent");
      return;
    }
    const padLeft = Math.max(inset, item.left < nowClear ? nowClear - item.left : inset);
    if (!item.node.classList.contains("stacked") && padLeft + need + inset <= item.draw) {
      label.style.paddingLeft = `${padLeft}px`;
      return;
    }
    item.node.classList.add("silent");
    if (item.node.classList.contains("stacked")) return;
    const sideLeft = item.left + item.draw + gap;
    const sideLimit = nextLeft >= width - 0.5 ? width : nextLeft - gap;
    if (sideLeft >= nowClear && sideLeft + chip <= sideLimit && !hits(sides, sideLeft, sideLeft + chip, gap)) {
      sides.push([sideLeft, sideLeft + chip]);
      const cap = document.createElement("span");
      cap.className = "side-label";
      cap.textContent = text;
      cap.style.left = `${sideLeft}px`;
      track.appendChild(cap);
      return;
    }
    if (track.dataset.links === "1") return;
    let railLeft = Math.max(item.left, nowClear);
    if (railLeft + chip > width) railLeft = Math.max(nowClear, width - chip);
    const railRight = railLeft + chip;
    if (railLeft < nowClear || railRight > width + 1 || hits(rails, railLeft, railRight, gap)) return;
    rails.push([railLeft, railRight]);
    const cap = document.createElement("span");
    cap.className = "rail-label";
    cap.textContent = text;
    cap.style.left = `${railLeft}px`;
    track.appendChild(cap);
  });
}

function placeHeld(track) {
  let cursor = 6;
  track.querySelectorAll(".bar.held").forEach((node) => {
    const label = node.querySelector(".bar-label");
    const text = label ? label.textContent : "";
    const need = textWidth(text) + 8;
    node.style.left = `${cursor}px`;
    node.style.width = `${Math.max(need, 10)}px`;
    node.style.top = "2px";
    node.style.height = "16px";
    node.classList.remove("silent");
    cursor += Math.max(need, 10) + 4;
  });
}

function nodeLabel(key) {
  const copy = t();
  const mock = state.health && state.health.llm === "mock" && state.health.data === "sample";
  if (mock && key === "nodeZetaris") return copy.nodePlant;
  if (mock && key === "nodeExplain") return copy.nodeExplainer;
  return copy[key];
}

function hits(placed, left, right, gap) {
  return placed.some((span) => left < span[1] + gap && right > span[0] - gap);
}

function textWidth(text) {
  if (!textWidth.probe) {
    const probe = document.createElement("span");
    probe.className = "bar-label";
    probe.style.position = "absolute";
    probe.style.visibility = "hidden";
    probe.style.left = "-9999px";
    document.body.appendChild(probe);
    textWidth.probe = probe;
  }
  textWidth.probe.style.padding = "0";
  textWidth.probe.textContent = text;
  return textWidth.probe.offsetWidth;
}

function renderLegend(report) {
  const copy = t();
  const host = $("#legend");
  host.innerHTML = "";
  const order = ["Lithography", "Etch", "CMP", "Deposition", "Metrology", "Clean"];
  const seen = new Set();
  for (const side of [report.gantt.before, report.gantt.after]) {
    for (const row of (side && side.rows) || []) if (row.area) seen.add(row.area);
  }
  for (const area of [...order.filter((name) => seen.has(name)), ...[...seen].filter((name) => !order.includes(name))]) {
    const tone = areaTone(area);
    host.appendChild(legendItem(tone.fill, (copy.areas && copy.areas[area]) || area, tone.ink));
  }
  const rework = [report.gantt.before, report.gantt.after].some((side) =>
    ((side && side.rows) || []).some((row) => (row.bars || []).some((bar) => bar.rework))
  );
  if (rework) host.appendChild(legendItem(null, copy.rework, null, "rework"));
  const held = [report.gantt.before, report.gantt.after].some((side) =>
    ((side && side.rows) || []).some((row) => (row.bars || []).some((bar) => bar.held))
  );
  if (held) host.appendChild(legendItem(null, copy.held, null, "held"));
  host.appendChild(legendItem(null, copy.moved, null, "moved"));
  host.appendChild(legendItem(null, copy.down, null, "hatch-down"));
  host.appendChild(legendItem(null, copy.maint, null, "hatch-maint"));
  host.appendChild(legendItem(null, copy.now, null, "now"));
  host.appendChild(legendItem(null, copy.due, null, "due"));
}

function legendItem(fill, label, ink, kind) {
  const li = document.createElement("li");
  const swatch = document.createElement("span");
  swatch.className = "swatch" + (kind ? ` ${kind}` : "");
  if (fill) {
    swatch.style.background = fill;
    if (ink) swatch.style.boxShadow = `inset 0 0 0 1px ${ink}`;
  }
  li.append(swatch, document.createTextNode(label));
  return li;
}

function showTip(event, bar, equipment, horizon) {
  const copy = t();
  if (bar.held) {
    const tip = $("#tip");
    tip.textContent = `${bar.job_id} · ${copy.held}\n${equipment} · ${bar.step}\n${bar.reason || ""}`;
    tip.hidden = false;
    moveTip(event);
    return;
  }
  const flags = [bar.moved ? copy.moved : "", bar.fresh ? copy.fresh : "", bar.rework ? copy.rework : ""].filter(Boolean).join(" · ");
  const mask = bar.reticle_id ? `\n${copy.reticle} ${bar.reticle_id}` : "";
  const text = `${bar.job_id} · P${bar.priority}\n${equipment} · ${bar.step}\n${formatClock(shift(horizon, bar.start_min)).slice(11, 16)}–${formatClock(shift(horizon, bar.end_min)).slice(11, 16)} · ${formatDuration(bar.end_min - bar.start_min)}${flags ? `\n${flags}` : ""}${mask}`;
  const tip = $("#tip");
  tip.textContent = text;
  tip.hidden = false;
  moveTip(event);
}

function moveTip(event) {
  const tip = $("#tip");
  tip.style.left = `${Math.min(event.clientX + 12, window.innerWidth - 280)}px`;
  tip.style.top = `${event.clientY + 16}px`;
}

function hideTip() {
  $("#tip").hidden = true;
}

function scaleOf(report) {
  const shared = report.gantt && report.gantt.window;
  if (shared && Number(shared.end_min) > Number(shared.start_min || 0)) {
    return {
      start_min: Number(shared.start_min) || 0,
      end_min: Number(shared.end_min),
      step_min: Number(shared.step_min) || 60,
    };
  }
  let end = 0;
  for (const side of [report.gantt && report.gantt.before, report.gantt && report.gantt.after]) {
    if (!side) continue;
    for (const row of side.rows || []) {
      for (const bar of row.bars || []) end = Math.max(end, bar.end_min || 0);
    }
  }
  if (end <= 0) end = 60;
  const padded = end + Math.max(Math.floor(end / 20), 10);
  const steps = [15, 30, 60, 120, 180, 240];
  let step = 240;
  for (const candidate of steps) {
    if (padded <= candidate * 8) {
      step = candidate;
      break;
    }
  }
  return { start_min: 0, end_min: Math.ceil(padded / step) * step, step_min: step };
}

function shortLot(jobId) {
  return String(jobId).replace("LOT-", "");
}

function formatMeasure(value, kind, digits) {
  if (kind === "dur") return formatDuration(value);
  if (kind === "%") return `${Number(value).toFixed(digits)}%`;
  if (kind === "x") return Number(value).toFixed(digits);
  return Number(value).toFixed(digits);
}

function signedMeasure(value, kind, digits) {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatMeasure(Math.abs(value), kind, digits)}`;
}

function paintMode(copy) {
  const health = state.health || {};
  const mock = health.llm === "mock" && health.data === "sample";
  const badge = $("#mode-badge");
  const detail = $("#mode-detail");
  const model = String(health.nemotron_model || "").split("/").pop();
  const dataName = health.data === "zetaris" ? copy.dataZetaris : copy.dataSample;
  badge.textContent = mock ? copy.offline : (copy.badgeLive || "Nightshift");
  badge.className = mock ? "badge" : "badge live";
  detail.textContent = mock
    ? copy.modeDetailMock
    : fill(copy.modeDetailLive, { model: model || copy.badgeLive, data: dataName });
  const tip = mock
    ? copy.modeTipMock
    : fill(copy.modeTipLive, { model: model || copy.badgeLive, data: dataName });
  badge.title = tip;
  detail.title = tip;
}

function paintOverview() {
  const copy = t();
  const overview = state.overview;
  const line = $("#product-line");
  if (line) line.textContent = copy.productLine;
  const kpis = $("#shift-kpis");
  if (!kpis) return;
  kpis.innerHTML = "";
  const values = overview && overview.kpis;
  const cards = [
    ["kpiOtd", values ? `${Number(values.on_time_delivery_pct).toFixed(1)}%` : "—", "otdTip"],
    ["kpiRisk", values ? String(values.lots_at_risk) : "—", "riskTip"],
    ["kpiWip", values ? String(values.wip) : "—", "wipTip"],
    ["kpiUtil", values ? `${Number(values.utilization_pct).toFixed(1)}%` : "—", "utilTip"],
  ];
  for (const [label, value, tip] of cards) {
    const article = document.createElement("article");
    article.innerHTML = `<div class="title">${escapeHtml(copy[label])}</div><div class="value">${escapeHtml(value)}</div>`;
    bindTip(article, copy[tip]);
    kpis.appendChild(article);
  }
  const down = (overview && overview.down_tools) || [];
  const plan = $("#plan-label");
  if (plan) {
    plan.textContent = down.length ? fill(copy.planTitle, { tool: down.join(", ") }) : copy.planTitleUp;
  }
  const legend = $("#plan-legend");
  if (legend) {
    legend.innerHTML = "";
    for (const [klass, label] of [["up", copy.legendUp], ["down", copy.legendDown], ["maint", copy.legendMaint]]) {
      const li = document.createElement("li");
      li.innerHTML = `<i class="swatch ${klass}"></i><span>${escapeHtml(label)}</span>`;
      legend.appendChild(li);
    }
  }
  if (overview && overview.gantt && overview.window) {
    renderGantt($("#gantt-now"), overview.gantt, state.horizon, overview.window, false);
  }
  const recommend = $("#recommend");
  if (!recommend) return;
  recommend.innerHTML = "";
  const id = (overview && overview.recommended) || "litho_down";
  const text = (copy.scenarios && copy.scenarios[id]) || ["", ""];
  const words = document.createElement("div");
  const impact = scenarioImpact(id, copy);
  words.innerHTML = `<strong><em>${escapeHtml(copy.recommended)}</em>${escapeHtml(text[0])}</strong><span>${escapeHtml(impact || text[1])}</span>`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "run";
  button.id = "run-recommended";
  button.textContent = copy.runRecommended;
  button.disabled = state.running;
  button.addEventListener("click", () => run({ scenario: id }));
  recommend.append(words, button);
}

function doneStatus(report) {
  const copy = t();
  const verdict = report && report.verdict && report.verdict.verdict;
  const word = (copy.verdicts && copy.verdicts[verdict]) || copy.done;
  const data = report && report.mode && report.mode.data === "zetaris" ? copy.sourceZetaris : copy.sourceSample;
  return `${word} · ${data}`;
}

function formatFinding(item) {
  if (!item) return "";
  const template = item.code && t().messages && t().messages[item.code];
  if (template) return fill(template, item.params || {});
  if ((state.lang || "en") === "en") return item.detail || "";
  return "";
}

function rationaleText(verdict) {
  if (!verdict) return "";
  const template = verdict.rationale_code && t().messages && t().messages[verdict.rationale_code];
  if (template) return fill(template, {});
  if ((state.lang || "en") === "en") return verdict.rationale || "";
  return "";
}

function fill(template, params) {
  let text = String(template || "");
  for (const [key, value] of Object.entries(params || {})) {
    if (value == null) continue;
    let shown = String(value);
    if (key.endsWith("_at")) shown = shiftClock(value);
    else if (key.endsWith("_min")) shown = formatDuration(value);
    const name = key.endsWith("_at") || key.endsWith("_min") ? key.replace(/_(at|min)$/, "") : key;
    text = text.split(`{${name}}`).join(shown);
  }
  return text;
}

function shiftClock(min) {
  if (min == null || min === "") return "";
  const base = Date.parse(state.horizon);
  if (!Number.isFinite(base)) return formatDuration(min);
  const when = new Date(base + Number(min) * 60000);
  const hh = String(when.getUTCHours()).padStart(2, "0");
  const mm = String(when.getUTCMinutes()).padStart(2, "0");
  const origin = new Date(base);
  const same = when.getUTCFullYear() === origin.getUTCFullYear()
    && when.getUTCMonth() === origin.getUTCMonth()
    && when.getUTCDate() === origin.getUTCDate();
  if (same) return `${hh}:${mm}`;
  const mo = String(when.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(when.getUTCDate()).padStart(2, "0");
  return `${mo}/${dd} ${hh}:${mm}`;
}

function formatDuration(minutes) {
  const lang = state.lang;
  const sign = minutes < 0 ? "−" : "";
  const total = Math.round(Math.abs(minutes));
  if (total < 60) {
    if (lang === "zh") return `${sign}${total} 分钟`;
    if (lang === "ja") return `${sign}${total}分`;
    return `${sign}${total} min`;
  }
  if (total < 48 * 60) {
    const hours = Math.floor(total / 60);
    const mins = total % 60;
    if (mins === 0) {
      if (lang === "zh") return `${sign}${hours} 小时`;
      if (lang === "ja") return `${sign}${hours}時間`;
      return `${sign}${hours} h`;
    }
    if (lang === "zh") return `${sign}${hours} 小时 ${mins} 分`;
    if (lang === "ja") return `${sign}${hours}時間${mins}分`;
    return `${sign}${hours} h ${mins} min`;
  }
  let days = Math.floor(total / 1440);
  let hours = Math.round((total % 1440) / 60);
  if (hours === 24) {
    days += 1;
    hours = 0;
  }
  if (hours === 0) {
    if (lang === "zh") return `${sign}${days} 天`;
    if (lang === "ja") return `${sign}${days}日`;
    return `${sign}${days} d`;
  }
  if (lang === "zh") return `${sign}${days} 天 ${hours} 小时`;
  if (lang === "ja") return `${sign}${days}日${hours}時間`;
  return `${sign}${days} d ${hours} h`;
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

window.addEventListener("resize", () => {
  if (state.report && state.report.gantt) renderCharts(state.report);
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
