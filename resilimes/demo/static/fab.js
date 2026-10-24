/* Fab views for the full SMT2020 run: overview, tools, product flow, lots,
   furnace batches, event log and daily KPIs. Every number comes from the
   read-only /api/fab/* endpoints, which replay the recorded 48 h simulation.
   State colours keep Schedule_Viewer's hue mapping (processing blue, waiting amber, setup orange,
   PM grey, idle light grey, down red), retuned to IBM Carbon shades (see DESIGN.md). */
(() => {
  "use strict";

  const HORIZON = 172800;
  const TABS = ["overview", "tools", "flow", "lots", "batches", "events", "kpis"];
  const BOOKS = ["base", "litho_down", "hot_lot", "pm_avoid"];
  const STATE_COLOR = {
    run: "#4589ff",
    setup: "#ff832b",
    idle: "#e0e0e0",
    pm: "#6f6f6f",
    down: "#da1e28",
    batch_wait: "#f1c21b",
    wait: "#f1c21b",
  };
  const CLASS_COLOR = { VIP: "#8a3ffc", hot: "#d02670", normal: "#8d8d8d" };
  const RISK_COLOR = { late: "#da1e28", risk: "#b28600", ok: "transparent" };
  const DONE_COLOR = "#24a148";
  const STATUS = ["wait", "run", "hold", "done"];

  const S = {
    tab: "overview",
    book: "base",
    whatif: null,
    t: 86400,
    playing: false,
    speed: 900,
    timer: null,
    meta: null,
    group: null,
    family: null,
    lot: null,
    recentLots: [],
    kinds: ["down", "pm", "batch", "priority", "rework", "reclean", "qtime_miss", "done"],
    query: "",
    token: 0,
    busy: false,
    cache: new Map(),
  };

  // ---------- helpers ----------
  const C = () => (t().fab || COPY.en.fab);
  function fill(template, values) {
    return String(template || "").replace(/\{(\w+)\}/g, (_m, key) =>
      values && values[key] !== undefined && values[key] !== null ? values[key] : "");
  }
  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "style") node.setAttribute("style", value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.appendChild(typeof kid === "string" || typeof kid === "number" ? document.createTextNode(String(kid)) : kid);
    }
    return node;
  }
  const NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, ...kids) {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined) continue;
      if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    }
    for (const kid of kids.flat()) if (kid) node.appendChild(kid);
    return node;
  }
  function clock(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    const s = Math.max(0, Math.round(seconds));
    const day = Math.floor(s / 86400) + 1;
    const hh = String(Math.floor((s % 86400) / 3600)).padStart(2, "0");
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    return fill(C().clock, { d: day, hm: `${hh}:${mm}` });
  }
  function hm(seconds) {
    const s = Math.max(0, Math.round(seconds));
    const hh = String(Math.floor((s % 86400) / 3600)).padStart(2, "0");
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const day = Math.floor(s / 86400) + 1;
    return day === Math.floor(S.t / 86400) + 1 ? `${hh}:${mm}` : `${fill(C().dayShort, { d: day })} ${hh}:${mm}`;
  }
  function dur(minutes) {
    const m = Math.round(Math.abs(minutes));
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  }
  const pct = (v, digits = 0) => `${(v * 100).toFixed(digits)}%`;
  const kindLabel = (kind) => (C().classes[kind] || kind);

  function reasonText(r) {
    const c = C().reason;
    switch (r.code) {
      case "vip": return c.vip;
      case "hot": return c.hot;
      case "late": return fill(c.late, { h: r.h });
      case "qtime": return r.min < 0 ? fill(c.qtimeOver, { min: -r.min }) : fill(c.qtime, { min: r.min });
      case "rework": return c.rework;
      case "batch": return fill(c.batch, r);
      case "same_recipe": return c.same_recipe;
      case "setup": return fill(c.setup, { min: Math.round(r.min) });
      case "slack": return fill(c.slack, { h: r.h });
      case "pm_skip": return fill(c.pm_skip, { at: hm(r.at) });
      default: return r.code;
    }
  }
  function reasonTone(r) {
    if (r.code === "vip" || r.code === "hot") return "prio";
    if (r.code === "late" || (r.code === "qtime" && r.min < 30)) return "bad";
    if (r.code === "qtime" || r.code === "pm_skip" || r.code === "rework") return "warn";
    if (r.code === "same_recipe") return "good";
    return "";
  }
  function reasonChips(reasons, max = 3) {
    return el("span", { class: "fx-reasons" },
      (reasons || []).slice(0, max).map((r) => el("span", { class: `fx-reason ${reasonTone(r)}`, text: reasonText(r) })));
  }
  function lotLink(name, kind) {
    return el("button", {
      type: "button",
      class: `fx-lot ${kind || ""}`,
      title: name,
      onclick: (event) => { event.stopPropagation(); openLot(name); },
    }, el("i", { class: "fx-dot", style: `background:${CLASS_COLOR[kind] || CLASS_COLOR.normal}` }), name);
  }
  function statePill(state) {
    return el("span", { class: `fx-pill st-${state}`, text: C().states[state] || state });
  }
  function riskPill(risk) {
    return el("span", { class: `fx-pill rk-${risk}`, text: C().risk[risk] || risk });
  }
  function card(title, note, ...body) {
    return el("section", { class: "fx-card" },
      el("header", {}, el("h3", { text: title }), note ? el("span", { class: "fx-note", text: note }) : null),
      ...body);
  }
  function bar(value, max, color, label) {
    const share = max > 0 ? Math.min(1, value / max) : 0;
    return el("span", { class: "fx-bar", title: label || "" },
      el("i", { style: `width:${(share * 100).toFixed(1)}%;background:${color}` }));
  }
  function empty(text) { return el("p", { class: "fx-empty", text }); }

  // ---------- data ----------
  function bookKey() { return S.book === "whatif" && S.whatif ? S.whatif : S.book; }
  async function api(path, params) {
    const query = new URLSearchParams({ book: bookKey(), ...(params || {}) });
    const url = `/api/fab/${path}?${query}`;
    if (S.cache.has(url)) return S.cache.get(url);
    const response = await fetch(url);
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).detail || detail; } catch (_e) { /* keep status */ }
      throw new Error(`${response.status} ${detail}`);
    }
    const body = await response.json();
    if (S.cache.size > 80) S.cache.delete(S.cache.keys().next().value);
    S.cache.set(url, body);
    return body;
  }
  async function loadMeta() {
    const key = bookKey();
    if (S.meta && S.meta.book === key) return S.meta;
    S.meta = await api("meta", {});
    return S.meta;
  }

  // ---------- frame ----------
  function host() { return document.getElementById("panel-fab"); }

  function toolbar() {
    const c = C();
    const select = el("select", {
      id: "fx-book",
      "aria-label": c.book,
      onchange: (event) => { S.book = event.target.value; S.meta = null; render(); },
    });
    const ready = new Map(((S.meta && S.meta.books) || []).map((b) => [b.key, b.ready]));
    for (const key of BOOKS) {
      select.appendChild(el("option", { value: key, selected: S.book === key }, c.books[key] + (ready.get(key) === false ? " ·" : "")));
    }
    if (S.whatif) select.appendChild(el("option", { value: "whatif", selected: S.book === "whatif" }, c.books.whatif));
    const range = el("input", {
      id: "fx-time",
      type: "range",
      min: 0,
      max: HORIZON,
      step: 900,
      value: S.t,
      "aria-label": c.time,
      oninput: (event) => { S.t = Number(event.target.value); label.textContent = clock(S.t); },
      onchange: () => render(),
    });
    const label = el("output", { class: "fx-clock", id: "fx-clock", text: clock(S.t) });
    const play = el("button", { type: "button", class: "fx-btn", id: "fx-play", onclick: togglePlay }, S.playing ? c.pause : c.play);
    const speed = el("select", {
      "aria-label": "speed",
      onchange: (event) => { S.speed = Number(event.target.value); },
    },
    el("option", { value: 900, selected: S.speed === 900 }, c.speed.slow),
    el("option", { value: 3600, selected: S.speed === 3600 }, c.speed.fast));
    const step = (delta) => () => { S.t = Math.max(0, Math.min(HORIZON, S.t + delta)); render(); };
    const meta = S.meta;
    return el("div", { class: "fx-toolbar" },
      el("div", { class: "fx-source" },
        el("strong", { text: c.source }),
        meta ? el("span", { text: fill(c.sourceLine, { lots: meta.lots, tools: meta.tools, families: meta.families.length, routes: meta.routes.length, seed: meta.seed }) }) : null),
      el("label", { class: "fx-field" }, el("span", { text: c.book }), select),
      el("div", { class: "fx-time" },
        el("button", { type: "button", class: "fx-btn ghost", onclick: step(-3600) }, c.back),
        play,
        el("button", { type: "button", class: "fx-btn ghost", onclick: step(3600) }, c.fwd),
        range, label, speed));
  }

  function togglePlay() {
    S.playing = !S.playing;
    clearInterval(S.timer);
    if (S.playing) {
      if (S.t >= HORIZON) S.t = 0;
      S.timer = setInterval(async () => {
        if (S.busy) return;
        if (S.t >= HORIZON || !document.getElementById("panel-fab") || host().hidden) {
          S.playing = false;
          clearInterval(S.timer);
          render();
          return;
        }
        S.t = Math.min(HORIZON, S.t + S.speed);
        await render(true);
      }, 800);
    }
    render();
  }

  async function render(quiet) {
    const root = host();
    if (!root) return;
    const token = ++S.token;
    S.busy = true;
    try {
      if (!quiet && !root.querySelector(".fx-body")) root.replaceChildren(el("p", { class: "fx-empty", text: C().loading }));
      await loadMeta();
      const body = await VIEWS[S.tab]();
      if (token !== S.token) return;
      root.replaceChildren(toolbar(), el("div", { class: `fx-body fx-${S.tab}` }, body));
    } catch (error) {
      if (token !== S.token) return;
      const note = el("p", { class: "fx-error", text: fill(C().error, { msg: error.message }) });
      root.replaceChildren(S.meta ? toolbar() : el("div"), note);
    } finally {
      if (token === S.token) S.busy = false;
    }
  }

  function goto(tab, patch) {
    Object.assign(S, patch || {});
    if (typeof state !== "undefined") {
      state.tab = `fab-${tab}`;
      if (typeof paintTabs === "function") { paintTabs(); return; }
    }
    S.tab = tab;
    render();
  }
  function openLot(name) {
    S.recentLots = [name, ...S.recentLots.filter((x) => x !== name)].slice(0, 8);
    goto("lots", { lot: name });
  }
  function openFamily(family, group) { goto("tools", { family, group: group || S.group }); }

  // ---------- overview ----------
  async function viewOverview() {
    const c = C();
    const o = await api("overview", { t: S.t });
    const tiles = el("div", { class: "fx-tiles" },
      tile(c.ov.kWip, o.lots.wait + o.lots.run + o.lots.hold, fill(c.ov.kWipSub, o.lots)),
      tile(c.ov.kDone, o.lots.done, fill(c.ov.kDoneSub, { ontime: o.due_so_far.on_time, due: o.due_so_far.due })),
      tile(c.ov.kTools, o.tools.run || 0, fill(c.ov.kToolsSub, { idle: o.tools.idle || 0, down: o.tools.down || 0, setup: o.tools.setup || 0 })),
      tile(c.ov.kOtd, `${o.counters.on_time_pct}%`, `${fill(c.ov.kOtdSub, { n: o.counters.due_in_horizon })} · ${c.ov.wholeRun}`),
      tile(c.ov.kPrio, o.priority.filter((row) => row.risk === "late").length,
        fill(c.ov.kPrioSub, { n: o.priority.length }), o.priority.some((row) => row.risk === "late") ? "bad" : ""));
    const toolBar = stacked(o.tools, ["run", "setup", "batch_wait", "idle", "pm", "down"], c.states);
    const lotBar = stacked(o.lots, ["run", "wait", "hold", "done"], c.status,
      { run: STATE_COLOR.run, wait: STATE_COLOR.wait, hold: STATE_COLOR.down, done: DONE_COLOR });
    const states = card(c.ov.toolStates, null, toolBar, el("h4", { text: c.ov.lotStates }), lotBar);

    const maxQ = Math.max(1, ...o.bottlenecks.map((b) => b.queue));
    const bn = card(c.ov.bottlenecks, o.bottlenecks.some((b) => b.bottleneck) ? c.ov.bottlenecksNote : c.ov.busiest,
      el("div", { class: "fx-rows" }, o.bottlenecks.slice(0, 6).map((b) => familyRow(b, maxQ))));
    const alerts = card(c.ov.alerts, fill(c.ov.alertsNote, { n: o.alerts_total }),
      o.alerts.length ? el("ul", { class: "fx-alerts" }, o.alerts.slice(0, 8).map((b) => alertRow(b)))
        : empty(c.ov.allClear));
    const prio = card(c.ov.priority, null, lotTable(o.priority.slice(0, 10)));
    const risk = card(c.ov.atRisk, fill(c.ov.atRiskNote, { n: o.at_risk_total }), lotTable(o.at_risk.slice(0, 8)));
    const recent = card(c.ov.recent, null, eventList(o.recent));
    return [tiles, el("div", { class: "fx-grid three" }, bn, alerts, states), el("div", { class: "fx-grid three" }, prio, risk, recent)];
  }
  function tile(label, value, sub, tone) {
    return el("div", { class: `fx-tile ${tone || ""}` },
      el("span", { class: "fx-tile-label", text: label }),
      el("strong", { text: String(value) }),
      el("span", { class: "fx-tile-sub", text: sub }));
  }
  function stacked(counts, keys, labels, colors) {
    const total = keys.reduce((sum, key) => sum + (counts[key] || 0), 0) || 1;
    return el("div", { class: "fx-stack-wrap" },
      el("div", { class: "fx-stack" }, keys.filter((k) => counts[k]).map((key) =>
        el("i", { title: `${labels[key]} ${counts[key]}`, style: `flex:${counts[key]};background:${(colors || STATE_COLOR)[key]}` }))),
      el("div", { class: "fx-legend" }, keys.filter((k) => counts[k]).map((key) =>
        el("span", {}, el("i", { style: `background:${(colors || STATE_COLOR)[key]}` }), `${labels[key]} ${counts[key]}`,
          el("small", { text: ` ${Math.round((counts[key] / total) * 100)}%` })))));
  }
  function familyRow(b, maxQ) {
    const c = C();
    const trend = b.trend > 0 ? fill(c.ov.trendUp, { n: b.trend }) : b.trend < 0 ? fill(c.ov.trendDown, { n: -b.trend }) : c.ov.trendFlat;
    return el("button", { type: "button", class: `fx-fam ${b.pileup ? "pile" : ""}`, onclick: () => openFamily(b.family, b.group) },
      el("span", { class: "fx-fam-name" }, el("strong", { text: b.family }), el("small", { text: `${b.group} · ${fill(c.tl.tools, { n: b.tools })}` })),
      el("span", { class: "fx-fam-metric" }, el("small", { text: `${c.ov.util} ${pct(b.util)}` }), bar(b.util, 1, b.util >= 0.85 ? "var(--alarm)" : "var(--accent)")),
      el("span", { class: "fx-fam-metric" }, el("small", { text: `${c.ov.queue} ${b.queue} · ${fill(c.ov.limit, { n: b.threshold })}` }),
        bar(b.queue, maxQ, b.queue > b.threshold ? "var(--amber-mark)" : "var(--accent)")),
      el("span", { class: `fx-trend ${b.trend > 0 ? "up" : ""}`, text: trend }));
  }
  function alertRow(b) {
    const c = C();
    const trend = b.trend > 0 ? fill(c.ov.trendUp, { n: b.trend }) : b.trend < 0 ? fill(c.ov.trendDown, { n: -b.trend }) : c.ov.trendFlat;
    const over = b.threshold ? b.queue / b.threshold : 1;
    return el("li", { class: over >= 3 ? "hi" : "" },
      el("button", { type: "button", class: "fx-link strong", onclick: () => openFamily(b.family, b.group), text: b.family }),
      el("small", { class: "muted", text: b.group }),
      el("span", { class: "fx-alert-line", text: `${fill(c.tl.lotsWaiting, { n: b.queue })} · ${fill(c.ov.limit, { n: b.threshold })}` }),
      el("span", { class: `fx-trend ${b.trend > 0 ? "up" : ""}`, text: trend }));
  }
  function lotTable(rows) {
    const c = C();
    if (!rows.length) return empty(c.none);
    return el("table", { class: "fx-table" },
      el("tbody", {}, rows.map((row) => el("tr", {},
        el("td", {}, lotLink(row.lot, row.kind)),
        el("td", { class: "muted", text: `${row.step + 1}/${row.steps}` }),
        el("td", {}, el("span", { class: `fx-status s-${row.status}`, text: c.status[row.status] || row.status })),
        el("td", { class: "num", text: row.slack_h === null ? "" : `${row.slack_h} h` }),
        el("td", {}, row.risk ? riskPill(row.risk) : null)))));
  }

  // ---------- events ----------
  function eventText(e) {
    const c = C().ev;
    switch (e.kind) {
      case "down":
        if (e.forced) return fill(c.downForced, { tool: e.tool, until: hm(e.until) });
        return e.lots && e.lots.length ? fill(c.downLots, { tool: e.tool, until: hm(e.until), n: e.lots.length }) : fill(c.down, { tool: e.tool, until: hm(e.until) });
      case "pm": return fill(c.pm, { tool: e.tool, until: hm(e.until) });
      case "batch": return fill(c.batch, { tool: e.tool, n: e.lots.length, wafers: e.wafers, why: C().why[e.why] || e.why });
      case "priority": return fill(c.priority, { cls: kindLabel(e.class), lot: e.lot, step: e.step + 1, tool: e.tool });
      case "rework": return e.redo_tool
        ? fill(c.reworkRedo, { lot: e.lot, step: e.step + 1, tool: e.tool, redo: e.redo_tool, at: hm(e.redo_at) })
        : fill(c.rework, { lot: e.lot, step: e.step + 1, tool: e.tool });
      case "reclean": return fill(c.reclean, { lot: e.lot, origin: e.origin + 1 });
      case "qtime_miss": return fill(c.qtime_miss, { lot: e.lot, step: e.step + 1, over: e.over_min });
      case "done": return e.on_time ? fill(c.doneOk, { lot: e.lot }) : fill(c.doneLate, { lot: e.lot, h: e.late_h });
      case "skip": return fill(c.skip, { lot: e.lot, step: e.step + 1 });
      default: return e.kind;
    }
  }
  function eventList(events) {
    if (!events || !events.length) return empty(C().none);
    return el("ol", { class: "fx-events" }, events.map((e) => el("li", { class: `ev-${e.kind}${e.kind === "done" && !e.on_time ? " late" : ""}` },
      el("time", { text: hm(e.t) }),
      el("i", { class: "fx-ev-mark" }),
      el("span", { class: "fx-ev-text", text: eventText(e) }),
      e.lot ? el("button", { type: "button", class: "fx-link", onclick: () => openLot(e.lot), text: "→" }) : null)));
  }
  async function viewEvents() {
    const c = C();
    const data = await api("events", { t0: 0, t1: S.t, kind: S.kinds.join(","), q: S.query, limit: 200 });
    if (!S.kinds.length) data.events = [];
    const chips = el("div", { class: "fx-chips" }, Object.keys(c.ev.kinds).map((kind) => el("button", {
      type: "button",
      class: `fx-chip ev-${kind}`,
      "aria-pressed": S.kinds.includes(kind) ? "true" : "false",
      onclick: () => {
        S.kinds = S.kinds.includes(kind) ? S.kinds.filter((k) => k !== kind) : [...S.kinds, kind];
        render();
      },
    }, el("i", { class: "fx-ev-mark" }), `${c.ev.kinds[kind]} ${data.by_kind[kind] || 0}`)));
    const search = el("input", {
      type: "search",
      class: "fx-search",
      placeholder: c.ev.search,
      value: S.query,
      onchange: (event) => { S.query = event.target.value.trim(); render(); },
    });
    const bds = data.breakdowns.filter((b) => b.start <= S.t);
    const list = card(fill(c.ev.count, { n: data.total, t: clock(S.t) }), null, eventList(data.events));
    const bdCard = card(c.ev.breakdowns, String(bds.length), bds.length ? el("div", { class: "fx-bd-list" }, bds.map((b) => el("div", { class: "fx-bd" },
      el("div", { class: "fx-bd-head" }, statePill("down"), el("strong", { text: b.tool }), el("small", { text: `${b.family} · ${b.group}` })),
      el("div", { class: "fx-bd-time", text: `${hm(b.start)} → ${b.open_end ? c.ev.bdOpen : hm(b.end)} · ${fill(c.ev.bdDur, { min: Math.round((b.end - b.start) / 60) })}` }),
      b.lots.length ? el("div", { class: "fx-bd-lots" }, el("small", { text: fill(c.ev.bdLots, { lots: "" }) }), b.lots.slice(0, 6).map((l) => lotLink(l.lot, l.kind))) : null)))
      : empty(c.none));
    return [el("div", { class: "fx-filterbar" }, chips, search), el("div", { class: "fx-grid two-one" }, list, bdCard)];
  }

  // ---------- tools ----------
  async function viewTools() {
    const c = C();
    const params = { t: S.t };
    if (S.family) params.family = S.family;
    else if (S.group) params.group = S.group;
    const data = await api("tools", params);
    const groups = (await api("tools", { t: S.t })).groups || data.groups || [];
    const chips = el("div", { class: "fx-chips" },
      el("button", { type: "button", class: "fx-chip", "aria-pressed": !S.group && !S.family ? "true" : "false", onclick: () => { S.group = null; S.family = null; render(); } }, C().ov.busiest),
      groups.map((g) => el("button", {
        type: "button",
        class: `fx-chip ${g.pileups ? "warn" : ""}`,
        "aria-pressed": S.group === g.group ? "true" : "false",
        onclick: () => { S.group = g.group; S.family = null; render(); },
      }, g.group, el("small", { text: ` ${g.queue}${g.pileups ? ` · ${g.pileups}▲` : ""}` }))));
    const fams = data.families || [];
    let select = null;
    if (S.group) {
      const names = (S.meta.families || []).filter((f) => f.group === S.group).map((f) => f.name);
      select = el("label", { class: "fx-field" }, el("span", { text: c.tl.pickFamily }), el("select", {
        onchange: (event) => { S.family = event.target.value || null; render(); },
      }, el("option", { value: "" }, c.tl.allFamilies), names.map((n) => el("option", { value: n, selected: S.family === n }, n))));
    }
    const legend = el("div", { class: "fx-legend" }, ["run", "setup", "batch_wait", "idle", "pm", "down"].map((k) =>
      el("span", {}, el("i", { style: `background:${STATE_COLOR[k]}` }), c.states[k])));
    const list = fams.length ? fams.map((f) => familyCard(f, data.window)) : [empty(c.none)];
    return [el("div", { class: "fx-filterbar" }, chips, select), legend, ...list];
  }
  function familyCard(f, window) {
    const c = C();
    const head = el("header", { class: "fx-famhead" },
      el("div", {},
        el("h3", { text: f.family }),
        el("small", { text: `${f.group} · ${fill(c.tl.tools, { n: f.tools.length })}` })),
      f.batch ? el("span", { class: "fx-badge", text: c.tl.batchTool }) : null,
      f.util >= 0.85 && f.queue > f.threshold ? el("span", { class: "fx-badge bad", text: c.tl.bottleneck }) : null,
      f.pileup ? el("span", { class: "fx-badge warn", text: c.tl.pileup }) : null,
      el("span", { class: "fx-fam-metric wide" }, el("small", { text: `${c.ov.util} ${pct(f.util)}` }), bar(f.util, 1, f.util >= 0.85 ? "var(--alarm)" : "var(--accent)")),
      el("span", { class: "fx-fam-metric wide" }, el("small", { text: `${c.ov.queue} ${f.queue} · ${fill(c.ov.limit, { n: f.threshold })}` }),
        bar(f.queue, Math.max(f.queue, f.threshold * 2), f.queue > f.threshold ? "var(--amber-mark)" : "var(--accent)")));
    const rows = el("div", { class: "fx-toolrows" },
      el("div", { class: "fx-toolrow head" },
        el("span", { text: C().lot.colTool }), el("span", { text: c.tl.onTool }), el("span", { text: c.tl.timeline }), el("span", { text: c.tl.next })),
      f.tools.map((tool) => toolRow(tool, window)));
    const queue = el("div", { class: "fx-queue" },
      el("h4", {}, c.tl.queueTitle, el("small", { text: ` ${fill(c.tl.queueNote, { n: f.queue, limit: f.threshold })}` })),
      f.queue_top.length ? el("ol", {}, f.queue_top.slice(0, 8).map((q) => el("li", {},
        lotLink(q.lot, q.kind),
        el("small", { class: "muted", text: `${fill(c.tl.step, { n: q.step + 1 })} · ${fill(c.tl.waited, { min: dur(q.wait_min) })}` }),
        reasonChips(q.reasons, 3),
        q.pm_blocked ? el("span", { class: "fx-reason warn", text: fill(c.reason.pm_blocked, { tools: q.pm_blocked.join(", ") }) }) : null)))
        : empty(c.none),
      f.queue > 8 ? el("small", { class: "muted", text: fill(c.more, { n: f.queue - 8 }) }) : null);
    return el("section", { class: `fx-card fx-family ${f.pileup ? "pile" : ""}` }, head, el("div", { class: "fx-family-body" }, rows, queue));
  }
  function toolRow(tool, window) {
    const c = C();
    const lots = tool.lots || [];
    let now;
    if (tool.state === "run" || tool.state === "setup") {
      now = el("div", { class: "fx-now" },
        el("div", { class: "fx-now-lots" }, lots.slice(0, 2).map((l) => lotLink(l.lot, l.kind)), lots.length > 2 ? el("small", { text: fill(c.more, { n: lots.length - 2 }) }) : null),
        el("div", { class: "fx-progress" }, el("i", { style: `width:${Math.round((tool.progress || 0) * 100)}%;background:${STATE_COLOR[tool.state]}` })),
        el("small", { class: "muted", text: `${fill(c.tl.progress, { p: Math.round((tool.progress || 0) * 100) })} · ${fill(c.tl.until, { t: hm(tool.end) })}${tool.recipe ? ` · ${tool.recipe}` : ""}` }));
    } else if (tool.state === "down" || tool.state === "pm") {
      now = el("div", { class: "fx-now" }, el("small", { text: fill(c.tl.until, { t: hm(tool.until) }) }));
    } else {
      now = el("div", { class: "fx-now" }, el("small", { class: "muted", text: "—" }));
    }
    const next = (tool.next || []).slice(0, 3).map((n) => el("div", { class: `fx-next ${n.type}` },
      el("time", { text: hm(n.start) }),
      n.type === "pm" ? el("span", { class: "fx-reason warn", text: fill(c.reason.pm, { from: hm(n.start), to: hm(n.end) }) })
        : el("span", { class: "fx-next-lots" }, (n.lots || []).slice(0, 1).map((l) => lotLink(l.lot, l.kind)),
          n.lots && n.lots.length > 1 ? el("small", { text: `+${n.lots.length - 1}` }) : null),
      n.type === "pm" ? null : reasonChips(n.reasons, 2)));
    return el("div", { class: `fx-toolrow st-${tool.state}` },
      el("div", { class: "fx-toolname" }, el("strong", { text: tool.tool }), statePill(tool.state),
        tool.pm_next ? el("small", { class: "muted", text: fill(c.tl.pmNext, { t: hm(tool.pm_next) }) }) : null),
      now,
      timeline(tool.timeline || [], window),
      el("div", { class: "fx-nexts" }, next.length ? next : el("small", { class: "muted", text: c.tl.nothingNext })));
  }
  function timeline(items, window) {
    const [t0, t1] = window;
    const W = 240;
    const H = 22;
    const x = (v) => ((Math.max(t0, Math.min(t1, v)) - t0) / (t1 - t0)) * W;
    const node = svg("svg", { class: "fx-tl", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", width: "100%", height: H },
      svg("rect", { x: 0, y: 4, width: W, height: H - 8, rx: 3, fill: "var(--track)" }));
    for (const [kind, s, e, label, cls] of items) {
      const busy = kind === "run" || kind === "batch";
      const color = busy ? (cls === "VIP" ? CLASS_COLOR.VIP : cls === "hot" ? CLASS_COLOR.hot : STATE_COLOR.run) : STATE_COLOR[kind] || "#999";
      const rect = svg("rect", { x: x(s), y: 4, width: Math.max(1, x(e) - x(s)), height: H - 8, fill: color, rx: 1, stroke: "var(--card)", "stroke-width": 0.8 });
      rect.appendChild(svg("title", { text: `${C().states[busy ? "run" : kind] || kind} ${hm(s)}–${hm(e)} ${label || ""}` }));
      node.appendChild(rect);
    }
    node.appendChild(svg("line", { x1: x(S.t), x2: x(S.t), y1: 0, y2: H, stroke: "var(--ink)", "stroke-width": 1.5 }));
    return node;
  }

  // ---------- flow ----------
  async function viewFlow() {
    const c = C();
    const data = await api("flow", { t: S.t });
    const meta = S.meta;
    const legend = el("div", { class: "fx-legend" },
      el("span", { class: "fx-legend-title", text: c.fl.legendClass }),
      ["VIP", "hot", "normal"].map((k) => el("span", {}, el("i", { class: "round", style: `background:${CLASS_COLOR[k]}` }), c.classes[k])),
      el("span", { class: "fx-legend-title", text: c.fl.legendRisk }),
      ["late", "risk"].map((k) => el("span", {}, el("i", { class: "round ring", style: `border-color:${RISK_COLOR[k]}` }), c.risk[k])),
      el("span", {}, el("i", { class: "round", style: `background:${DONE_COLOR}` }), c.status.done));
    const lanes = data.products.map((p) => swimlane(p, meta));
    const maxW = Math.max(1, ...data.wip_by_group.map((g) => g.wait + g.run + g.hold));
    const wip = card(c.fl.wip, null, el("div", { class: "fx-rows" }, data.wip_by_group.map((g) => el("div", { class: "fx-wiprow" },
      el("span", { class: "fx-wipname", text: g.group }),
      el("span", { class: "fx-stack small", style: `width:${((g.wait + g.run + g.hold) / maxW) * 100}%` },
        g.run ? el("i", { style: `flex:${g.run};background:${STATE_COLOR.run}`, title: `${c.fl.running} ${g.run}` }) : null,
        g.wait ? el("i", { style: `flex:${g.wait};background:${STATE_COLOR.wait}`, title: `${c.fl.waiting} ${g.wait}` }) : null,
        g.hold ? el("i", { style: `flex:${g.hold};background:${STATE_COLOR.down}`, title: `${c.fl.hold} ${g.hold}` }) : null),
      el("small", { class: "num", text: `${g.run} / ${g.wait}${g.hold ? ` / ${g.hold}` : ""}` })))),
      el("div", { class: "fx-legend" }, el("span", {}, el("i", { style: `background:${STATE_COLOR.run}` }), c.fl.running),
        el("span", {}, el("i", { style: `background:${STATE_COLOR.wait}` }), c.fl.waiting)));
    const live = [];
    for (const p of data.products) for (const [lot, step, status, slack] of p.lots) if (status !== 3) live.push({ lot, step, status, slack, p });
    live.sort((a, b) => a.slack - b.slack);
    const row = (item) => el("li", {}, lotLink(meta.lot_id[item.lot], meta.lot_kind[item.lot]),
      el("small", { class: "muted", text: `${item.p.product} · ${item.step + 1}/${item.p.steps}` }),
      el("span", { class: `num ${item.slack < 0 ? "bad" : ""}`, text: `${(item.slack / 60).toFixed(1)} h` }));
    const behind = card(c.fl.behind, c.lot.slack, el("ol", { class: "fx-mini" }, live.slice(0, 8).map(row)));
    const ahead = card(c.fl.ahead, c.lot.slack, el("ol", { class: "fx-mini" }, live.slice(-8).reverse().map(row)));
    return [el("p", { class: "fx-note block", text: c.fl.note }), legend,
      el("div", { class: "fx-grid flow" }, el("div", { class: "fx-lanes" }, lanes), el("div", { class: "fx-side" }, wip, behind, ahead))];
  }
  function swimlane(p, meta) {
    const c = C();
    const W = 760;
    const H = 46;
    const node = svg("svg", { class: "fx-lane", viewBox: `0 0 ${W} ${H}`, width: "100%", height: H });
    // process-area band along the route
    const areas = p.areas || [];
    const groups = meta.groups || [];
    for (let i = 0; i < areas.length; i += 1) {
      const [step, group] = areas[i];
      const end = i + 1 < areas.length ? areas[i + 1][0] : p.steps;
      const hue = (groups.indexOf(group) * 47) % 360;
      const band = svg("rect", { x: (step / p.steps) * W, y: H - 6, width: Math.max(0.5, ((end - step) / p.steps) * W), height: 6, fill: `hsl(${hue} 45% 62%)` });
      band.appendChild(svg("title", { text: `${group} · ${fill(c.tl.step, { n: step + 1 })}` }));
      node.appendChild(band);
    }
    node.appendChild(svg("line", { x1: 0, x2: W, y1: 20, y2: 20, stroke: "var(--line)" }));
    const stacks = new Map();
    const sorted = [...p.lots].sort((a, b) => (CLASS_RANK[meta.lot_kind[a[0]]] || 0) - (CLASS_RANK[meta.lot_kind[b[0]]] || 0));
    for (const [lot, step, status, slack] of sorted) {
      const kind = meta.lot_kind[lot];
      const col = Math.round((step / p.steps) * (W / 5));
      const k = stacks.get(col) || 0;
      stacks.set(col, k + 1);
      const offset = ((k % 7) - 3) * 4.4;
      const risk = status === 3 ? "ok" : slack < 0 ? "late" : slack < 480 ? "risk" : "ok";
      const r = kind === "normal" ? 2.6 : 3.8;
      const dot = svg("circle", {
        cx: Math.min(W - 4, Math.max(4, (step / p.steps) * W)),
        cy: 20 + offset,
        r,
        fill: status === 3 ? DONE_COLOR : CLASS_COLOR[kind],
        "fill-opacity": status === 0 ? 0.55 : 1,
        stroke: RISK_COLOR[risk] === "transparent" ? "none" : RISK_COLOR[risk],
        "stroke-width": risk === "ok" ? 0 : 1.6,
        class: "fx-dotsvg",
        onclick: () => openLot(meta.lot_id[lot]),
      });
      dot.appendChild(svg("title", { text: `${meta.lot_id[lot]} · ${c.classes[kind]} · ${fill(c.tl.step, { n: step + 1 })}/${p.steps} · ${C().status[STATUS[status]]} · ${(slack / 60).toFixed(1)} h` }));
      node.appendChild(dot);
    }
    return el("div", { class: "fx-lanebox" },
      el("div", { class: "fx-lanehead" },
        el("strong", { text: p.product }),
        el("small", { class: "muted", text: `${fill(c.fl.steps, { n: p.steps })} · ${p.lots.length}` }),
        el("span", { class: "fx-lanecounts" },
          p.counts.late ? el("span", { class: "fx-pill rk-late", text: `${c.risk.late} ${p.counts.late}` }) : null,
          p.counts.risk ? el("span", { class: "fx-pill rk-risk", text: `${c.risk.risk} ${p.counts.risk}` }) : null,
          el("span", { class: "fx-pill rk-ok", text: `${c.risk.ok} ${p.counts.ok}` }),
          el("span", { class: "fx-pill s-done", text: `${c.status.done} ${p.counts.done}` }))),
      node);
  }
  const CLASS_RANK = { normal: 0, hot: 1, VIP: 2 };

  // ---------- lots ----------
  async function viewLots() {
    const c = C();
    const input = el("input", { type: "search", class: "fx-search", placeholder: c.lot.search, value: S.lot || "", list: "fx-lot-ids" });
    const go = () => { const v = input.value.trim(); if (v) openLot(v); };
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") go(); });
    const bar0 = el("div", { class: "fx-filterbar" }, input, el("button", { type: "button", class: "fx-btn", onclick: go }, c.lot.open),
      S.recentLots.length ? el("span", { class: "fx-recent" }, el("small", { class: "muted", text: c.lot.recent }), S.recentLots.map((n) => lotLink(n, guessKind(n)))) : null);
    if (!S.lot) {
      const o = await api("overview", { t: S.t });
      return [bar0, el("p", { class: "fx-note block", text: c.lot.pick }), el("div", { class: "fx-grid two" },
        card(C().ov.priority, null, lotTable(o.priority.slice(0, 10))), card(C().ov.atRisk, null, lotTable(o.at_risk.slice(0, 10))))];
    }
    let lot;
    try {
      lot = await api(`lot/${encodeURIComponent(S.lot)}`, { t: S.t });
    } catch (error) {
      return [bar0, el("p", { class: "fx-error", text: fill(c.lot.notFound, { id: S.lot }) })];
    }
    const head = el("section", { class: "fx-card fx-lothead" },
      el("div", {}, el("h2", {}, el("i", { class: "fx-dot big", style: `background:${CLASS_COLOR[lot.kind]}` }), lot.lot),
        el("p", { class: "muted", text: fill(c.lot.header, { product: lot.product, step: lot.step + 1, steps: lot.steps }) })),
      el("div", { class: "fx-lotfacts" },
        el("span", { class: "fx-pill", text: kindLabel(lot.kind) }),
        el("span", { class: `fx-status s-${lot.status}`, text: c.status[lot.status] }),
        lot.risk ? riskPill(lot.risk) : null,
        el("span", { text: `${c.lot.slack} ${lot.slack_h === null ? "—" : `${lot.slack_h} h`}` }),
        el("span", { text: fill(c.lot.due, { t: clock(lot.due) }) }),
        el("span", { text: lot.done_at !== null && lot.done_at !== undefined ? fill(c.lot.finished, { t: clock(lot.done_at) }) : lot.finished >= 0 ? fill(c.lot.willFinish, { t: clock(lot.finished) }) : c.lot.notFinished }),
        lot.family ? el("button", { type: "button", class: "fx-link", onclick: () => openFamily(lot.family, lot.group), text: `${lot.family} →` }) : null));
    const ops = lot.ops || [];
    const gantt = lotGantt(ops);
    const table = el("table", { class: "fx-table ops" },
      el("thead", {}, el("tr", {}, [c.lot.colStep, c.lot.colTool, c.lot.colReady, c.lot.colStart, c.lot.colWait, c.lot.colWhy].map((h) => el("th", { text: h })))),
      el("tbody", {}, ops.map((op) => el("tr", { class: op.start > S.t ? "future" : op.end > S.t ? "current" : "" },
        el("td", { text: `${op.step + 1}` }),
        el("td", {}, el("strong", { text: op.tool }), el("small", { class: "muted", text: ` ${op.family}` }), op.interrupted ? el("span", { class: "fx-reason bad", text: c.lot.interrupted }) : null),
        el("td", { class: "muted", text: hm(op.ready) }),
        el("td", { text: hm(op.start) }),
        el("td", { class: "num", text: dur((op.start - op.ready) / 60) }),
        el("td", {}, reasonChips(op.reasons, 4), op.batch_lots > 1 ? el("span", { class: "fx-reason", text: fill(c.bt.lotsN, { n: op.batch_lots }) }) : null)))));
    const side = [];
    side.push(card(c.lot.qtime, String(lot.qtime.length), lot.qtime.length ? el("ul", { class: "fx-mini" }, lot.qtime.map((q) => el("li", { class: q.outcome === "violated" ? "bad" : "" },
      el("span", { text: fill(c.lot.qtimeRow, { a: q.origin + 1, b: q.target + 1, outcome: c.lot.outcome[q.outcome] || q.outcome }) }),
      el("small", { class: "muted", text: `${hm(q.opened)} → ${hm(q.deadline)}` })))) : empty(c.none)));
    if (lot.skips.length) side.push(card(c.lot.skips, String(lot.skips.length), el("ul", { class: "fx-mini" }, lot.skips.map((s) => el("li", {}, el("span", { text: fill(c.tl.step, { n: s.step + 1 }) }), el("small", { class: "muted", text: hm(s.t) }))))));
    if (lot.reworks.length) side.push(card(c.lot.reworks, String(lot.reworks.length), eventList(lot.reworks.map((r) => ({ ...r, kind: "rework", lot: lot.lot })))));
    if (lot.recleans.length) side.push(card(c.lot.recleans, String(lot.recleans.length), eventList(lot.recleans.map((r) => ({ ...r, kind: "reclean", lot: lot.lot })))));
    if (lot.upcoming.length) side.push(card(c.lot.upcoming, null, el("ol", { class: "fx-mini" }, lot.upcoming.map((u) => el("li", {}, el("span", { text: fill(c.tl.step, { n: u.step + 1 }) }), el("small", { class: "muted", text: u.family }))))));
    return [bar0, head, card(c.lot.timeline, lot.release_step ? fill(c.lot.released, { n: lot.release_step + 1 }) : null, gantt),
      el("div", { class: "fx-grid two-one" }, card(c.lot.colWhy, null, el("div", { class: "fx-scrollx" }, table)), el("div", { class: "fx-side" }, side))];
  }
  function guessKind(name) {
    if (!S.meta) return "normal";
    const index = S.meta.lot_id.indexOf(name);
    return index >= 0 ? S.meta.lot_kind[index] : "normal";
  }
  function lotGantt(ops) {
    const W = 1200;
    const H = 46;
    const x = (v) => (Math.max(0, Math.min(HORIZON, v)) / HORIZON) * W;
    const node = svg("svg", { class: "fx-gantt", viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, preserveAspectRatio: "none" },
      svg("rect", { x: 0, y: 10, width: W, height: 18, fill: "var(--track)", rx: 3 }));
    for (const op of ops) {
      const parts = [["wait", op.ready, op.start], ["setup", op.start, op.start + op.setup_min * 60], ["run", op.start + op.setup_min * 60, op.end]];
      for (const [kind, s, e] of parts) {
        if (e <= s) continue;
        const r = svg("rect", { x: x(s), y: 10, width: Math.max(0.8, x(e) - x(s)), height: 18, fill: STATE_COLOR[kind], opacity: op.interrupted ? 0.6 : 1 });
        r.appendChild(svg("title", { text: `${fill(C().tl.step, { n: op.step + 1 })} · ${op.tool} · ${C().states[kind] || C().status.wait} ${hm(s)}–${hm(e)}` }));
        node.appendChild(r);
      }
    }
    for (let h = 0; h <= 48; h += 6) {
      node.appendChild(svg("line", { x1: x(h * 3600), x2: x(h * 3600), y1: 28, y2: 32, stroke: "var(--muted)" }));
      node.appendChild(svg("text", { x: Math.min(W - 18, x(h * 3600) + 2), y: 42, "font-size": 10, fill: "var(--muted)", text: `${h}h` }));
    }
    node.appendChild(svg("line", { x1: x(S.t), x2: x(S.t), y1: 4, y2: 32, stroke: "var(--ink)", "stroke-width": 2 }));
    return node;
  }

  // ---------- batches ----------
  async function viewBatches() {
    const c = C();
    const data = await api("batches", { t: S.t });
    const forming = data.forming.map((b) => {
      const wafers = Math.min(b.wafers, b.max);
      const urgent = b.countdown_min !== null && b.countdown_min !== undefined;
      return el("section", { class: `fx-card fx-batch ${b.hot ? "hot" : ""}` },
        el("header", {}, el("h3", { text: b.family }), el("small", { class: "muted", text: b.recipe }), b.hot ? el("span", { class: "fx-badge bad", text: c.bt.hot }) : null),
        gauge(wafers, b.min, b.max),
        el("p", { class: "fx-small", text: fill(c.bt.wafers, { w: b.wafers, min: b.min, max: b.max }) }),
        el("p", { class: "fx-small" }, el("strong", { text: c.bt.waitingFor[b.waiting_for] || b.waiting_for }), " · ",
          urgent ? (b.countdown_min >= 0 ? fill(c.bt.capAt, { min: b.countdown_min }) : fill(c.bt.capPassed, { min: -b.countdown_min })) : ""),
        el("div", { class: "fx-bd-lots" }, b.lots.slice(0, 6).map((l) => lotLink(l.lot, l.kind)), b.queued > b.lots.length ? el("small", { class: "muted", text: fill(c.bt.queued, { n: b.queued }) }) : null),
        b.started ? el("p", { class: "fx-small muted", text: fill(c.bt.started, { t: hm(b.started.t), tool: b.started.tool }) }) : null);
    });
    const running = data.running.map((b) => el("section", { class: "fx-card fx-batch is-run" },
      el("header", {}, el("h3", { text: b.tool }), el("small", { class: "muted", text: `${b.family} · ${b.recipe}` })),
      gauge(b.wafers, b.min, b.max),
      el("div", { class: "fx-progress" }, el("i", { style: `width:${Math.round(b.progress * 100)}%;background:${STATE_COLOR.run}` })),
      el("p", { class: "fx-small", text: `${fill(c.tl.progress, { p: Math.round(b.progress * 100) })} · ${fill(c.bt.ends, { t: hm(b.end) })} · ${C().why[b.why] || b.why}` }),
      el("div", { class: "fx-bd-lots" }, b.lots.slice(0, 6).map((l) => lotLink(l.lot, l.kind)), b.lots.length > 6 ? el("small", { text: fill(c.more, { n: b.lots.length - 6 }) }) : null)));
    return [
      el("h3", { class: "fx-h" }, c.bt.forming, el("small", { class: "muted", text: ` ${data.forming.length} · ${c.bt.formingNote}` })),
      forming.length ? el("div", { class: "fx-cards" }, forming) : empty(c.bt.none),
      el("h3", { class: "fx-h" }, c.bt.running, el("small", { class: "muted", text: ` ${data.running.length}` })),
      running.length ? el("div", { class: "fx-cards" }, running) : empty(c.bt.none),
    ];
  }
  function gauge(wafers, min, max) {
    const W = 220;
    const x = (v) => (Math.min(v, max) / max) * W;
    return svg("svg", { class: "fx-gauge", viewBox: `0 0 ${W} 16`, width: "100%", height: 16, preserveAspectRatio: "none" },
      svg("rect", { x: 0, y: 3, width: W, height: 10, rx: 5, fill: "var(--track)" }),
      svg("rect", { x: 0, y: 3, width: x(wafers), height: 10, rx: 5, fill: wafers >= min ? DONE_COLOR : STATE_COLOR.wait }),
      svg("line", { x1: x(min), x2: x(min), y1: 0, y2: 16, stroke: "var(--ink)", "stroke-width": 1.5 }));
  }

  // ---------- KPIs ----------
  async function viewKpis() {
    const c = C().kp;
    const data = await api("kpis", {});
    const P = data.periods;
    const rows = [
      [c.rows.onTime, (p) => `${p.due_date.on_time_rate}%`, (p) => `${p.due_date.on_time}/${p.due_date.completed}`],
      [c.rows.completed, (p) => p.due_date.completed],
      [c.rows.avgDelay, (p) => (p.due_date.late ? dur(p.due_date.avg_delay_min) : "—")],
      [c.rows.qtime, (p) => `${p.qtime.rate}%`, (p) => `${p.qtime.checked - p.qtime.violated}/${p.qtime.checked}`],
      [c.rows.setupRate, (p) => `${p.setup.setup_rate}%`],
      [c.rows.waitRate, (p) => `${p.equipment.wait_rate}%`],
      [c.rows.moves, (p) => p.throughput.lots.toLocaleString()],
      [c.rows.wafers, (p) => p.throughput.wafers.toLocaleString()],
      [c.rows.batches, (p) => p.batch.batches],
      [c.rows.batchFill, (p) => `${p.batch.fill_rate}%`],
      [c.rows.grouping, (p) => `${p.same_recipe.grouping_rate}%`],
      [c.rows.queue, (p) => dur(p.lot_steps.all.queue_mean_min)],
      [c.rows.xfactor, (p) => p.lot_steps.all.xfactor_mean],
    ];
    const table = el("table", { class: "fx-table fx-kpit" },
      el("thead", {}, el("tr", {}, el("th", { text: c.metric }), P.map((p) => el("th", { class: "num", text: c.periods[p.name] || p.name })))),
      el("tbody", {}, rows.map(([label, value, sub]) => el("tr", {}, el("td", { text: label }),
        P.map((p) => el("td", { class: "num" }, el("strong", { text: String(value(p)) }), sub ? el("small", { class: "muted", text: ` ${sub(p)}` }) : null))))));
    const acts = ["production", "setup", "down", "pm", "idle"];
    const actColor = { production: STATE_COLOR.run, setup: STATE_COLOR.setup, down: STATE_COLOR.down, pm: STATE_COLOR.pm, idle: STATE_COLOR.idle };
    const activity = card(c.activity, null, P.map((p) => el("div", { class: "fx-wiprow" },
      el("span", { class: "fx-wipname", text: c.periods[p.name] }),
      el("span", { class: "fx-stack small", style: "width:100%" }, acts.filter((a) => p.activity[a] > 0).map((a) =>
        el("i", { style: `flex:${p.activity[a]};background:${actColor[a]}`, title: `${c.act[a]} ${p.activity[a]}%` }))))),
    el("div", { class: "fx-legend" }, acts.map((a) => el("span", {}, el("i", { style: `background:${actColor[a]}` }), `${c.act[a]} ${P[2] ? P[2].activity[a] : ""}%`))));
    const all = P[P.length - 1];
    const load = card(c.load, c.periods.all, el("div", { class: "fx-rows" }, all.load_by_group.map((g) => el("div", { class: "fx-wiprow" },
      el("span", { class: "fx-wipname", text: g.group }), bar(g.load_rate, 100, g.load_rate >= 85 ? "var(--alarm)" : "var(--accent)"),
      el("small", { class: "num", text: `${g.load_rate}%` })))));
    const classes = ["VIP", "hot", "normal"];
    const cls = card(c.classWait, c.periods.all, el("div", { class: "fx-rows" }, classes.map((k) => el("div", { class: "fx-wiprow" },
      el("span", { class: "fx-wipname", text: C().classes[k] }),
      bar(all.lot_steps[k].queue_mean_min, Math.max(...classes.map((x) => all.lot_steps[x].queue_mean_min)), CLASS_COLOR[k]),
      el("small", { class: "num", text: dur(all.lot_steps[k].queue_mean_min) }))))) ;
    return [el("p", { class: "fx-note block", text: c.note }), el("div", { class: "fx-grid two-one" }, card(C().tabs.kpis, null, table), el("div", { class: "fx-side" }, activity, cls, load))];
  }

  const VIEWS = { overview: viewOverview, tools: viewTools, flow: viewFlow, lots: viewLots, batches: viewBatches, events: viewEvents, kpis: viewKpis };

  // ---------- public ----------
  window.Fab = {
    tabs() {
      const c = C();
      return TABS.map((id) => [`fab-${id}`, c.tabs[id]]);
    },
    show(tab) {
      if (!TABS.includes(tab)) return;
      S.tab = tab;
      render();
    },
    openBook(key) {
      if (!key) return;
      if (BOOKS.includes(key)) S.book = key;
      else { S.whatif = key; S.book = "whatif"; }
      S.meta = null;
      goto("overview");
    },
    state: S,
  };
})();
