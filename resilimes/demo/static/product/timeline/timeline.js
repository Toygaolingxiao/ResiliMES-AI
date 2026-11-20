// Production Gantt. Bars are canvas; the axis, row headers, tooltip and menu are DOM.
// Zoom is a linear scale plus a pointer transform (the same model as d3-scale / d3-zoom)
// without those packages: this page has no bundler, and d3-zoom drives DOM selections.
(function () {
  const LABEL_W = 196;
  const AXIS_H = 46;
  const ROW_H = 32;
  const GROUP_H = 28;
  const BAR_H = 20;
  const FILL = {
    processing: "#FFD700",
    scheduled: "#5B8DEF",
    reserved: "#FF69B4",
    waiting: "#82C213",
    transport: "#8080C0",
    setup: "#FFA400",
    down: "#6b6258",
    pm: "#808080",
    idle: "#e7e2d8",
  };
  const INK = {
    processing: "#1e293b",
    scheduled: "#ffffff",
    reserved: "#1e293b",
    waiting: "#1e293b",
    transport: "#ffffff",
  };
  const STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 720, 1440, 2880];

  function mount(host, options) {
    const opt = options || {};
    const url = opt.url || "/api/timeline";
    host.innerHTML = "";
    host.appendChild(shell());
    const $ = (sel) => host.querySelector(sel);
    const state = {
      lang: localStorage.getItem("resilimes.lang") || "ja",
      catalog: null,
      payload: null,
      view: "machine",
      t0: null,
      t1: null,
      focus: "",
      collapsed: new Set(),
      links: false,
      scroll: 0,
      token: 0,
      hover: null,
      drag: null,
    };
    if (new URLSearchParams(location.search).get("view") === "product") state.view = "product";
    function copy() {
      const table = state.catalog && (state.catalog[state.lang] || state.catalog.ja);
      return (table && table.timeline) || {};
    }
    function text(node, value) {
      if (node) node.textContent = value == null ? "" : String(value);
    }
    function paint() {
      const c = copy();
      document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang;
      document.title = c.title || "工程ガント";
      text($(".tl-home"), c.back || "ResiliMES");
      text($(".tl-title"), c.title || "工程ガント");
      text($(".tl-lead"), c.lead || "");
      host.querySelectorAll("[data-lang]").forEach((button) => {
        button.setAttribute("aria-pressed", button.getAttribute("data-lang") === state.lang ? "true" : "false");
      });
      text($("[data-view-text='machine']"), c.viewMachine || "装置別");
      text($("[data-view-text='product']"), c.viewProduct || "製品・ロット");
      text($(".tl-links-label"), c.links || "");
      text($(".tl-idle-label"), c.idleTools || "");
      text($(".tl-lot-unit"), c.lotUnit || "");
      text($(".tl-refresh"), c.refresh || "更新");
      text($(".tl-reset"), c.reset || "リセット");
      text($(".tl-fit"), c.fit || "全体");
      text($(".tl-zoom-in"), c.zoomIn || "拡大");
      text($(".tl-zoom-out"), c.zoomOut || "縮小");
      text($(".tl-png"), c.exportPng || "PNG");
      text($(".tl-csv"), c.exportCsv || "CSV");
      text($(".tl-fold"), (state.filtersOpen ? "▼ " : "▶ ") + (c.filter || "フィルタ"));
      text($(".tl-help"), "");
      $(".tl-help").append(document.createTextNode(c.help || ""));
      const fields = ["machine", "group", "lot", "step", "product", "priority", "start", "end"];
      for (const name of fields) text($(`.tl-field-${name}`), c[name] || name);
      text($(".tl-view-label"), c.view || "");
      text($(".tl-corner"), state.view === "machine" ? (c.machine || "") : (c.lot || ""));
      paintLegend(c);
      paintStats();
      draw();
      // The scope notice is the one line that reconciles the cards with
      // the drawn bars; re-render it on language switch too, not only on
      // load, or it goes stale in the previous language.
      if (state.payload) {
        const status = statusFor(state.payload, c);
        setStatus(status.message, status.warn);
      }
    }
    function paintLegend(c) {
      const items = [
        ["processing", c.processing, c.running],
        ["scheduled", c.scheduled],
        ["reserved", c.reserved],
        ["waiting", c.waiting],
        ["transport", c.transport],
        ["setup", c.setup],
        ["down", c.down],
        ["pm", c.pm],
        ["idle", c.idle],
      ];
      const box = $(".tl-legend");
      box.replaceChildren();
      for (const [key, label, extra] of items) {
        const node = document.createElement("span");
        const swatch = document.createElement("i");
        swatch.className = "tl-swatch";
        swatch.style.background = FILL[key];
        node.append(swatch, document.createTextNode(extra ? `${label} · ${extra}` : label || key));
        box.appendChild(node);
      }
      const late = document.createElement("span");
      late.textContent = c.lateLots || "";
      late.style.color = "#9c2b1a";
      box.appendChild(late);
    }
    function paintStats() {
      const c = copy();
      const stats = (state.payload && state.payload.stats) || {};
      const cards = [
        ["jobs", stats.total_jobs],
        ["machines", stats.total_equipment],
        ["lots", stats.total_lots],
        ["operations", stats.total_operations],
        ["moves", stats.total_moves],
        ["skips", stats.skip_count],
        ["lateLots", stats.late_lots],
        ["qtime", (stats.qtime_risk || 0) + (stats.qtime_breach || 0)],
      ];
      const box = $(".tl-stats");
      box.replaceChildren();
      for (const [key, value] of cards) {
        if (key === "skips" && !value) continue;
        const card = document.createElement("div");
        card.className = "tl-stat";
        const label = document.createElement("span");
        label.textContent = c[key] || key;
        const number = document.createElement("b");
        number.textContent = value == null ? "—" : String(value);
        card.append(label, number);
        box.appendChild(card);
      }
      const daily = $(".tl-daily");
      daily.replaceChildren();
      for (const day of (state.payload && state.payload.daily) || []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tl-day";
        button.textContent = `${clock(day.start_min, true)}  ${day.jobs}`;
        button.addEventListener("click", () => {
          state.t0 = day.start_min;
          state.t1 = day.start_min + 1440;
          load();
        });
        daily.appendChild(button);
      }
      const selected = $(".tl-selected");
      if (!state.focus) text(selected, "");
      else {
        selected.replaceChildren();
        selected.append(document.createTextNode(`${c.selected || ""} ${state.focus} `));
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "tl-btn";
        clear.textContent = c.clear || "解除";
        clear.addEventListener("click", () => { state.focus = ""; draw(); paintStats(); });
        selected.appendChild(clear);
      }
      fillFacets();
    }
    function fillFacets() {
      const facets = (state.payload && state.payload.facets) || {};
      fillSelect($(".tl-group-select"), facets.groups || [], $(".tl-group-select").value);
      fillSelect($(".tl-product-select"), (facets.products || []).map((item) => item.id), $(".tl-product-select").value);
      fillSelect($(".tl-priority-select"), (facets.priorities || []).map(String), $(".tl-priority-select").value);
    }
    function fillSelect(select, values, current) {
      const all = copy().priorityAll || copy().all || "すべて";
      const chosen = current || "";
      select.replaceChildren();
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = all;
      select.appendChild(blank);
      for (const value of values) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        if (value === chosen) option.selected = true;
        select.appendChild(option);
      }
    }

    function params() {
      const query = new URLSearchParams();
      const span = state.t0 != null && state.t1 != null ? Math.max(30, state.t1 - state.t0) : null;
      if (span != null) {
        query.set("t0", String(Math.max(0, state.t0 - span)));
        query.set("t1", String(state.t1 + span));
        // The display window: stats and scope are computed over this, not
        // the wider prefetched fetch.
        query.set("view_t0", String(state.t0));
        query.set("view_t1", String(state.t1));
      }
      const machine = $(".tl-machine").value.trim();
      const group = $(".tl-group-select").value;
      const lot = $(".tl-lot").value.trim();
      const step = $(".tl-step").value.trim();
      const product = $(".tl-product-select").value;
      const priority = $(".tl-priority-select").value;
      if (machine) query.set("machine", machine);
      if (group) query.set("group", group);
      if (lot) query.set("lot", lot);
      if (step) query.set("step", step);
      if (product) query.set("product", product);
      if (priority) query.set("priority", priority);
      query.set("lots", $(".tl-lots").value || "100");
      if ($(".tl-idle").checked) query.set("idle", "true");
      if (state.focus) query.set("focus", state.focus);
      return query;
    }
    function applyDates() {
      const origin = state.payload && state.payload.origin;
      const start = fromInput(origin, $(".tl-start").value);
      const end = fromInput(origin, $(".tl-end").value);
      if (start != null && end != null && end > start) {
        state.t0 = start;
        state.t1 = end;
      }
    }
    async function load() {
      const seq = ++state.token;
      setStatus(copy().loading || "…");
      let body;
      try {
        const response = await fetch(`${url}?${params().toString()}`);
        if (!response.ok) throw new Error(String(response.status));
        body = await response.json();
      } catch (error) {
        if (seq !== state.token) return;
        setStatus(fill(copy().error || "{msg}", { msg: error.message || error }), true);
        return;
      }
      if (seq !== state.token) return;
      state.payload = body;
      if (state.t0 == null || state.t1 == null) {
        state.t0 = body.window.t0;
        state.t1 = body.window.t1;
      }
      index();
      const status = statusFor(body, copy());
      setStatus(status.message, status.warn);
      syncInputs();
      paint();
    }
    function index() {
      const bars = dedupe((state.payload.bars || []).concat(state.payload.focus_bars || []));
      state.byMachine = indexBy(bars.filter((bar) => !bar.gap), (bar) => bar.machine);
      state.byLot = new Map();
      for (const bar of bars) {
        addLot(bar.lot, bar);
        for (const other of bar.also || []) addLot(other, bar);
      }
      for (const gap of state.payload.gaps || []) addLot(gap.lot, gap);
      for (const list of state.byLot.values()) list.sort((a, b) => a.start_min - b.start_min);
      state.byBlock = indexBy(state.payload.blocks || [], (block) => block.machine);
    }
    function addLot(lot, bar) {
      const list = state.byLot.get(lot);
      if (list) list.push(bar);
      else state.byLot.set(lot, [bar]);
    }
    function rows() {
      const payload = state.payload;
      if (!payload) return [];
      const source = state.view === "machine" ? payload.machine_rows : payload.product_rows;
      const out = [];
      let hidden = "";
      for (const row of source || []) {
        if (row.kind === "group" || row.kind === "product") {
          out.push(row);
          hidden = state.collapsed.has(row.id) ? row.id : "";
        } else if (hidden && row.parent === hidden) {
          continue;
        } else out.push(row);
      }
      return out;
    }
    function layout() {
      let y = 0;
      const boxes = [];
      for (const row of rows()) {
        const h = row.kind === "group" || row.kind === "product" ? GROUP_H : ROW_H;
        boxes.push({ row, y, h });
        y += h;
      }
      return { boxes, height: y };
    }
    function trackW() {
      const scroll = $(".tl-scroll");
      return Math.max(120, (scroll.clientWidth || 800) - LABEL_W - 16);
    }
    function viewH() {
      return Math.max(200, $(".tl-scroll").clientHeight || 480);
    }
    function span() {
      return Math.max(1, (state.t1 || 1) - (state.t0 || 0));
    }
    function xOf(minute, width) {
      return ((minute - state.t0) / span()) * width;
    }
    function minuteOf(x, width) {
      return state.t0 + (x / width) * span();
    }
    function draw() {
      if (!state.payload || state.t0 == null) return;
      scale.t0 = state.t0;
      scale.span = span();
      const scroll = $(".tl-scroll");
      const width = trackW();
      const height = viewH();
      const laid = layout();
      $(".tl-spacer").style.height = `${Math.max(laid.height, height)}px`;
      const pane = $(".tl-pane");
      pane.style.height = `${height}px`;
      pane.style.width = `${LABEL_W + width}px`;
      const labels = $(".tl-labels");
      labels.style.height = `${height}px`;
      labels.replaceChildren();
      const top = state.scroll;
      for (const box of laid.boxes) {
        if (box.y + box.h < top || box.y > top + height) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = `tl-row ${box.row.kind}${box.row.late ? " late" : ""}`;
        button.style.top = `${box.y - top}px`;
        button.style.height = `${box.h}px`;
        const mark = box.row.kind === "group" || box.row.kind === "product"
          ? (state.collapsed.has(box.row.id) ? "▸ " : "▾ ")
          : "";
        const count = box.row.count != null ? `  ${box.row.count}` : "";
        button.textContent = `${mark}${box.row.label || box.row.id}${count}`;
        button.title = box.row.family || box.row.label || "";
        if (box.row.kind === "group" || box.row.kind === "product") {
          button.addEventListener("click", () => {
            if (state.collapsed.has(box.row.id)) state.collapsed.delete(box.row.id);
            else state.collapsed.add(box.row.id);
            draw();
          });
        }
        labels.appendChild(button);
      }
      const canvas = $(".tl-bars");
      paintCanvas(canvas, width, height, top, laid);
      paintAxis(width);
      const empty = !laid.boxes.length;
      $(".tl-empty").hidden = !empty;
      if (empty) text($(".tl-empty"), copy().empty || "");
    }
    function paintCanvas(canvas, width, height, top, laid) {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#fafafa";
      ctx.fillRect(0, 0, width, height);
      drawGrid(ctx, width, height);
      for (const box of laid.boxes) {
        if (box.y + box.h < top || box.y > top + height) continue;
        const y = box.y - top;
        if (box.row.kind === "machine") drawMachine(ctx, box.row.id, y, box.h, width);
        else if (box.row.kind === "lot") drawLot(ctx, box.row.id, y, box.h, width);
        else {
          ctx.fillStyle = "#f1f5f9";
          ctx.fillRect(0, y, width, box.h);
        }
        ctx.strokeStyle = "#e2e8f0";
        ctx.beginPath();
        ctx.moveTo(0, y + box.h - 0.5);
        ctx.lineTo(width, y + box.h - 0.5);
        ctx.stroke();
      }
      if (state.links || state.focus) drawLinks(ctx, width, laid, top, height);
      drawNow(ctx, width, height);
      if (state.focus) drawDue(ctx, width, height);
    }
    function drawGrid(ctx, width, height) {
      const step = chooseStep(span(), width);
      ctx.save();
      ctx.beginPath();
      for (let minute = Math.ceil(state.t0 / 480) * 480; minute < state.t1; minute += 480) {
        const x = xOf(minute, width);
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
      }
      ctx.strokeStyle = "#e2e8f0";
      ctx.stroke();
      ctx.beginPath();
      for (let minute = Math.ceil(state.t0 / 1440) * 1440; minute < state.t1; minute += 1440) {
        const x = xOf(minute, width);
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
      }
      ctx.strokeStyle = "#cbd5e1";
      ctx.stroke();
      ctx.restore();
      void step;
    }
    function drawMachine(ctx, id, y, h, width) {
      for (const block of overlaps(state.byBlock.get(id) || [], state.t0, state.t1)) {
        band(ctx, block.start_min, block.end_min, y + 2, h - 4, width, FILL[block.kind] || FILL.down, block.kind === "down");
      }
      const bars = overlaps(state.byMachine.get(id) || [], state.t0, state.t1).filter((bar) => !bar.gap);
      drawIdle(ctx, bars, state.byBlock.get(id) || [], y, h, width);
      for (const bar of bars) drawBar(ctx, bar, y, width, true);
    }
    function drawLot(ctx, id, y, h, width) {
      const bars = overlaps(state.byLot.get(id) || [], state.t0, state.t1);
      for (const bar of bars) drawBar(ctx, bar, y, width, false);
      void h;
    }
    function drawIdle(ctx, bars, blocks, y, h, width) {
      const spans = bars.concat(blocks).map((item) => [item.start_min, item.end_min]).sort((a, b) => a[0] - b[0]);
      let cursor = state.t0;
      const merged = [];
      for (const [start, end] of spans) {
        const a = Math.max(start, state.t0);
        const b = Math.min(end, state.t1);
        if (b <= a) continue;
        if (!merged.length || a > merged[merged.length - 1][1]) merged.push([a, b]);
        else merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], b);
      }
      for (const [start, end] of merged) {
        if (start - cursor >= 15) band(ctx, cursor, start, y + 4, h - 8, width, FILL.idle, false);
        cursor = end;
      }
      if (state.t1 - cursor >= 15) band(ctx, cursor, state.t1, y + 4, h - 8, width, FILL.idle, false);
    }
    function drawBar(ctx, bar, y, width, machine) {
      const x = xOf(bar.start_min, width);
      const w = Math.max(1.5, xOf(bar.end_min, width) - x);
      const member = isMember(bar, state.focus);
      ctx.save();
      ctx.globalAlpha = state.focus && !member ? 0.28 : 1;
      ctx.fillStyle = FILL[bar.state] || FILL.scheduled;
      roundRect(ctx, x, y + 6, w, BAR_H, 3);
      ctx.fill();
      if (bar.setup_min > 0 && !bar.gap) {
        const setupW = Math.min(w, (bar.setup_min / span()) * width);
        ctx.fillStyle = FILL.setup;
        ctx.fillRect(x, y + 6, setupW, BAR_H);
        hatchRect(ctx, x, y + 6, setupW, BAR_H);
      }
      if (bar.late) {
        ctx.strokeStyle = "#9c2b1a";
        ctx.lineWidth = 2;
        ctx.strokeRect(x + 1, y + 7, Math.max(0, w - 2), BAR_H - 2);
      }
      if (member) {
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 2;
        ctx.strokeRect(x + 0.5, y + 5, w, BAR_H + 2);
      }
      if (bar.qtime) {
        ctx.fillStyle = bar.qtime === "breach" ? "#b42318" : "#e6a100";
        ctx.beginPath();
        ctx.moveTo(x + w - 8, y + 6);
        ctx.lineTo(x + w, y + 6);
        ctx.lineTo(x + w, y + 14);
        ctx.fill();
      }
      ctx.font = "12px sans-serif";
      ctx.textBaseline = "middle";
      const full = machine
        ? `${bar.lot} · ${bar.step}${bar.recipe ? " · " + bar.recipe : ""}`
        : `${bar.gap ? labelState(bar.state) : bar.machine} · ${bar.step}`;
      const short = machine ? bar.lot : (bar.gap ? labelState(bar.state) : bar.machine);
      const label = ctx.measureText(full).width + 8 <= w ? full : short;
      if (ctx.measureText(label).width + 8 <= w) {
        ctx.beginPath();
        ctx.rect(x + 2, y + 6, w - 4, BAR_H);
        ctx.clip();
        ctx.fillStyle = INK[bar.state] || "#1e293b";
        ctx.fillText(label, x + 4, y + 6 + BAR_H / 2);
      }
      ctx.restore();
    }
    function drawLinks(ctx, width, laid, top, height) {
      const lots = state.focus ? [state.focus] : visibleLots(laid, top, height).slice(0, 30);
      if (!state.links && !state.focus) return;
      ctx.save();
      ctx.strokeStyle = "#0f172a";
      ctx.globalAlpha = 0.45;
      ctx.lineWidth = 1.25;
      for (const lot of lots) {
        const bars = (state.byLot.get(lot) || []).filter((bar) => !bar.gap).sort((a, b) => a.start_min - b.start_min);
        for (let i = 0; i < bars.length - 1; i += 1) {
          const a = center(bars[i], laid, width, top);
          const b = center(bars[i + 1], laid, width, top);
          if (!a || !b) continue;
          if ((a.y < 0 && b.y < 0) || (a.y > height && b.y > height)) continue;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
      ctx.restore();
    }
    function center(bar, laid, width, top) {
      const rowId = state.view === "machine" ? bar.machine : bar.lot;
      const box = laid.boxes.find((item) => item.row.id === rowId);
      if (!box) return null;
      return { x: xOf((bar.start_min + bar.end_min) / 2, width), y: box.y - top + box.h / 2 };
    }
    function visibleLots(laid, top, height) {
      return laid.boxes.filter((box) => box.row.kind === "lot" && box.y + box.h >= top && box.y <= top + height).map((box) => box.row.id);
    }
    function drawNow(ctx, width, height) {
      const now = state.payload.now_min || 0;
      if (now < state.t0 || now > state.t1) return;
      const x = xOf(now, width);
      ctx.save();
      ctx.strokeStyle = "#c2410c";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
      ctx.restore();
    }
    function drawDue(ctx, width, height) {
      const bars = state.byLot.get(state.focus) || [];
      if (!bars.length || bars[0].due_min == null) return;
      const due = bars[0].due_min;
      if (due < state.t0 || due > state.t1) return;
      ctx.save();
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = "#b45309";
      const x = xOf(due, width);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
      ctx.restore();
    }
    function paintAxis(width) {
      const canvas = $(".tl-axis-canvas");
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(AXIS_H * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${AXIS_H}px`;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, width, AXIS_H);
      const step = chooseStep(span(), width);
      ctx.fillStyle = "#64748b";
      ctx.font = "11px sans-serif";
      ctx.textBaseline = "top";
      const c = copy();
      const shifts = [c.shiftA || "A", c.shiftB || "B", c.shiftC || "C"];
      for (let minute = Math.floor(state.t0 / 480) * 480; minute < state.t1; minute += 480) {
        if (minute < state.t0) continue;
        const slot = Math.floor((minute % 1440) / 480);
        ctx.fillStyle = "#94a3b8";
        ctx.fillText(shifts[((slot % 3) + 3) % 3], xOf(minute, width) + 4, 4);
      }
      ctx.fillStyle = "#1e293b";
      for (let minute = Math.ceil(state.t0 / step) * step; minute <= state.t1; minute += step) {
        const x = xOf(minute, width);
        ctx.strokeStyle = "#cbd5e1";
        ctx.beginPath();
        ctx.moveTo(x, 28);
        ctx.lineTo(x, AXIS_H);
        ctx.stroke();
        const label = Math.abs(minute - (state.payload.now_min || 0)) < 0.1 ? (c.now || "Now") : clock(minute, span() > 1440);
        ctx.fillText(label, Math.min(width - 64, x + 3), 28);
      }
    }
    function hit(event) {
      const canvas = $(".tl-bars");
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top + state.scroll;
      const laid = layout();
      const box = laid.boxes.find((item) => y >= item.y && y < item.y + item.h);
      if (!box || (box.row.kind !== "machine" && box.row.kind !== "lot")) return null;
      const minute = minuteOf(x, rect.width);
      const list = box.row.kind === "machine"
        ? (state.byMachine.get(box.row.id) || []).filter((bar) => !bar.gap)
        : (state.byLot.get(box.row.id) || []);
      for (let i = list.length - 1; i >= 0; i -= 1) {
        const bar = list[i];
        if (minute >= bar.start_min && minute <= bar.end_min) return { bar, box };
      }
      return { bar: null, box };
    }
    function showTip(event, bar) {
      const tip = $(".tl-tip");
      const c = copy();
      const rows = [
        [c.tipState || "", labelState(bar.state)],
        [c.tipLot || "", members(bar).join(", ")],
        [c.tipProduct || "", bar.product || ""],
        [c.tipMachine || "", bar.machine || ""],
        [c.tipStep || "", bar.step || ""],
        [c.tipRecipe || "", bar.recipe || "—"],
        [c.tipStart || "", clock(bar.start_min, true)],
        [c.tipEnd || "", clock(bar.end_min, true)],
        [c.tipDuration || "", duration(bar.end_min - bar.start_min)],
        [c.tipSetup || "", bar.setup_min ? duration(bar.setup_min) : "—"],
        [c.tipPriority || "", String(bar.priority)],
        [c.tipDue || "", clock(bar.due_min, true)],
        [c.tipLate || "", bar.late ? (c.lateLots || "") : (c.onTime || "")],
        [c.tipQtime || "", bar.qtime === "breach" ? (c.qtimeBreach || "") : bar.qtime === "risk" ? (c.qtimeRiskWord || "") : (c.qtimeOk || "")],
      ];
      tip.replaceChildren();
      const title = document.createElement("b");
      title.textContent = bar.lot;
      tip.appendChild(title);
      for (const [name, value] of rows) {
        const line = document.createElement("div");
        const dt = document.createElement("dt");
        dt.textContent = name;
        const dd = document.createElement("span");
        dd.textContent = value;
        line.append(dt, dd);
        tip.appendChild(line);
      }
      tip.hidden = false;
      const left = Math.min(event.clientX + 12, window.innerWidth - 300);
      const top = Math.min(event.clientY + 12, window.innerHeight - 240);
      tip.style.left = `${Math.max(8, left)}px`;
      tip.style.top = `${Math.max(8, top)}px`;
    }
    function hideTip() { $(".tl-tip").hidden = true; }
    function openMenu(event, bar) {
      event.preventDefault();
      const menu = $(".tl-menu");
      const lot = state.focus && members(bar).includes(state.focus) ? state.focus : bar.lot;
      menu.replaceChildren();
      const href = whyHref(state.payload, lot);
      if (href === null) {
        // No report covers the run on screen (a scenario/what-if book, or
        // the sample plant): a link would land on the baseline run's
        // evidence or on a 404. Say so in the menu instead of offering a
        // link that cannot resolve to this run.
        const note = document.createElement("div");
        note.className = "tl-menu-note";
        note.textContent = copy().whyUnavailable || WHY_UNAVAILABLE_FALLBACK;
        menu.appendChild(note);
      } else {
        const why = document.createElement("button");
        why.type = "button";
        why.textContent = `${copy().why || "なぜ？"} ${lot}`;
        why.addEventListener("click", () => {
          menu.hidden = true;
          if (opt.onWhy) opt.onWhy({ lot, href, bar });
          else window.location.assign(href);
        });
        menu.appendChild(why);
      }
      menu.hidden = false;
      menu.style.left = `${Math.min(event.clientX, window.innerWidth - 200)}px`;
      menu.style.top = `${Math.min(event.clientY, window.innerHeight - 80)}px`;
    }
    function zoomAt(factor, minute) {
      const horizon = (state.payload && state.payload.horizon_min) || 1440;
      const next = Math.min(horizon, Math.max(30, span() * factor));
      const ratio = (minute - state.t0) / span();
      state.t0 = minute - next * ratio;
      state.t1 = state.t0 + next;
      if (state.t0 < 0) { state.t1 -= state.t0; state.t0 = 0; }
      if (state.t1 > horizon) { state.t0 -= state.t1 - horizon; state.t1 = horizon; }
      if (state.t0 < 0) state.t0 = 0;
      draw();
      ensure();
    }
    function ensure() {
      const windowed = state.payload && state.payload.window;
      if (!windowed) return;
      if (state.t0 >= windowed.t0 && state.t1 <= windowed.t1) return;
      clearTimeout(state.timer);
      state.timer = setTimeout(load, 180);
    }
    function fit() {
      const bars = state.focus ? (state.byLot.get(state.focus) || []) : (state.payload && state.payload.bars) || [];
      if (!bars.length) return;
      state.t0 = Math.max(0, Math.min(...bars.map((bar) => bar.start_min)) - 10);
      state.t1 = Math.max(...bars.map((bar) => bar.end_min)) + 10;
      load();
    }
    function reset() {
      $(".tl-machine").value = "";
      $(".tl-lot").value = "";
      $(".tl-step").value = "";
      $(".tl-group-select").value = "";
      $(".tl-product-select").value = "";
      $(".tl-priority-select").value = "";
      $(".tl-start").value = "";
      $(".tl-end").value = "";
      $(".tl-lots").value = "100";
      $(".tl-idle").checked = false;
      state.focus = "";
      state.t0 = null;
      state.t1 = null;
      state.view = "machine";
      load();
    }
    function exportCsv() {
      const laid = layout();
      const ids = new Set(laid.boxes.map((box) => box.row.id));
      const bars = (state.payload.bars || []).concat(state.payload.gaps || []).filter((bar) => {
        if (bar.end_min <= state.t0 || bar.start_min >= state.t1) return false;
        if (state.view === "machine") return ids.has(bar.machine);
        return ids.has(bar.lot) || (bar.also || []).some((lot) => ids.has(lot));
      });
      const header = ["state", "lot", "product", "machine", "group", "step", "recipe", "start_min", "end_min", "duration_min", "setup_min", "priority", "due_min", "late", "qtime"];
      const lines = [header.join(",")];
      for (const bar of bars) {
        lines.push([
          bar.state, bar.lot, bar.product, bar.machine, bar.group, bar.step, bar.recipe,
          num(bar.start_min), num(bar.end_min), num(bar.end_min - bar.start_min), num(bar.setup_min),
          bar.priority, num(bar.due_min), bar.late ? "1" : "0", bar.qtime || "",
        ].map(csv).join(","));
      }
      download("timeline.csv", lines.join("\n"), "text/csv");
    }
    function exportPng() {
      scale.t0 = state.t0;
      scale.span = span();
      const width = trackW();
      const height = viewH();
      const laid = layout();
      const out = document.createElement("canvas");
      const dpr = 2;
      out.width = (LABEL_W + width) * dpr;
      out.height = (AXIS_H + height) * dpr;
      const ctx = out.getContext("2d");
      ctx.scale(dpr, dpr);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, LABEL_W + width, AXIS_H + height);
      ctx.save();
      ctx.translate(LABEL_W, AXIS_H);
      ctx.fillStyle = "#fafafa";
      ctx.fillRect(0, 0, width, height);
      drawGrid(ctx, width, height);
      for (const box of laid.boxes) {
        if (box.y + box.h < state.scroll || box.y > state.scroll + height) continue;
        const y = box.y - state.scroll;
        ctx.fillStyle = "#1e293b";
        ctx.font = "12px sans-serif";
        ctx.textBaseline = "middle";
        ctx.fillText(String(box.row.label || box.row.id), -LABEL_W + 8, y + box.h / 2);
        if (box.row.kind === "machine") drawMachine(ctx, box.row.id, y, box.h, width);
        else if (box.row.kind === "lot") drawLot(ctx, box.row.id, y, box.h, width);
      }
      drawNow(ctx, width, height);
      ctx.restore();
      out.toBlob((blob) => {
        if (!blob) return;
        const href = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = href;
        link.download = "timeline.png";
        link.click();
        URL.revokeObjectURL(href);
      });
    }
    function syncInputs() {
      const origin = state.payload && state.payload.origin;
      const active = document.activeElement;
      if (!origin || state.t0 == null) return;
      if (active === $(".tl-start") || active === $(".tl-end")) return;
      $(".tl-start").value = toInput(origin, state.t0);
      $(".tl-end").value = toInput(origin, state.t1);
    }
    function clock(minute, withDay) {
      const origin = state.payload && Date.parse(state.payload.origin);
      if (!Number.isFinite(origin)) return String(Math.round(minute));
      const date = new Date(origin + minute * 60000);
      const pad = (n) => String(n).padStart(2, "0");
      const hm = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
      if (!withDay) return hm;
      return `${date.getUTCMonth() + 1}/${date.getUTCDate()} ${hm}`;
    }
    function labelState(value) {
      const c = copy();
      return c[value] || value || "";
    }
    function setStatus(message, warn) {
      const node = $(".tl-status");
      text(node, message || "");
      node.className = warn ? "tl-status warn" : "tl-status";
    }
    function bind() {
      host.querySelectorAll("[data-lang]").forEach((button) => {
        button.addEventListener("click", () => {
          state.lang = button.getAttribute("data-lang");
          localStorage.setItem("resilimes.lang", state.lang);
          paint();
        });
      });
      host.querySelectorAll("[data-view]").forEach((input) => {
        input.addEventListener("change", () => {
          if (input.checked) { state.view = input.value; draw(); paint(); }
        });
      });
      $(".tl-refresh").addEventListener("click", () => { applyDates(); load(); });
      $(".tl-form").addEventListener("submit", (event) => { event.preventDefault(); applyDates(); load(); });
      $(".tl-reset").addEventListener("click", reset);
      $(".tl-fit").addEventListener("click", fit);
      $(".tl-zoom-in").addEventListener("click", () => zoomAt(0.7, state.t0 + span() / 2));
      $(".tl-zoom-out").addEventListener("click", () => zoomAt(1.4, state.t0 + span() / 2));
      $(".tl-png").addEventListener("click", exportPng);
      $(".tl-csv").addEventListener("click", exportCsv);
      $(".tl-links").addEventListener("change", () => { state.links = $(".tl-links").checked; draw(); });
      $(".tl-idle").addEventListener("change", load);
      $(".tl-fold").addEventListener("click", () => {
        state.filtersOpen = !state.filtersOpen;
        $(".tl-filters").classList.toggle("collapsed", !state.filtersOpen);
        paint();
      });
      const scroll = $(".tl-scroll");
      scroll.addEventListener("scroll", () => { state.scroll = scroll.scrollTop; draw(); });
      const canvas = $(".tl-bars");
      canvas.addEventListener("wheel", (event) => {
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        const rect = canvas.getBoundingClientRect();
        zoomAt(Math.exp(event.deltaY * 0.0015), minuteOf(event.clientX - rect.left, rect.width));
      }, { passive: false });
      canvas.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        state.drag = { x: event.clientX, t0: state.t0, t1: state.t1, moved: false };
        canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (state.drag) {
          const dx = event.clientX - state.drag.x;
          if (Math.abs(dx) > 3) state.drag.moved = true;
          const delta = (dx / trackW()) * span();
          state.t0 = state.drag.t0 - delta;
          state.t1 = state.drag.t1 - delta;
          draw();
          return;
        }
        const found = hit(event);
        if (found && found.bar) showTip(event, found.bar);
        else hideTip();
      });
      canvas.addEventListener("pointerup", (event) => {
        const drag = state.drag;
        state.drag = null;
        if (drag && drag.moved) { ensure(); return; }
        const found = hit(event);
        if (found && found.bar) {
          state.focus = found.bar.lot;
          draw();
          paintStats();
        }
      });
      canvas.addEventListener("pointerleave", hideTip);
      canvas.addEventListener("contextmenu", (event) => {
        const found = hit(event);
        if (found && found.bar) openMenu(event, found.bar);
      });
      $(".tl-axis-canvas").addEventListener("pointerdown", (event) => {
        state.drag = { x: event.clientX, t0: state.t0, t1: state.t1, moved: true };
        event.currentTarget.setPointerCapture(event.pointerId);
      });
      $(".tl-axis-canvas").addEventListener("pointermove", (event) => {
        if (!state.drag) return;
        const delta = ((event.clientX - state.drag.x) / trackW()) * span();
        state.t0 = state.drag.t0 - delta;
        state.t1 = state.drag.t1 - delta;
        draw();
      });
      $(".tl-axis-canvas").addEventListener("pointerup", () => { state.drag = null; ensure(); });
      document.addEventListener("pointerdown", (event) => {
        if (!event.target.closest(".tl-menu")) $(".tl-menu").hidden = true;
      });
      host.addEventListener("keydown", (event) => {
        if (event.key === "ArrowLeft") zoomPan(-0.15);
        else if (event.key === "ArrowRight") zoomPan(0.15);
        else if (event.key === "+" || event.key === "=") zoomAt(0.8, state.t0 + span() / 2);
        else if (event.key === "-" || event.key === "_") zoomAt(1.25, state.t0 + span() / 2);
        else if (event.key === "Escape") $(".tl-menu").hidden = true;
      });
      window.addEventListener("resize", draw);
    }
    function zoomPan(fraction) {
      const delta = span() * fraction;
      state.t0 += delta;
      state.t1 += delta;
      if (state.t0 < 0) { state.t1 -= state.t0; state.t0 = 0; }
      draw();
      ensure();
    }
    state.filtersOpen = true;
    bind();
    if (state.view === "product") {
      const product = host.querySelector("[data-view='product']");
      if (product) product.checked = true;
    }
    fetch("/assets/i18n.json").then((response) => response.json()).then((catalog) => {
      state.catalog = catalog;
      paint();
      load();
    }).catch(() => load());
    return { reload: load };
  }

  function shell() {
    const root = document.createElement("div");
    root.className = "tl";
    root.tabIndex = 0;
    root.innerHTML = `
      <header class="tl-top">
        <div class="tl-brand"><a class="tl-home" href="/">ResiliMES</a><h1 class="tl-title">工程ガント</h1></div>
        <div class="tl-langs" role="group">
          <button type="button" data-lang="ja">日本語</button>
          <button type="button" data-lang="zh">中文</button>
          <button type="button" data-lang="en">English</button>
        </div>
      </header>
      <p class="tl-lead"></p>
      <div class="tl-toolbar">
        <div class="tl-group">
          <span class="tl-label tl-view-label"></span>
          <label><input type="radio" name="tl-view" data-view="machine" value="machine" checked> <span data-view-text="machine">装置別</span></label>
          <label><input type="radio" name="tl-view" data-view="product" value="product"> <span data-view-text="product">製品・ロット</span></label>
        </div>
        <div class="tl-sep"></div>
        <label class="tl-group"><input class="tl-links" type="checkbox"> <span class="tl-links-label"></span></label>
        <label class="tl-group"><input class="tl-idle" type="checkbox"> <span class="tl-idle-label"></span></label>
        <label class="tl-group"><input class="tl-lots tl-narrow" type="number" min="1" max="5000" value="100"> <span class="tl-lot-unit"></span></label>
        <div class="tl-actions">
          <button type="button" class="tl-btn tl-zoom-out"></button>
          <button type="button" class="tl-btn tl-zoom-in"></button>
          <button type="button" class="tl-btn tl-fit"></button>
          <button type="button" class="tl-btn primary tl-refresh"></button>
          <button type="button" class="tl-btn tl-reset"></button>
          <button type="button" class="tl-btn tl-png"></button>
          <button type="button" class="tl-btn tl-csv"></button>
        </div>
      </div>
      <form class="tl-filters tl-form">
        <button type="button" class="tl-fold"></button>
        <p class="tl-help"></p>
        <div class="tl-grid">
          <label class="tl-field"><span class="tl-field-machine"></span><input class="tl-machine" type="text"></label>
          <label class="tl-field"><span class="tl-field-group"></span><select class="tl-group-select"></select></label>
          <label class="tl-field"><span class="tl-field-lot"></span><input class="tl-lot" type="text"></label>
          <label class="tl-field"><span class="tl-field-step"></span><input class="tl-step" type="text"></label>
          <label class="tl-field"><span class="tl-field-product"></span><select class="tl-product-select"></select></label>
          <label class="tl-field"><span class="tl-field-priority"></span><select class="tl-priority-select"></select></label>
          <label class="tl-field"><span class="tl-field-start"></span><input class="tl-start" type="datetime-local"></label>
          <label class="tl-field"><span class="tl-field-end"></span><input class="tl-end" type="datetime-local"></label>
        </div>
      </form>
      <div class="tl-stats"></div>
      <div class="tl-daily"></div>
      <div class="tl-legend"></div>
      <p class="tl-selected"></p>
      <p class="tl-status" role="status"></p>
      <div class="tl-chart" role="application">
        <div class="tl-axis"><div class="tl-corner"></div><canvas class="tl-axis-canvas"></canvas></div>
        <div class="tl-scroll"><div class="tl-spacer"><div class="tl-pane"><div class="tl-labels"></div><canvas class="tl-bars"></canvas></div></div></div>
        <p class="tl-empty" hidden></p>
      </div>
      <div class="tl-tip" hidden></div>
      <div class="tl-menu" hidden></div>`;
    return root;
  }

  function indexBy(items, keyFn) {
    const map = new Map();
    for (const item of items) {
      const key = keyFn(item);
      const list = map.get(key);
      if (list) list.push(item);
      else map.set(key, [item]);
    }
    for (const list of map.values()) list.sort((a, b) => a.start_min - b.start_min);
    return map;
  }
  function dedupe(bars) {
    const seen = new Set();
    const out = [];
    for (const bar of bars) {
      if (seen.has(bar.id)) continue;
      seen.add(bar.id);
      out.push(bar);
    }
    return out;
  }
  function overlaps(list, t0, t1) {
    const found = [];
    for (const bar of list) {
      if (bar.end_min > t0 && bar.start_min < t1) found.push(bar);
      else if (bar.start_min >= t1) break;
    }
    return found;
  }
  function isMember(bar, lot) {
    return !!lot && (bar.lot === lot || (bar.also || []).includes(lot));
  }
  function members(bar) {
    return [bar.lot].concat(bar.also || []);
  }
  const scale = { t0: 0, span: 1 };
  function band(ctx, start, end, y, h, width, color, hatched) {
    const left = ((Math.max(start, scale.t0) - scale.t0) / scale.span) * width;
    const right = ((Math.min(end, scale.t0 + scale.span) - scale.t0) / scale.span) * width;
    const w = Math.max(1, right - left);
    ctx.save();
    ctx.globalAlpha = hatched ? 0.45 : 0.7;
    ctx.fillStyle = color;
    ctx.fillRect(left, y, w, h);
    if (hatched) hatchRect(ctx, left, y, w, h);
    ctx.restore();
  }
  function chooseStep(span, width) {
    for (const step of STEPS) if ((width / span) * step >= 72) return step;
    return STEPS[STEPS.length - 1];
  }
  function roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }
  function hatchRect(ctx, x, y, w, h) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.strokeStyle = "rgba(30,41,59,0.4)";
    ctx.beginPath();
    for (let offset = -h; offset < w; offset += 6) {
      ctx.moveTo(x + offset, y + h);
      ctx.lineTo(x + offset + h, y);
    }
    ctx.stroke();
    ctx.restore();
  }
  function duration(minutes) {
    const abs = Math.abs(minutes);
    const h = Math.floor(abs / 60);
    const m = Math.round(abs % 60);
    return h ? `${h}h ${m}m` : `${m}m`;
  }
  function num(value) { return (Math.round(value * 10) / 10).toFixed(1); }
  function csv(value) {
    const text = value == null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  }
  function download(name, body, type) {
    const blob = new Blob([body], { type });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = name;
    link.click();
    URL.revokeObjectURL(href);
  }
  function toInput(origin, minute) {
    const date = new Date(Date.parse(origin) + minute * 60000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  }
  function fromInput(origin, value) {
    if (!origin || !value) return null;
    const delta = Date.parse(`${value}Z`) - Date.parse(origin);
    return Number.isFinite(delta) ? delta / 60000 : null;
  }
  function fill(template, params) {
    let out = template || "";
    for (const [name, value] of Object.entries(params || {})) out = out.replaceAll(`{${name}}`, value == null ? "" : String(value));
    return out;
  }

  // Status line for what the page actually shows. The lot cap and the bar
  // limit both shrink the drawn bars, while the cards count the display
  // window, so a window that hides lots must say so instead of letting
  // the cards pass for the full picture. The lots sentence appears
  // whenever fewer lots are drawn than the window holds, whatever cut
  // them — not merely when the cap engaged, which can also fire while
  // nothing was hidden. Pure over (payload, copy) so node can test it.
  // Fallback English when the catalog lacks the key: a capped window
  // must never fail silent.
  const SCOPE_LOTS_FALLBACK =
    "Showing {shown} of {total} lots in this window. Counts cover this window; Skips counts the whole book.";
  function scopeNotice(payload, c) {
    const copy = c || {};
    const scope = (payload && payload.scope) || {};
    const parts = [];
    const shown = scope.lots_shown;
    const total = scope.lots_total;
    if (Number.isFinite(shown) && Number.isFinite(total) && shown < total) {
      parts.push(fill(copy.scopeLots || SCOPE_LOTS_FALLBACK, { shown, total }));
    }
    if (payload && payload.truncated) parts.push(copy.truncated || "");
    return parts.filter(Boolean).join(" ");
  }

  // The "why?" deep link into the evidence report. The report endpoints
  // read the baseline run only, so a link exists only for the baseline
  // family: the base book and its seed/horizon refinements (payload book
  // "base" or "timeline-<seed>-<h>"). Any other run — a scenario or
  // what-if book, or the sample plant — would land on another run's
  // evidence or on a 404, so there is no link. Pure over (payload, lot)
  // so node can test it; null means "no link exists".
  const WHY_UNAVAILABLE_FALLBACK =
    "No evidence report — reports cover the recorded baseline run only.";
  function whyHref(payload, lot) {
    if (!payload || payload.source !== "smt2020" || !lot) return null;
    const book = payload.book;
    if (book && book !== "base" && !book.startsWith("timeline-")) return null;
    const horizon = payload.horizon_h || 48;
    const seed = payload.seed || 1;
    return `/report?lot=${encodeURIComponent(lot)}&seed=${encodeURIComponent(seed)}&horizon_h=${encodeURIComponent(horizon)}`;
  }

  function statusFor(payload, c) {
    const scope = (payload && payload.scope) || {};
    const hidden =
      Number.isFinite(scope.lots_shown) &&
      Number.isFinite(scope.lots_total) &&
      scope.lots_shown < scope.lots_total;
    return {
      message: scopeNotice(payload, c),
      warn: Boolean(hidden || (payload && payload.truncated)),
    };
  }

  window.ResiliTimeline = { mount, scopeNotice, whyHref };
  const host = document.getElementById("timeline-app");
  if (host) mount(host);
})();
