const AREA_TONE = {
  light: {
    Lithography: { fill: "#dbe1fb", ink: "#1e1b4b" },
    Etch: { fill: "#cff4f6", ink: "#0c4a4e" },
    CMP: { fill: "#e6d9f7", ink: "#3b0764" },
    Deposition: { fill: "#d4f3e8", ink: "#064e3b" },
  },
  dark: {
    Lithography: { fill: "#312e81", ink: "#e0e7ff" },
    Etch: { fill: "#155e75", ink: "#cffafe" },
    CMP: { fill: "#5b21b6", ink: "#f3e8ff" },
    Deposition: { fill: "#115e59", ink: "#ccfbf1" },
  },
};

function areaTone(area) {
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const table = AREA_TONE[theme];
  return table[area] || table.Deposition;
}

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
    wait: "Waiting",
    runState: "Running",
    done: "Done",
    reads: "reads",
    facts: "facts",
    ops: "operations",
    holds: "holds",
    events: "events",
    loopLabel: "Recovery loop",
    change: "Change",
    byArea: "Utilization by area",
    kpiOtd: "On-time delivery",
    kpiTardy: "Weighted tardiness",
    kpiSpan: "Makespan",
    kpiUtil: "Utilization",
    kpiChange: "Changeovers",
    kpiRisk: "Lots at risk",
    kpiMoved: "Lots moved",
    kpiLead: "Mean lead time",
    kpiWait: "Mean wait",
    kpiX: "X-factor",
    utilTip: "One window for both books: the longer makespan. Busy time divided by the time tools are up. Down time is excluded and listed below, so a shorter book cannot raise this number.",
    xTip: "Mean time from the scenario clock to completion, divided by raw process time. 1.0 is all processing.",
    downWindow: "Down in this window",
    byTool: "By tool",
    byLot: "By lot",
    whereWait: "Where the wait is",
    route: "Route",
    waitGap: "wait",
    themeLight: "Light",
    themeDark: "Dark",
    intents: {
      machine_down: "machine down",
      rush_order: "rush order",
      material_shortage: "material shortage",
      query_status: "status",
      explain: "explain",
      emergency_stop: "emergency stop",
    },
    verdicts: { accept: "accepted", conditional: "conditional", reject: "rejected" },
    areas: { Lithography: "Lithography", Etch: "Etch", CMP: "CMP", Deposition: "Deposition" },
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
    wait: "等待",
    runState: "运行",
    done: "完成",
    reads: "次读取",
    facts: "条事实",
    ops: "道工序",
    holds: "个暂扣",
    events: "条事件",
    loopLabel: "恢复循环",
    change: "变化",
    byArea: "各区域利用率",
    kpiOtd: "准时交付",
    kpiTardy: "加权拖期",
    kpiSpan: "总工期",
    kpiUtil: "利用率",
    kpiChange: "换型",
    kpiRisk: "风险批次",
    kpiMoved: "移动批次",
    kpiLead: "平均前置时间",
    kpiWait: "平均等待",
    kpiX: "X 因子",
    utilTip: "两本账用同一个窗口，取较长的总工期。忙时除以设备可用的时间。宕机时间不进分母，列在下面，所以较短的账不会把这个数抬高。",
    xTip: "从场景时钟到完工的平均时间，除以纯加工时间。1.0 表示全是加工。",
    downWindow: "本窗口宕机",
    byTool: "按设备",
    byLot: "按批次",
    whereWait: "等待在哪",
    route: "路线",
    waitGap: "等待",
    themeLight: "浅色",
    themeDark: "深色",
    intents: {
      machine_down: "设备宕机",
      rush_order: "急单",
      material_shortage: "物料短缺",
      query_status: "状态",
      explain: "说明",
      emergency_stop: "紧急停止",
    },
    verdicts: { accept: "接受", conditional: "有条件", reject: "拒绝" },
    areas: { Lithography: "光刻", Etch: "刻蚀", CMP: "CMP", Deposition: "沉积" },
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
    wait: "待機",
    runState: "実行",
    done: "完了",
    reads: "件の読取",
    facts: "件の事実",
    ops: "工程",
    holds: "件の保留",
    events: "件のイベント",
    loopLabel: "回復ループ",
    change: "変化",
    byArea: "エリア別の稼働率",
    kpiOtd: "納期遵守",
    kpiTardy: "加重遅延",
    kpiSpan: "総所要",
    kpiUtil: "稼働率",
    kpiChange: "段取り",
    kpiRisk: "危険ロット",
    kpiMoved: "移動ロット",
    kpiLead: "平均リードタイム",
    kpiWait: "平均待ち",
    kpiX: "X ファクター",
    utilTip: "二つの帳票は同じ窓。長い方の総所要を使う。稼働時間を、装置が上がっている時間で割る。停止時間は分母に入れず下に示す。短い帳票だから割合は上がらない。",
    xTip: "シナリオ時計から完了までの平均を、正味加工時間で割る。1.0 は加工だけ。",
    downWindow: "この窓の停止",
    byTool: "装置別",
    byLot: "ロット別",
    whereWait: "待ちの場所",
    route: "経路",
    waitGap: "待ち",
    themeLight: "ライト",
    themeDark: "ダーク",
    intents: {
      machine_down: "装置停止",
      rush_order: "特急",
      material_shortage: "材料不足",
      query_status: "状態",
      explain: "説明",
      emergency_stop: "非常停止",
    },
    verdicts: { accept: "受理", conditional: "条件付き", reject: "拒否" },
    areas: { Lithography: "露光", Etch: "エッチング", CMP: "CMP", Deposition: "成膜" },
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
  theme: localStorage.getItem("resilimes.theme") === "dark" ? "dark" : "light",
  view: "tool",
  routeJob: "",
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
  applyTheme();
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
  $("#theme").addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
    if (state.report) render(state.report);
    else paintChrome();
  });
  document.addEventListener("click", (event) => {
    const route = $("#route");
    if (!route || route.hidden) return;
    if (event.target.closest && event.target.closest("#route, .bar")) return;
    closeRoute();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeRoute();
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
  const theme = $("#theme");
  if (theme) theme.textContent = state.theme === "dark" ? copy.themeDark : copy.themeLight;
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
    paintAgents();
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
  host.setAttribute("aria-label", copy.loopLabel);
  host.innerHTML = "";
  const seen = new Map(state.steps.map((step) => [step.phase, step]));
  let active = "";
  for (const step of state.steps) {
    if (NODES.some(([phase]) => phase === step.phase)) active = step.phase;
  }
  NODES.forEach(([phase, key], index) => {
    const step = seen.get(phase);
    const running = Boolean(step) && phase === active && state.running;
    const li = document.createElement("li");
    li.className = running ? "on" : step ? "done" : "wait";
    const no = document.createElement("span");
    no.className = "step-no";
    no.textContent = String(index + 1).padStart(2, "0");
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = copy[key];
    const status = document.createElement("span");
    status.className = "state";
    status.textContent = running ? copy.runState : step ? copy.done : copy.wait;
    const out = document.createElement("span");
    out.className = "out";
    out.textContent = step ? stepOutput(phase, step.slots || {}, copy) : "";
    const ms = document.createElement("span");
    ms.className = "ms";
    ms.textContent = step ? `${step.elapsed_ms} ms` : "";
    li.append(no, who, status, out, ms);
    host.appendChild(li);
  });
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

function stepOutput(phase, slots, copy) {
  if (phase === "scout") {
    const raw = String(slots.intent || "").replace(/^plant\./, "");
    const label = (copy.intents && copy.intents[raw]) || raw.replaceAll("_", " ");
    const conf = typeof slots.confidence === "number" ? ` · ${Math.round(slots.confidence * 100)}%` : "";
    return `${label}${conf}`;
  }
  if (phase === "query") return `${slots.reads ?? 0} ${copy.reads}`;
  if (phase === "sense") return `${slots.facts ?? 0} ${copy.facts}`;
  if (phase === "plan") return `${slots.operations ?? 0} ${copy.ops} · ${slots.holds ?? 0} ${copy.holds}`;
  if (phase === "critique") return String((copy.verdicts && copy.verdicts[slots.verdict]) || slots.verdict || "");
  if (phase === "explain") {
    const model = String(slots.model || "").split("/").pop();
    return [slots.provider, model].filter(Boolean).join(" · ");
  }
  if (phase === "commit") return `${slots.events ?? 0} ${copy.events}`;
  return "";
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
  paintViews();
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
  host.innerHTML = "";
  if (!report.kpis) {
    const empty = document.createElement("p");
    empty.className = "board-empty";
    empty.textContent = report.block_reason || copy.readOnly;
    host.appendChild(empty);
    return;
  }
  const specs = [
    ["on_time_delivery_pct", copy.kpiOtd, "%", 1, true, ""],
    ["weighted_tardiness_min", copy.kpiTardy, "dur", 0, false, ""],
    ["makespan_min", copy.kpiSpan, "dur", 0, false, ""],
    ["mean_lead_min", copy.kpiLead, "dur", 0, false, ""],
    ["mean_wait_min", copy.kpiWait, "dur", 0, false, ""],
    ["mean_x_factor", copy.kpiX, "x", 2, false, copy.xTip],
    ["utilization_pct", copy.kpiUtil, "%", 1, null, copy.utilTip],
    ["setup_changes", copy.kpiChange, "", 0, false, ""],
    ["lots_at_risk", copy.kpiRisk, "", 0, false, ""],
  ];
  const table = document.createElement("table");
  table.className = "compare";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["", copy.before, copy.after, copy.change]) {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  }
  head.appendChild(headRow);
  const body = document.createElement("tbody");
  for (const [key, label, kind, digits, upGood, tip] of specs) {
    if (report.kpis.before[key] === undefined) continue;
    const before = report.kpis.before[key];
    const after = report.kpis.after[key];
    const delta = report.kpis.delta[key];
    body.appendChild(compareRow(
      label,
      formatMeasure(before, kind, digits),
      formatMeasure(after, kind, digits),
      signedMeasure(delta, kind, digits),
      deltaTone(delta, upGood),
      false,
      tip,
    ));
  }
  const moved = report.kpis.lots_moved || [];
  body.appendChild(compareRow(
    copy.kpiMoved,
    "—",
    String(moved.length),
    moved.length ? moved.join(", ") : "—",
    "flat",
    true,
  ));
  table.append(head, body);
  const side = document.createElement("div");
  side.className = "side";
  side.append(
    renderAreas(report.kpis.areas || {}, copy),
    renderDown(report.kpis.down || {}, copy),
    renderWaits(report.kpis.waits || {}, copy),
  );
  host.append(table, side);
}

function compareRow(label, before, after, change, tone, ids, tip) {
  const tr = document.createElement("tr");
  const values = [label, before, after, change];
  values.forEach((text, index) => {
    const cell = document.createElement(index === 0 ? "th" : "td");
    if (index > 0) cell.className = "num" + (index === 3 ? ` ${tone}` : "") + (index === 3 && ids ? " ids" : "");
    cell.textContent = text;
    tr.appendChild(cell);
  });
  if (tip) tr.querySelector("th").append(infoButton(tip));
  return tr;
}

function infoButton(text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "info";
  button.textContent = "i";
  button.setAttribute("aria-label", text);
  const tip = document.createElement("span");
  tip.className = "info-tip";
  tip.setAttribute("role", "tooltip");
  tip.textContent = text;
  const place = () => {
    const rect = button.getBoundingClientRect();
    const width = 240;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    tip.style.left = `${left}px`;
    const below = rect.bottom + 6;
    tip.style.top = `${below}px`;
    tip.style.bottom = "auto";
    const height = tip.offsetHeight || 72;
    if (below + height > window.innerHeight - 8) {
      tip.style.top = "auto";
      tip.style.bottom = `${window.innerHeight - rect.top + 6}px`;
    }
  };
  button.addEventListener("mouseenter", place);
  button.addEventListener("focus", place);
  button.appendChild(tip);
  return button;
}

function renderDown(down, copy) {
  const note = document.createElement("p");
  note.className = "down-note";
  const before = down.before || [];
  const after = down.after || [];
  if (!before.length && !after.length) {
    note.hidden = true;
    return note;
  }
  const lamp = document.createElement("span");
  lamp.className = "lamp down";
  const text = (rows) => rows.map((row) => {
    const word = row.status === "MAINTENANCE" ? copy.maint : copy.down;
    return `${row.equipment_id} · ${word} · ${formatDuration(row.down_min)}`;
  }).join(", ");
  const same = text(before) === text(after);
  const label = document.createElement("span");
  label.textContent = same
    ? `${copy.downWindow}: ${text(after)}`
    : `${copy.before} ${text(before)} · ${copy.after} ${text(after)}`;
  note.append(lamp, label);
  return note;
}

function renderWaits(waits, copy) {
  const wrap = document.createElement("div");
  wrap.className = "waits";
  const title = document.createElement("h3");
  title.textContent = copy.whereWait;
  wrap.appendChild(title);
  const after = (waits.after || []).slice(0, 4);
  if (!after.length) return wrap;
  const before = new Map((waits.before || []).map((row) => [`${row.from_step}>${row.to_step}`, row]));
  const peak = Math.max(...after.map((row) => Number(row.avg_min) || 0), 1);
  for (const row of after) {
    const line = document.createElement("div");
    line.className = "wait-row";
    const name = document.createElement("span");
    name.textContent = `${row.from_step} → ${row.to_step}`;
    const bar = document.createElement("span");
    bar.className = "wait-bar";
    const fill = document.createElement("i");
    fill.style.width = `${Math.max(0, Math.min(100, (Number(row.avg_min) / peak) * 100))}%`;
    bar.appendChild(fill);
    const fig = document.createElement("span");
    fig.className = "wait-fig";
    const prior = before.get(`${row.from_step}>${row.to_step}`);
    const delta = prior ? Number(row.avg_min) - Number(prior.avg_min) : 0;
    const tone = prior ? deltaTone(delta, false) : "flat";
    fig.textContent = formatDuration(row.avg_min);
    fig.classList.add(tone);
    line.append(name, bar, fig);
    wrap.appendChild(line);
  }
  return wrap;
}

function deltaTone(delta, upGood) {
  if (upGood === null || Math.abs(delta) <= 0.05) return "flat";
  return (upGood ? delta > 0 : delta < 0) ? "good" : "bad";
}

function renderAreas(sides, copy) {
  const wrap = document.createElement("div");
  wrap.className = "areas";
  const title = document.createElement("h3");
  title.textContent = copy.byArea;
  const key = document.createElement("p");
  key.className = "area-key";
  key.append(meterKey("before"), document.createTextNode(` ${copy.before} `), meterKey("after"), document.createTextNode(` ${copy.after}`));
  wrap.append(title, key);
  const before = new Map((sides.before || []).map((row) => [row.area, row]));
  const after = new Map((sides.after || []).map((row) => [row.area, row]));
  const names = [...new Set([...before.keys(), ...after.keys()])].sort();
  for (const name of names) {
    const bPct = before.has(name) ? before.get(name).utilization_pct : 0;
    const aPct = after.has(name) ? after.get(name).utilization_pct : 0;
    const row = document.createElement("div");
    row.className = "area";
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = (copy.areas && copy.areas[name]) || name;
    const fig = document.createElement("span");
    fig.className = "fig";
    fig.textContent = `${formatMeasure(bPct, "%", 1)} → ${formatMeasure(aPct, "%", 1)}`;
    const meters = document.createElement("span");
    meters.className = "meters";
    meters.append(meterBar("before", bPct), meterBar("after", aPct));
    row.append(label, fig, meters);
    wrap.appendChild(row);
  }
  return wrap;
}

function meterKey(kind) {
  return meterBar(kind, 100);
}

function meterBar(kind, pct) {
  const span = document.createElement("span");
  span.className = `meter ${kind}`;
  const fill = document.createElement("i");
  fill.style.width = `${Math.max(0, Math.min(100, Number(pct) || 0))}%`;
  span.appendChild(fill);
  return span;
}

function renderGantt(host, gantt, horizon, scale, draw) {
  host.innerHTML = "";
  if (!gantt) return;
  const wrap = document.createElement("div");
  wrap.className = "gantt" + (draw ? " draw" : "");
  wrap.dataset.scale = String(scale);
  const rows = state.view === "lot" ? lotRows(gantt) : gantt.rows;
  for (const row of rows) {
    const line = document.createElement("div");
    line.className = "gantt-row";
    const label = document.createElement("div");
    label.className = "gantt-label";
    if (state.view === "lot") {
      label.innerHTML = `${escapeHtml(row.job_id)}<small>P${row.priority}</small>`;
    } else {
      label.innerHTML = `${escapeHtml(row.equipment_id)}<small>${escapeHtml(statusLabel(row.status))}</small>`;
    }
    const track = document.createElement("div");
    track.className = "track";
    if (state.view === "lot") track.dataset.links = "1";
    if (state.view !== "lot" && row.available_at_min > 0) {
      const shade = document.createElement("div");
      shade.className = row.status === "MAINTENANCE" ? "shade maint" : "shade down";
      shade.style.left = "0";
      shade.style.width = `${(row.available_at_min / scale) * 100}%`;
      track.appendChild(shade);
    }
    for (const bar of row.bars) {
      const node = document.createElement("div");
      const tone = areaTone(bar.area || row.area);
      node.className = "bar" + (bar.moved ? " moved" : "") + (bar.fresh ? " fresh" : "") + (bar.moved && !draw ? " leaving" : "");
      if (state.routeJob === bar.job_id) node.classList.add("selected");
      node.dataset.start = String(bar.start_min);
      node.dataset.end = String(bar.end_min);
      node.style.background = tone.fill;
      node.style.color = tone.ink;
      node.title = bar.job_id;
      const label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = shortLot(bar.job_id);
      node.appendChild(label);
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
  const step = Math.max(60, Math.round(scale / 4 / 60) * 60);
  for (let minute = 0; minute <= scale; minute += step) {
    const tick = document.createElement("span");
    tick.textContent = minute === 0 ? t().now : formatClock(shift(horizon, minute)).slice(11, 16);
    if (minute === 0) tick.className = "now-tick";
    axis.appendChild(tick);
  }
  host.append(wrap, axis);
  wrap.querySelectorAll(".track").forEach((track) => {
    layoutTrack(track, scale);
    if (track.dataset.links === "1") drawLinks(track);
  });
}

function lotRows(gantt) {
  const lots = new Map();
  for (const row of gantt.rows) {
    for (const bar of row.bars) {
      if (!lots.has(bar.job_id)) {
        lots.set(bar.job_id, { job_id: bar.job_id, priority: bar.priority, bars: [] });
      }
      lots.get(bar.job_id).bars.push({ ...bar, equipment_id: row.equipment_id, area: row.area });
    }
  }
  return [...lots.values()].sort((a, b) => a.priority - b.priority || a.job_id.localeCompare(b.job_id));
}

function paintViews() {
  const host = $("#views");
  if (!host) return;
  const copy = t();
  host.setAttribute("aria-label", copy.byTool);
  host.innerHTML = "";
  for (const [id, label] of [["tool", copy.byTool], ["lot", copy.byLot]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-pressed", state.view === id ? "true" : "false");
    button.addEventListener("click", () => {
      state.view = id;
      closeRoute();
      if (state.report) render(state.report);
    });
    host.appendChild(button);
  }
}

function drawLinks(track) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "links");
  const bars = [...track.querySelectorAll(".bar")].sort(
    (a, b) => Number(a.dataset.start) - Number(b.dataset.start),
  );
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
      if (bar.job_id === jobId) {
        steps.push({ ...bar, equipment_id: row.equipment_id, area: row.area });
      }
    }
  }
  steps.sort((a, b) => a.start_min - b.start_min);
  state.routeJob = jobId;
  document.querySelectorAll(".bar").forEach((node) => {
    node.classList.toggle("selected", node.title === jobId);
  });
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
  const width = 280;
  host.style.left = `${Math.min(event.clientX + 12, window.innerWidth - width - 12)}px`;
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
  if (!width || !scale) return;
  const items = [...track.querySelectorAll(".bar")]
    .map((node) => ({
      node,
      start: Number(node.dataset.start),
      end: Number(node.dataset.end),
    }))
    .sort((a, b) => a.start - b.start);
  items.forEach((item) => {
    item.left = (item.start / scale) * width;
    item.raw = ((item.end - item.start) / scale) * width;
  });
  const laneEnds = [];
  items.forEach((item) => {
    let lane = laneEnds.findIndex((end) => item.start >= end);
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(item.end);
    } else {
      laneEnds[lane] = item.end;
    }
    item.lane = lane;
  });
  const laneCount = Math.max(1, laneEnds.length);
  if (laneCount > 1) track.style.height = `${8 + laneCount * 24}px`;
  items.forEach((item) => {
    const later = items.filter((other) => other.lane === item.lane && other.left > item.left + 0.5);
    const nextLeft = later.length ? Math.min(...later.map((other) => other.left)) : width;
    const room = Math.max(0, nextLeft - item.left - 1);
    const floor = Math.min(3, room);
    item.draw = room <= 0 ? 0 : Math.min(Math.max(item.raw, floor), room);
    item.node.style.left = `${item.left}px`;
    item.node.style.width = `${item.draw}px`;
    if (laneCount > 1) {
      item.node.style.top = `${4 + item.lane * 24}px`;
      item.node.classList.add("stacked");
    } else {
      item.node.style.top = "";
      item.node.classList.remove("stacked");
    }
  });
  const lanes = { above: [], below: [] };
  items.forEach((item, index) => {
    const label = item.node.querySelector(".bar-label");
    const text = label ? label.textContent : "";
    const need = textWidth(text);
    item.node.classList.remove("lane-above", "lane-below", "silent");
    if (!text || item.draw >= need || item.node.classList.contains("stacked")) return;
    const labelLeft = item.left;
    const labelRight = item.left + Math.max(0, need - 8);
    const prefer = index % 2 === 0 ? "above" : "below";
    const order = prefer === "above" ? ["above", "below"] : ["below", "above"];
    let lane = "";
    for (const candidate of order) {
      const hit = lanes[candidate].some((span) => labelLeft < span[1] + 2 && labelRight > span[0] - 2);
      if (!hit && labelRight <= width + 1) {
        lane = candidate;
        lanes[candidate].push([labelLeft, labelRight]);
        break;
      }
    }
    if (lane === "above") item.node.classList.add("lane-above");
    else if (lane === "below") item.node.classList.add("lane-below");
    else item.node.classList.add("silent");
  });
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
  textWidth.probe.textContent = text;
  return textWidth.probe.offsetWidth;
}

function renderLegend(report) {
  const copy = t();
  const host = $("#legend");
  host.innerHTML = "";
  const order = ["Lithography", "Etch", "CMP", "Deposition"];
  const seen = new Set();
  for (const side of [report.gantt && report.gantt.before, report.gantt && report.gantt.after]) {
    for (const row of (side && side.rows) || []) {
      if (row.area) seen.add(row.area);
    }
  }
  for (const area of [...order.filter((name) => seen.has(name)), ...[...seen].filter((name) => !order.includes(name))]) {
    const tone = areaTone(area);
    host.appendChild(legendItem(tone.fill, (copy.areas && copy.areas[area]) || area, tone.ink));
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
  if (kind === "x") return Number(value).toFixed(digits);
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

window.addEventListener("resize", () => {
  document.querySelectorAll(".gantt").forEach((wrap) => {
    const scale = Number(wrap.dataset.scale || 0);
    wrap.querySelectorAll(".track").forEach((track) => {
      layoutTrack(track, scale);
      track.querySelectorAll(".links").forEach((node) => node.remove());
      if (track.dataset.links === "1") drawLinks(track);
    });
  });
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
