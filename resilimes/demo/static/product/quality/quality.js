// Quality page: the metrics and checks panels.
// Loaded after the run console so it can call the shared helpers.

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
    appendRecoveryNotes(host, report, copy);
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
  const lang = state.lang || "ja";
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
  appendRecoveryNotes(host, report, copy);
}

function appendRecoveryNotes(host, report, copy) {
  const safety = safetyCard(report, copy);
  if (safety) host.appendChild(safety);
  const rounds = roundsCard(report, copy);
  if (rounds) host.appendChild(rounds);
  if (report.review_panel) host.appendChild(reviewCard(report.review_panel, copy));
}

function safetyCard(report, copy) {
  const alt = report.rejected_alternative;
  if (!alt || alt.label !== "safety test") return null;
  const card = document.createElement("article");
  card.className = "card";
  const intent = copy.intent || {};
  card.appendChild(cardHead(intent.safety || alt.label, intent.safetyNote || ""));
  return card;
}

function roundsCard(report, copy) {
  const rounds = report.propose_loop && report.propose_loop.rounds;
  if (!Array.isArray(rounds) || !rounds.length) return null;
  const card = document.createElement("article");
  card.className = "card";
  const intent = copy.intent || {};
  card.appendChild(cardHead(intent.rounds || "", ""));
  const list = document.createElement("ol");
  for (const round of rounds) {
    const item = document.createElement("li");
    item.textContent = typeof round === "string" ? round : JSON.stringify(round);
    list.appendChild(item);
  }
  card.appendChild(list);
  return card;
}

function reviewCard(panel, copy) {
  const card = document.createElement("article");
  card.className = "card";
  card.appendChild(reviewBlock(panel, copy));
  return card;
}

function paintIntent() {
  const host = $("#intent");
  if (!host) return;
  const copy = t();
  const intent = copy.intent || {};
  const view = state.intent || {};
  host.innerHTML = "";
  if (!view.propose && !view.result) {
    host.appendChild(emptyLine(copy.working));
    return;
  }
  const propose = view.propose || {};
  const result = view.result;
  const status = (result && result.status) || propose.status || "";
  const row = document.createElement("p");
  row.className = "status-row";
  const pill = document.createElement("span");
  pill.className = `pill ${status === "executed" ? "accept" : status === "rejected" || status === "aborted" ? "failed" : "conditional"}`;
  pill.textContent = (intent.status && intent.status[status]) || status;
  row.appendChild(pill);
  host.appendChild(row);
  if (view.httpError) host.appendChild(paragraph(view.httpError));
  const source = (result && result.feedback && result.feedback.source) || (result && result.source) || propose.source;
  if (source === "deterministic-fallback") host.appendChild(fallbackBanner(intent.fallback));
  const errors = (result && result.errors) || propose.errors || [];
  if (errors.length) {
    const list = document.createElement("ul");
    for (const item of errors) {
      const li = document.createElement("li");
      li.textContent = localizeServer(String(item), intent);
      list.appendChild(li);
    }
    host.appendChild(list);
  }
  const contract = propose.contract;
  if (contract) {
    const signed = document.createElement("p");
    signed.textContent = `${intent.signature} · ${copy.verified} · ${contract.signaturePrefix || ""}`;
    host.appendChild(signed);
  } else if (propose.status === "rejected" && propose.call) {
    host.appendChild(paragraph(intent.noContract));
  }
  const request = propose.meterless_request_id || (result && result.meterless_request_id);
  if (request) host.appendChild(paragraph(fill(copy.requestId, { id: request })));
  const call = (result && result.call) || propose.call;
  if (call) host.appendChild(callBlock(call, intent));
  if (result) host.appendChild(resultBlock(result, intent, copy));
  if (propose.status === "pending_confirmation" && !result) {
    const actions = document.createElement("div");
    actions.className = "actions";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "run";
    confirm.id = "intent-confirm";
    confirm.textContent = intent.confirm;
    confirm.disabled = state.running;
    confirm.addEventListener("click", confirmIntent);
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "run quiet";
    cancel.id = "intent-cancel";
    cancel.textContent = intent.cancel;
    cancel.disabled = state.running;
    cancel.addEventListener("click", () => {
      state.intent = null;
      paint();
    });
    actions.append(confirm, cancel);
    host.appendChild(actions);
  }
}

function paragraph(text) {
  const node = document.createElement("p");
  node.textContent = text || "";
  return node;
}

function fallbackBanner(text) {
  const node = document.createElement("p");
  node.className = "fallback";
  node.textContent = text || "";
  return node;
}

function callBlock(call, intent) {
  const wrap = document.createElement("div");
  const title = document.createElement("h2");
  const name = (intent.names && intent.names[call.intent]) || call.intent;
  title.textContent = `${intent.call} · ${name}`;
  wrap.appendChild(title);
  const list = document.createElement("dl");
  const params = call.parameters || {};
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "") continue;
    const dt = document.createElement("dt");
    dt.textContent = (intent.params && intent.params[key]) || key;
    const dd = document.createElement("dd");
    dd.textContent = paramValue(key, value, intent);
    list.append(dt, dd);
  }
  const rules = call.validation_rules || {};
  const stock = document.createElement("dt");
  stock.textContent = intent.checkInventory;
  const stockValue = document.createElement("dd");
  stockValue.textContent = rules.check_inventory ? intent.yes : intent.no;
  list.append(stock, stockValue);
  if (rules.notify_pe) {
    const who = document.createElement("dt");
    who.textContent = intent.notifyPe;
    const whom = document.createElement("dd");
    whom.textContent = rules.notify_pe;
    list.append(who, whom);
  }
  wrap.appendChild(list);
  return wrap;
}

function paramValue(key, value, intent) {
  if (typeof value === "boolean") return value ? intent.yes : intent.no;
  if (String(key).endsWith("_min") && Number.isFinite(Number(value))) return formatDuration(Number(value));
  return String(value);
}

function resultBlock(result, intent, copy) {
  const wrap = document.createElement("div");
  const outcome = document.createElement("p");
  outcome.textContent = result.status === "aborted"
    ? intent.notWritten
    : result.committed
      ? intent.committed
      : intent.simulated;
  wrap.appendChild(outcome);
  if (result.fix_hint) wrap.appendChild(paragraph(localizeServer(String(result.fix_hint), intent)));
  const trace = (result.trace || []).filter((item) => item && item.type === "notify_pe");
  for (const item of trace) {
    const note = document.createElement("p");
    note.textContent = fill(intent.notify, { name: item.to || "" });
    wrap.appendChild(note);
  }
  const feedback = result.feedback || {};
  if (feedback.narrative_degraded) wrap.appendChild(fallbackBanner(intent.degraded));
  const kpis = result.kpis || {};
  if (kpis.before && kpis.after) {
    const line = document.createElement("p");
    line.textContent = `${copy.kpiOtd} ${Number(kpis.before.on_time_delivery_pct).toFixed(1)}% → ${Number(kpis.after.on_time_delivery_pct).toFixed(1)}% · ${copy.kpiTardy} ${formatDuration(kpis.before.weighted_tardiness_min)} → ${formatDuration(kpis.after.weighted_tardiness_min)}`;
    wrap.appendChild(line);
  }
  const lots = (result.affected_lots || []).map((item) => item.lot_id).filter(Boolean);
  wrap.appendChild(paragraph(`${intent.affected} · ${lots.length ? lots.join(", ") : intent.none}`));
  if (result.review_panel) wrap.appendChild(reviewBlock(result.review_panel, copy));
  if (result.book && window.Fab && copy.fab) {
    const open = document.createElement("button");
    open.type = "button";
    open.className = "fab-open";
    open.textContent = copy.fab.whatifOpen;
    open.addEventListener("click", () => window.Fab.openBook(result.book));
    wrap.appendChild(open);
  }
  return wrap;
}

function reviewBlock(panel, copy) {
  const intent = copy.intent || {};
  const wrap = document.createElement("div");
  if (panel.source === "deterministic-fallback") wrap.appendChild(fallbackBanner(intent.fallback));
  const agree = document.createElement("p");
  const agreement = (intent.agreement && intent.agreement[panel.agreement]) || panel.agreement || "";
  const recommendation = (intent.review && intent.review[panel.recommendation]) || panel.recommendation || "";
  agree.textContent = `${agreement} · ${recommendation}`;
  wrap.appendChild(agree);
  wrap.appendChild(paragraph(intent.suggestions));
  for (const reviewer of panel.reviewers || []) {
    const block = document.createElement("section");
    block.className = "reviewer";
    const title = document.createElement("h3");
    const role = (intent.roles && intent.roles[reviewer.role]) || reviewer.role;
    const verdict = (intent.review && intent.review[reviewer.verdict]) || reviewer.verdict;
    title.textContent = `${role} · ${verdict}`;
    block.appendChild(title);
    if (reviewer.source === "deterministic-fallback") block.appendChild(fallbackBanner(intent.fallback));
    if (reviewer.meterless_request_id) block.appendChild(paragraph(fill(copy.requestId, { id: reviewer.meterless_request_id })));
    for (const concern of reviewer.concerns || []) {
      block.appendChild(paragraph(localizeConcern(concern, intent)));
    }
    for (const suggestion of reviewer.suggestions || []) {
      block.appendChild(paragraph(localizeSuggestion(suggestion, intent)));
    }
    if (reviewer.hallucinated_ids && reviewer.hallucinated_ids.length) {
      block.appendChild(paragraph(reviewer.hallucinated_ids.join(", ")));
    }
    wrap.appendChild(block);
  }
  return wrap;
}

function localizeConcern(concern, intent) {
  const detail = String((concern && concern.detail) || "");
  const down = detail.match(/^(.+) is down or in maintenance\.$/);
  if (down) return fill(intent.concernDown, { id: down[1] });
  const held = detail.match(/^(.+) is held\.$/);
  if (held) return fill(intent.concernHeld, { id: held[1] });
  return detail;
}

function localizeSuggestion(text, intent) {
  const match = String(text || "").match(/^Review the hold on (.+) before publishing the book\.$/);
  if (match) return fill(intent.suggestHold, { id: match[1] });
  return String(text || "");
}

function localizeServer(text, intent) {
  const lot = text.match(/^Unknown lot (.+)\.$/);
  if (lot) return fill(intent.unknownLot, { id: lot[1] });
  const tool = text.match(/^Unknown equipment (.+)\.$/);
  if (tool) return fill(intent.unknownTool, { id: tool[1] });
  if (text === "Prompt injection detected.") return intent.injection;
  const hold = text.match(/^Cannot hold ([^:]+): it is running on ([^.]+)\.$/);
  if (hold) return fill(intent.runningHold, { lot: hold[1], tool: hold[2] });
  if (text === "Leave the running lot in place and reschedule queued work.") return intent.leaveRunning;
  return text;
}

async function submitIntent(text) {
  if (state.running) return;
  state.running = true;
  state.report = null;
  state.tab = "recover";
  state.intent = { propose: null, result: null };
  closeRoute();
  paint();
  try {
    const response = await fetch("/api/intents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ incident: text, actor_role: "planner" }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    state.intent = { propose: payload, result: null };
  } catch (error) {
    state.intent = { propose: { status: "rejected", contract: null, errors: [error.message] }, result: null };
  } finally {
    state.running = false;
    paint();
  }
}

async function confirmIntent() {
  const propose = state.intent && state.intent.propose;
  if (!propose || !propose.confirmation_id || state.running) return;
  state.running = true;
  paint();
  try {
    const response = await fetch("/api/intents/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_id: propose.confirmation_id }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      state.intent = { propose, result: null, httpError: payload.detail || `Request failed (${response.status})` };
    } else {
      state.intent = { propose, result: payload };
    }
  } catch (error) {
    state.intent = { propose, result: null, httpError: error.message };
  } finally {
    state.running = false;
    paint();
  }
}

function checkReasons(report, row, copy) {
  const reasons = (row.violations || []).map((item) => formatFinding(item)).filter(Boolean);
  const rejected = report.rejected_alternative && report.rejected_alternative.critique;
  for (const item of (rejected && rejected.violations) || []) {
    if (item.constraint !== row.constraint && item.constraint !== row.id) continue;
    const line = formatFinding(item);
    if (line && !reasons.includes(line)) {
      const label = report.rejected_alternative && report.rejected_alternative.label === "safety test"
        ? (copy.intent && copy.intent.safety) || copy.refusedPlan
        : copy.refusedPlan;
      reasons.push(`${label}: ${line}`);
    }
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

