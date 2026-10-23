const PRIORITY = {
  1: { fill: "#f0d7a8", ink: "#3d2a08" },
  2: { fill: "#c5e4e1", ink: "#0e3d3a" },
  3: { fill: "#d5e0ea", ink: "#1c3344" },
  4: { fill: "#e4dfd8", ink: "#3a342e" },
};

const NODES = [
  ["scout", "nodeScout"],
  ["query", "nodeZetaris"],
  ["sense", "nodeSense"],
  ["plan", "nodePlan"],
  ["critique", "nodeCritic"],
  ["explain", "nodeExplain"],
  ["commit", "nodeCommit"],
];

const COPY = {
  en: {
    scope: "FAB-A recovery",
    lang: "Language",
    disruption: "Disruption",
    bay: "Bay",
    describe: "Or describe one",
    placeholder: "Litho-02 is down, repair in 10 hours",
    run: "Run recovery",
    running: "Reading the line…",
    refused: "Request refused.",
    idle: "Choose a disruption.",
    headline: "Which disruption should the bay recover?",
    points: [
      "A priority lot blocked on a down tool misses its due time while the book is rebuilt by hand.",
      "ResiliMES reschedules only what the critic will sign.",
      "The loop below is the real run, one step at a time.",
    ],
    full: "Full note",
    mock: "Offline mock. The schedule, the critic, and the engines are real. Nightshift and Zetaris are not called. Secrets stay off this screen.",
    live: "Live path. Data and the explainer use the credentials in the environment. Secrets stay off this screen.",
    offline: "Offline mock",
    clock: "Scenario clock",
    was: "was",
    noSchedule: "No schedule",
    readOnly: "Read only",
    now: "Now",
    moved: "Moved",
    fresh: "New",
    down: "Down",
    maint: "Maintenance",
    lots: "Lots",
    lot: "Lot",
    pri: "Pri",
    before: "Before",
    after: "After",
    tardy: "Tardiness",
    critic: "Why the critic committed this",
    held: "held",
    verified: "contract verified",
    rejected: "Refused alternative",
    explainer: "Explainer",
    checkpoint: "Checkpoint",
    of: "of",
    computed: "computed",
    nodeScout: "Scout",
    nodeZetaris: "Zetaris",
    nodeSense: "Sense",
    nodePlan: "Plan",
    nodeCritic: "Critic",
    nodeExplain: "Nightshift",
    nodeCommit: "Commit",
    kpis: ["On-time delivery", "Weighted tardiness", "Makespan", "Lots at risk"],
    scenarios: {
      litho_down: ["Machine breakdown", "LITHO-02 is down for 10 h. LOT-1001 is blocked, due 18:00 UTC."],
      rush_order: ["Rush order", "A hot lot is due in 3 h. Running lots stay on their tools."],
      material_shortage: ["Material shortage", "RESIST-UV is at zero. Lots that still need it wait."],
    },
    chartBefore: { litho_down: "Wait for repair", rush_order: "Book without the rush", material_shortage: "Resist available" },
    chartAfter: { litho_down: "Rescheduled", rush_order: "Book with the rush", material_shortage: "RESIST-UV stockout" },
  },
  zh: {
    scope: "FAB-A 恢复",
    lang: "语言",
    disruption: "异常",
    bay: "机台",
    describe: "或自己描述",
    placeholder: "光刻机 02 宕机，维修 10 小时",
    run: "开始恢复",
    running: "正在读产线…",
    refused: "请求被拒绝。",
    idle: "选择一个异常。",
    headline: "这一班要先恢复哪一件异常？",
    points: [
      "优先级批次挡在宕机设备上，人工重排的时候交期已经错过。",
      "ResiliMES 只提交评审愿意签字的排程。",
      "下面的循环是真实运行，一步一步出现。",
    ],
    full: "完整说明",
    mock: "离线模拟。排程、评审和引擎是真的。没有调用 Nightshift 和 Zetaris。密钥不会出现在这个画面上。",
    live: "实时路径。数据和说明使用环境中的凭据。密钥不会出现在这个画面上。",
    offline: "离线模拟",
    clock: "场景时钟",
    was: "原先",
    noSchedule: "没有排程",
    readOnly: "只读",
    now: "现在",
    moved: "已移动",
    fresh: "新批次",
    down: "宕机",
    maint: "保养",
    lots: "批次",
    lot: "批次",
    pri: "优先级",
    before: "之前",
    after: "之后",
    tardy: "拖期",
    critic: "评审为什么提交这一版",
    held: "暂扣",
    verified: "合同已验证",
    rejected: "被拒绝的替代方案",
    explainer: "说明",
    checkpoint: "检查点",
    of: "/",
    computed: "计算",
    nodeScout: "Scout",
    nodeZetaris: "Zetaris",
    nodeSense: "感知",
    nodePlan: "计划",
    nodeCritic: "评审",
    nodeExplain: "Nightshift",
    nodeCommit: "提交",
    kpis: ["准时交付", "加权拖期", "总工期", "风险批次"],
    scenarios: {
      litho_down: ["设备故障", "LITHO-02 宕机 10 小时。LOT-1001 被挡住，交期 18:00 UTC。"],
      rush_order: ["急单", "一个热批次要求 3 小时内交货。正在加工的批次留在设备上。"],
      material_shortage: ["物料短缺", "RESIST-UV 库存为零。还需要它的批次等待。"],
    },
    chartBefore: { litho_down: "等待维修", rush_order: "没有急单的账", material_shortage: "光刻胶充足" },
    chartAfter: { litho_down: "已重排", rush_order: "加入急单", material_shortage: "RESIST-UV 断料" },
  },
  ja: {
    scope: "FAB-A の回復",
    lang: "言語",
    disruption: "異常",
    bay: "装置",
    describe: "または文章で",
    placeholder: "露光機 02 が停止。修理は 10 時間",
    run: "回復を実行",
    running: "ラインを読んでいる…",
    refused: "依頼は拒否された。",
    idle: "異常を選ぶ。",
    headline: "この直で、どの異常から回復するか？",
    points: [
      "停止装置に止まった優先ロットは、手で組み直している間に納期を落とす。",
      "ResiliMES は、批評が署名する日程だけを確定する。",
      "下のループは実際の実行で、一歩ずつ現れる。",
    ],
    full: "全文",
    mock: "オフライン模擬。日程、批評、エンジンは本物。Nightshift と Zetaris は呼んでいない。秘密はこの画面に出ない。",
    live: "ライブ経路。データと説明は環境の資格情報を使う。秘密はこの画面に出ない。",
    offline: "オフライン模擬",
    clock: "シナリオ時計",
    was: "前は",
    noSchedule: "日程なし",
    readOnly: "読み取りのみ",
    now: "今",
    moved: "移動",
    fresh: "新規",
    down: "停止",
    maint: "保全",
    lots: "ロット",
    lot: "ロット",
    pri: "優先",
    before: "前",
    after: "後",
    tardy: "遅延",
    critic: "批評がこれを確定した理由",
    held: "保留",
    verified: "契約を検証",
    rejected: "拒否した代替",
    explainer: "説明",
    checkpoint: "チェックポイント",
    of: "/",
    computed: "計算",
    nodeScout: "Scout",
    nodeZetaris: "Zetaris",
    nodeSense: "把握",
    nodePlan: "計画",
    nodeCritic: "批評",
    nodeExplain: "Nightshift",
    nodeCommit: "確定",
    kpis: ["納期遵守", "加重遅延", "総所要", "危険ロット"],
    scenarios: {
      litho_down: ["装置故障", "LITHO-02 は 10 時間停止。LOT-1001 が止まり、納期は 18:00 UTC。"],
      rush_order: ["特急", "特急ロットの納期は 3 時間後。加工中のロットは装置に残す。"],
      material_shortage: ["材料不足", "RESIST-UV は在庫ゼロ。まだ必要なロットは待つ。"],
    },
    chartBefore: { litho_down: "修理を待つ", rush_order: "特急なし", material_shortage: "レジストあり" },
    chartAfter: { litho_down: "再計画", rush_order: "特急を入れる", material_shortage: "RESIST-UV 欠品" },
  },
};

const BAY = [
  ["LITHO-01", "tool"],
  ["LITHO-02", "tool"],
  ["ETCH-01", "tool"],
  ["ETCH-02", "tool"],
  ["CMP-01", "tool"],
  ["DEP-01", "tool"],
  ["RESIST-UV", "material"],
];

const ALERT = {
  litho_down: "LITHO-02",
  rush_order: "LITHO-01",
  material_shortage: "RESIST-UV",
};

const state = {
  lang: localStorage.getItem("resilimes.lang") || "en",
  scenario: "litho_down",
  report: null,
  steps: [],
  horizon: "",
  health: null,
  running: false,
};

const $ = (id) => document.querySelector(id);

document.addEventListener("DOMContentLoaded", init);

async function init() {
  state.health = await getJson("/api/health");
  state.horizon = state.health.horizon;
  const payload = await getJson("/api/scenarios");
  state.scenarioItems = payload.scenarios;
  paintChrome();
  paintBay({});
  paintAgents();
  paintFinding(null);
  $("#run").addEventListener("click", () => {
    const incident = $("#incident").value.trim();
    if (incident) run({ incident });
    else run({ scenario: state.scenario });
  });
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.addEventListener("click", () => {
      state.lang = button.getAttribute("data-lang");
      localStorage.setItem("resilimes.lang", state.lang);
      document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang === "ja" ? "ja" : "en";
      paintChrome();
      if (state.report) render(state.report);
      else paintFinding(null);
      paintAgents();
    });
  });
}

function t() {
  return COPY[state.lang] || COPY.en;
}

function paintChrome() {
  const copy = t();
  document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang === "ja" ? "ja" : "en";
  $("#scope").textContent = copy.scope;
  $("#lang-label").textContent = copy.lang;
  $("#disruption-label").textContent = copy.disruption;
  $("#bay-label").textContent = copy.bay;
  $("#describe-label").textContent = copy.describe;
  $("#incident").placeholder = copy.placeholder;
  $("#run").textContent = copy.run;
  $("#detail-summary").textContent = copy.full;
  $("#lots-label").textContent = copy.lots;
  $("#th-lot").textContent = copy.lot;
  $("#th-pri").textContent = copy.pri;
  $("#th-before").textContent = copy.before;
  $("#th-after").textContent = copy.after;
  $("#th-tardy").textContent = copy.tardy;
  $("#critic-label").textContent = copy.critic;
  $("#clock").textContent = `${copy.clock} ${formatClock(state.horizon)} UTC`;
  const mock = state.health.llm === "mock" && state.health.data === "sample";
  const badge = $("#mode-badge");
  badge.textContent = mock ? copy.offline : state.health.label;
  badge.className = mock ? "badge" : "badge live";
  const banner = $("#banner");
  banner.hidden = false;
  banner.textContent = mock ? copy.mock : copy.live;
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.setAttribute("aria-pressed", button.getAttribute("data-lang") === state.lang ? "true" : "false");
  });
  paintScenarios();
  if (!state.running && !state.report) $("#status").textContent = copy.idle;
}

function paintScenarios() {
  const host = $("#scenarios");
  const copy = t();
  host.innerHTML = "";
  for (const item of state.scenarioItems || []) {
    const text = copy.scenarios[item.id] || [item.title, item.summary];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scenario" + (item.id === state.scenario ? " active" : "");
    button.innerHTML = `<strong>${escapeHtml(text[0])}</strong><span>${escapeHtml(text[1])}</span>`;
    button.addEventListener("click", () => {
      state.scenario = item.id;
      $("#incident").value = "";
      paintScenarios();
      run({ scenario: item.id });
    });
    host.appendChild(button);
  }
}

function paintBay(statusById) {
  const host = $("#bay");
  host.innerHTML = "";
  for (const [id, kind] of BAY) {
    const li = document.createElement("li");
    li.dataset.id = id;
    const status = statusById[id] || (kind === "material" ? "ok" : "—");
    const lamp = lampClass(status, kind);
    li.innerHTML = `<span class="lamp ${lamp}"></span><span>${escapeHtml(id)}</span><small>${escapeHtml(statusLabel(status))}</small>`;
    host.appendChild(li);
  }
}

function lampClass(status, kind) {
  if (kind === "material" && status === "short") return "short";
  if (status === "DOWN") return "down";
  if (status === "MAINTENANCE") return "maint";
  if (status === "RUNNING" || status === "IDLE" || status === "ok") return "up";
  return "";
}

function statusLabel(status) {
  const copy = t();
  if (status === "DOWN") return copy.down;
  if (status === "MAINTENANCE") return copy.maint;
  if (status === "short") return copy.down;
  return status;
}

function flash(id) {
  const row = document.querySelector(`.bay li[data-id="${id}"]`);
  if (!row) return;
  const lamp = row.querySelector(".lamp");
  lamp.classList.remove("flash");
  void lamp.offsetWidth;
  lamp.classList.add("flash");
  if (id === "RESIST-UV") lamp.className = "lamp short flash";
  if (id === "LITHO-02") lamp.className = "lamp down flash";
}

async function run(body) {
  if (state.running) return;
  state.running = true;
  state.steps = [];
  state.report = null;
  $("#run").disabled = true;
  $("#status").textContent = t().running;
  $("#result").hidden = true;
  $("#kpis").hidden = true;
  paintFinding(null);
  paintAgents();
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
        paintAgents();
        if (payload.phase === "alert" && body.scenario) flash(ALERT[body.scenario]);
      } else if (kind === "report") {
        state.report = payload;
        render(payload);
      } else if (kind === "error") {
        throw new Error(payload.detail || "Recovery failed");
      }
    });
    const report = state.report;
    $("#status").textContent = report && report.blocked
      ? t().refused
      : `${report && report.verdict ? report.verdict.verdict : "done"} · ${report && report.mode ? report.mode.label : ""}`;
  } catch (error) {
    $("#status").textContent = error.message;
  } finally {
    state.running = false;
    $("#run").disabled = false;
  }
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

function paintAgents() {
  const copy = t();
  const host = $("#agents");
  host.innerHTML = "";
  const seen = new Map(state.steps.map((step) => [step.phase, step]));
  let active = "";
  for (const step of state.steps) {
    if (NODES.some(([phase]) => phase === step.phase)) active = step.phase;
  }
  for (const [phase, key] of NODES) {
    const step = seen.get(phase);
    const li = document.createElement("li");
    li.className = step ? (phase === active && state.running ? "on" : "done") : "";
    const ms = step ? `${step.elapsed_ms} ms` : "";
    li.innerHTML = `<span class="who">${escapeHtml(copy[key])}</span><span class="ms">${escapeHtml(ms)}</span>`;
    host.appendChild(li);
  }
  const last = state.steps[state.steps.length - 1];
  const line = $("#agent-line");
  const evidence = $("#agent-evidence");
  if (!last) {
    line.textContent = "";
    evidence.textContent = "";
    return;
  }
  const slot = last.slots || {};
  const checkpoint = slot.checkpoint ? ` · ${copy.checkpoint} ${slot.checkpoint} ${copy.of} ${slot.checkpoints}` : "";
  line.textContent = `${last.summary}${checkpoint} · ${copy.computed} ${last.elapsed_ms} ms`;
  const lines = (last.evidence || []).slice(0, 2);
  evidence.textContent = lines.join("\n");
}

function render(report) {
  paintFinding(report);
  renderKpis(report);
  const copy = t();
  const beforeName = (copy.chartBefore && copy.chartBefore[report.scenario_id]) || report.before_label;
  const afterName = (copy.chartAfter && copy.chartAfter[report.scenario_id]) || report.after_label;
  $("#before-label").textContent = beforeName;
  $("#after-label").textContent = afterName;
  $("#clock").textContent = `${copy.clock} ${formatClock(report.horizon)} UTC`;
  const result = $("#result");
  if (!report.gantt) {
    result.hidden = true;
    updateBay(report);
    return;
  }
  result.hidden = false;
  const scale = scaleOf(report);
  renderGantt($("#gantt-before"), report.gantt.before, report.horizon, scale, false);
  renderGantt($("#gantt-after"), report.gantt.after, report.horizon, scale, true);
  renderLegend(report);
  renderLots(report.outcomes || []);
  renderDecision(report);
  updateBay(report);
}

function paintFinding(report) {
  const copy = t();
  const brief = report && report.brief && report.brief[state.lang];
  const list = $("#points");
  list.innerHTML = "";
  if (!brief && state.running) {
    $("#headline").textContent = copy.running;
    $("#detail").hidden = true;
    return;
  }
  $("#headline").textContent = brief ? brief.headline : copy.headline;
  const points = brief ? brief.points : copy.points;
  for (const point of points || []) {
    const li = document.createElement("li");
    li.textContent = point;
    list.appendChild(li);
  }
  const detail = $("#detail");
  if (brief && brief.detail) {
    detail.hidden = false;
    $("#detail-body").textContent = brief.detail;
  } else {
    detail.hidden = true;
  }
}

function renderKpis(report) {
  const host = $("#kpis");
  const copy = t();
  host.hidden = false;
  if (!report.kpis) {
    host.innerHTML = `<div class="kpi"><p class="label">${escapeHtml(copy.noSchedule)}</p><p class="value">—</p><p class="delta flat">${escapeHtml(report.block_reason || copy.readOnly)}</p></div>`;
    return;
  }
  const cards = [
    ["on_time_delivery_pct", "%", 1, true],
    ["weighted_tardiness_min", "dur", 0, false],
    ["makespan_min", "dur", 0, false],
    ["lots_at_risk", "", 0, false],
  ];
  host.innerHTML = "";
  cards.forEach(([key, kind, digits, upGood], index) => {
    const before = report.kpis.before[key];
    const after = report.kpis.after[key];
    const delta = report.kpis.delta[key];
    const improved = upGood ? delta > 0.05 : delta < -0.05;
    const worse = upGood ? delta < -0.05 : delta > 0.05;
    const tone = improved ? "good" : worse ? "bad" : "flat";
    const article = document.createElement("div");
    article.className = "kpi";
    article.innerHTML = `
      <p class="label">${escapeHtml(copy.kpis[index])}</p>
      <p class="value">${escapeHtml(formatMeasure(after, kind, digits))}</p>
      <p class="delta ${tone}">${escapeHtml(signedMeasure(delta, kind, digits))}</p>
      <p class="was flat">${escapeHtml(copy.was)} ${escapeHtml(formatMeasure(before, kind, digits))}</p>`;
    host.appendChild(article);
  });
}

function renderGantt(host, gantt, horizon, scale, draw) {
  host.innerHTML = "";
  if (!gantt) return;
  const wrap = document.createElement("div");
  wrap.className = "gantt" + (draw ? " draw" : "");
  for (const row of gantt.rows) {
    const line = document.createElement("div");
    line.className = "gantt-row";
    const label = document.createElement("div");
    label.className = "gantt-label";
    label.innerHTML = `${escapeHtml(row.equipment_id)}<small>${escapeHtml(statusLabel(row.status))}</small>`;
    const track = document.createElement("div");
    track.className = "track";
    if (row.available_at_min > 0) {
      const shade = document.createElement("div");
      shade.className = row.status === "MAINTENANCE" ? "shade maint" : "shade down";
      shade.style.left = "0";
      shade.style.width = `${(row.available_at_min / scale) * 100}%`;
      track.appendChild(shade);
    }
    for (const bar of row.bars) {
      const node = document.createElement("div");
      const tone = PRIORITY[bar.priority] || PRIORITY[4];
      node.className = "bar" + (bar.moved ? " moved" : "") + (bar.fresh ? " fresh" : "") + (bar.moved && !draw ? " leaving" : "");
      node.style.left = `${(bar.start_min / scale) * 100}%`;
      node.style.width = `${Math.max(1.4, ((bar.end_min - bar.start_min) / scale) * 100)}%`;
      node.style.background = tone.fill;
      node.style.color = tone.ink;
      const label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = shortLot(bar.job_id);
      node.appendChild(label);
      requestAnimationFrame(() => {
        if (node.scrollWidth > node.clientWidth + 1) node.classList.add("tight");
      });
      node.addEventListener("pointerenter", (event) => showTip(event, bar, row.equipment_id, horizon));
      node.addEventListener("pointermove", moveTip);
      node.addEventListener("pointerleave", hideTip);
      track.appendChild(node);
    }
    line.append(label, track);
    wrap.appendChild(line);
  }
  const axis = document.createElement("div");
  axis.className = "axis";
  const step = Math.max(60, Math.round(scale / 4 / 60) * 60);
  for (let minute = 0; minute <= scale; minute += step) {
    const tick = document.createElement("span");
    tick.textContent = minute === 0 ? t().now : formatClock(shift(horizon, minute)).slice(11, 16);
    if (minute === 0) tick.className = "now-tick";
    axis.appendChild(tick);
  }
  host.append(wrap, axis);
}

function renderLegend(report) {
  const copy = t();
  const host = $("#legend");
  host.innerHTML = "";
  const lots = new Map();
  for (const row of report.outcomes || []) lots.set(row.job_id, row.priority);
  for (const [job, priority] of lots) {
    const tone = PRIORITY[priority] || PRIORITY[4];
    host.appendChild(legendItem(tone.fill, `${job} · P${priority}`, tone.ink));
  }
  host.appendChild(legendItem(null, copy.moved, null, "moved"));
  host.appendChild(legendItem(null, copy.down, null, "hatch-down"));
  host.appendChild(legendItem(null, copy.maint, null, "hatch-maint"));
  host.appendChild(legendItem(null, copy.now, null, "now"));
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

function renderLots(rows) {
  const body = $("#lots");
  const copy = t();
  body.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    const better = row.after_tardiness_min < row.before_tardiness_min;
    const worse = row.after_tardiness_min > row.before_tardiness_min;
    const tone = better ? "good" : worse ? "bad" : "";
    const after = row.after_equipment || copy.held;
    tr.innerHTML = `
      <td class="mono">${escapeHtml(row.job_id)}</td>
      <td class="num">${row.priority}</td>
      <td class="mono">${escapeHtml(row.before_equipment || "—")}</td>
      <td class="mono">${escapeHtml(after)}</td>
      <td class="num ${tone}">${escapeHtml(formatDuration(row.before_tardiness_min))} → ${escapeHtml(formatDuration(row.after_tardiness_min))}</td>`;
    body.appendChild(tr);
  }
}

function renderDecision(report) {
  const copy = t();
  const host = $("#decision");
  const verdict = report.verdict ? report.verdict.verdict : report.blocked ? "blocked" : "—";
  const rejected = report.rejected_alternative && report.rejected_alternative.critique;
  const violation = rejected && rejected.violations && rejected.violations[0];
  const contract = report.contract;
  host.innerHTML = `
    <p><span class="pill ${escapeHtml(verdict)}">${escapeHtml(verdict)}</span>
      ${contract ? `<span class="pill">${escapeHtml(copy.verified)}</span>` : ""}</p>
    <p>${escapeHtml(report.verdict ? report.verdict.rationale : report.narrative)}</p>
    ${violation ? `<p>${escapeHtml(copy.rejected)} · ${escapeHtml(violation.constraint)}: ${escapeHtml(violation.detail)}</p>` : ""}
    ${contract ? `<p class="meta">${escapeHtml(contract.modelProfile || "")} · ${escapeHtml(contract.contractId || "")}</p>` : ""}
    ${report.provider_call ? `<p class="meta">${escapeHtml(copy.explainer)} ${escapeHtml(report.provider_call.provider)} · ${escapeHtml(report.provider_call.model)} · ${Math.round(report.provider_call.latency_ms)} ms${report.provider_call.mocked ? " · mock" : ""}</p>` : ""}`;
}

function updateBay(report) {
  const status = {};
  const rows = report.gantt && report.gantt.after && report.gantt.after.rows;
  if (rows) {
    for (const row of rows) status[row.equipment_id] = row.status;
  }
  if (report.scenario_id === "material_shortage") status["RESIST-UV"] = "short";
  paintBay(status);
}

function showTip(event, bar, equipment, horizon) {
  const tip = $("#tip");
  const copy = t();
  const flags = [bar.moved ? copy.moved : "", bar.fresh ? copy.fresh : ""].filter(Boolean).join(" · ");
  tip.innerHTML = `<strong>${escapeHtml(bar.job_id)}</strong> · P${bar.priority}<br>${escapeHtml(equipment)} · ${escapeHtml(bar.step)}<br>${escapeHtml(formatClock(shift(horizon, bar.start_min)).slice(11, 16))}–${escapeHtml(formatClock(shift(horizon, bar.end_min)).slice(11, 16))} · ${escapeHtml(formatDuration(bar.end_min - bar.start_min))}${flags ? `<br>${escapeHtml(flags)}` : ""}`;
  tip.hidden = false;
  moveTip(event);
}

function moveTip(event) {
  const tip = $("#tip");
  tip.style.left = `${Math.min(event.clientX + 12, window.innerWidth - 300)}px`;
  tip.style.top = `${event.clientY + 16}px`;
}

function hideTip() {
  $("#tip").hidden = true;
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

function shortLot(jobId) {
  return String(jobId).replace("LOT-", "");
}

function formatMeasure(value, kind, digits) {
  if (kind === "dur") return formatDuration(value);
  if (kind === "%") return `${Number(value).toFixed(digits)}%`;
  return Number(value).toFixed(digits);
}

function signedMeasure(value, kind, digits) {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  const body = formatMeasure(Math.abs(value), kind, digits);
  return `${sign}${body}`;
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
