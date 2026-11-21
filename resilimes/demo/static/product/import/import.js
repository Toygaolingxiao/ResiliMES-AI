// Import one MES event log. The page says which evidence tier the file can
// reach, and shows the lateness report when the file is complete enough.
(function () {
  const IDLE_REASON = "a tool was idle and the record has no cause (pin, gate or wake latency)";
  const DUE_REASON = "the log has no due time";
  const state = { lang: localStorage.getItem("resilimes.lang") || "ja", catalog: null, result: null, contents: null };
  const $ = (id) => document.getElementById(id);

  function langCopy() {
    return state.catalog[state.lang] || state.catalog.ja || {};
  }
  function copy() {
    return langCopy().import || {};
  }
  function reportCopy() {
    return langCopy().report || {};
  }

  function text(node, value) {
    node.textContent = value == null ? "" : String(value);
  }
  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) text(node, value);
    return node;
  }
  function fill(template, params) {
    let out = template || "";
    for (const [name, value] of Object.entries(params || {})) {
      out = out.replaceAll("{" + name + "}", value == null ? "" : String(value));
    }
    return out;
  }

  function paintChrome() {
    const c = copy();
    document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang;
    document.title = c.title || "イベントログの取り込み";
    text($("title"), c.title);
    text($("lead"), c.lead);
    text($("format"), c.format);
    text($("file-label"), c.file);
    text($("submit"), c.submit);
    text(document.querySelector(".back"), c.back || "Back to the console");
    const table = langCopy();
    const peers = {
      timeline: (table.timeline && table.timeline.link) || "Timeline",
      report: (table.report && table.report.link) || "Report",
      import: c.link || "Import",
    };
    document.querySelectorAll("[data-nav]").forEach((node) => {
      const key = node.getAttribute("data-nav");
      text(node, peers[key] || "");
    });
    document.querySelectorAll("[data-lang]").forEach((button) => {
      button.setAttribute("aria-pressed", button.getAttribute("data-lang") === state.lang ? "true" : "false");
    });
    if (state.result) render(state.result);
    if (state.contents) renderContents();
  }

  function tierName(tier) {
    return reportCopy()[tier] || tier;
  }
  function bucketName(key) {
    const report = reportCopy();
    const buckets = report.buckets || {};
    const bare = key.includes(":") ? key.slice(key.indexOf(":") + 1) : key;
    const lot = key.includes(":") ? `${key.slice(0, key.indexOf(":"))} ` : "";
    let name = bare;
    if (bare === "lateness" || bare.startsWith("lateness.")) name = report.lateness || bare;
    else if (bare.startsWith("overrun.")) name = buckets[bare.slice("overrun.".length)] || bare;
    return `${lot}${name}`;
  }
  function reasonText(reason) {
    const reasons = reportCopy().reasons || {};
    if (reason === IDLE_REASON) return reasons.idleNoCause || reason;
    if (reason === DUE_REASON) return copy().noDue || reason;
    return reason || "";
  }

  function statementNode(row) {
    const block = el("section", "statement");
    const head = el("p");
    const report = reportCopy();
    const unit = row.unit === "sec" ? report.seconds || row.unit : row.unit || "";
    const value = row.value === null || row.value === undefined ? "" : unit ? `${row.value} ${unit}` : String(row.value);
    head.append(document.createTextNode(`${bucketName(row.key)}${value ? "  " + value : ""}`));
    head.append(el("span", `tier tier-${row.tier}`, tierName(row.tier)));
    block.appendChild(head);
    const sources = el("div", "sources");
    sources.append(el("span", "", `${report.sources || ""}:`));
    const list = el("ul");
    const items = row.sources || [];
    if (!items.length) list.append(el("li", "", report.none || ""));
    for (const source of items) list.append(el("li", "", source));
    sources.appendChild(list);
    block.appendChild(sources);
    if (row.tier === "unknown") {
      block.appendChild(el("p", "reason", `${report.missing || ""}: ${reasonText(row.reason)}`));
    }
    return block;
  }

  function render(result) {
    const c = copy();
    const host = $("result");
    host.hidden = false;
    host.replaceChildren();
    const ceilingText = {
      recorded: c.ceilingRecorded,
      attributed: c.ceilingAttributed,
      unknown: c.ceilingUnknown,
    }[result.ceiling] || result.ceiling;
    host.appendChild(el("h2", "", c.ceiling));
    host.appendChild(el("p", `tier tier-${result.ceiling}`, ceilingText));
    const meta = el("dl", "meta");
    const pairs = [
      [c.rows, String(result.rows ?? 0)],
      [c.decisions, String(result.decision_rows ?? 0)],
    ];
    for (const [name, value] of pairs) meta.append(el("dt", "", name), el("dd", "", value));
    host.appendChild(meta);
    if ((result.missing || []).length) {
      host.appendChild(el("h2", "", c.missing));
      const list = el("ul");
      for (const item of result.missing) list.append(el("li", "", item));
      host.appendChild(list);
    }
    if ((result.unrecognised || []).length) {
      host.appendChild(el("h2", "", c.unrecognised));
      const list = el("ul");
      for (const item of result.unrecognised) list.append(el("li", "", item));
      host.appendChild(list);
    }
    const report = result.report;
    if (!report) return;
    host.appendChild(el("h2", "", c.reportTitle));
    host.appendChild(el("p", "hash", report.content_hash || ""));
    const percent = (report.coverage && report.coverage.percent) || {};
    const coverage = el("ul", "coverage");
    for (const tier of ["recorded", "attributed", "unknown"]) {
      coverage.append(el("li", `tier-${tier}`, `${tierName(tier)} ${percent[tier] ?? 0}%`));
    }
    host.appendChild(coverage);
    for (const row of report.statements || []) host.appendChild(statementNode(row));
  }

  // The dropped file itself, parsed in the browser so the reader can see
  // what was actually in it — not only the verdict the import returned.
  const MAX_SHOWN = 100;
  const MAX_CELL = 120;

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let field = "";
    let quoted = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (quoted) {
        if (ch === '"') {
          if (text[i + 1] === '"') {
            field += '"';
            i++;
          } else quoted = false;
        } else field += ch;
      } else if (ch === '"') quoted = true;
      else if (ch === ",") {
        row.push(field);
        field = "";
      } else if (ch === "\n") {
        row.push(field);
        field = "";
        rows.push(row);
        row = [];
      } else if (ch !== "\r") field += ch;
    }
    if (field !== "" || row.length) {
      row.push(field);
      rows.push(row);
    }
    return rows;
  }

  function cellText(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function tableFromObjects(items) {
    const columns = [];
    for (const item of items.slice(0, 200)) {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        for (const key of Object.keys(item)) {
          if (!columns.includes(key)) columns.push(key);
        }
      }
    }
    if (!columns.length) return null;
    const rows = items.map((item) =>
      columns.map((key) => cellText(item && typeof item === "object" ? item[key] : null))
    );
    return { columns, rows };
  }

  function parseContents(text) {
    const trimmed = text.trim();
    if (!trimmed) return null;
    if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
      try {
        const data = JSON.parse(trimmed);
        return tableFromObjects(Array.isArray(data) ? data : [data]);
      } catch (error) {
        // Not one JSON document; try JSON lines before CSV.
        try {
          const items = trimmed
            .split(/\r?\n/)
            .filter((line) => line.trim())
            .map((line) => JSON.parse(line));
          const table = tableFromObjects(items);
          if (table) return table;
        } catch (lineError) {
          // Not JSON lines either; fall through to CSV.
        }
      }
    }
    const rows = parseCsv(text).filter(
      (row) => row.length > 1 || (row.length === 1 && row[0] !== "")
    );
    if (rows.length < 2) return null;
    return { columns: rows[0], rows: rows.slice(1) };
  }

  function renderContents() {
    const c = copy();
    const host = $("contents");
    host.replaceChildren();
    if (!state.contents) {
      host.hidden = true;
      return;
    }
    host.hidden = false;
    host.appendChild(el("h2", "", c.contentsTitle));
    const table = state.contents.table;
    if (!table) {
      host.appendChild(el("p", "reason", c.contentsUnparsed));
      return;
    }
    const shown = Math.min(table.rows.length, MAX_SHOWN);
    host.appendChild(
      el("p", "hash", fill(c.contentsMeta, { name: state.contents.name, total: table.rows.length, shown }))
    );
    const tableNode = el("table", "contents-table");
    const thead = el("thead");
    const headRow = el("tr");
    for (const column of table.columns) headRow.append(el("th", "", column));
    thead.appendChild(headRow);
    tableNode.appendChild(thead);
    const tbody = el("tbody");
    for (const row of table.rows.slice(0, MAX_SHOWN)) {
      const tr = el("tr");
      for (const value of row) {
        tr.append(el("td", "", value.length > MAX_CELL ? value.slice(0, MAX_CELL) + "…" : value));
      }
      tbody.appendChild(tr);
    }
    tableNode.appendChild(tbody);
    const wrap = el("div", "contents-wrap");
    wrap.appendChild(tableNode);
    host.appendChild(wrap);
  }

  async function submit(event) {
    event.preventDefault();
    const c = copy();
    const file = $("file").files && $("file").files[0];
    if (!file) {
      text($("status"), c.empty);
      return;
    }
    text($("status"), c.loading);
    $("result").hidden = true;
    $("contents").hidden = true;
    state.contents = null;
    let contents;
    try {
      contents = await file.text();
    } catch (error) {
      text($("status"), fill(c.error, { msg: error.message || error }));
      $("status").className = "status warn";
      return;
    }
    state.contents = { name: file.name, table: parseContents(contents) };
    renderContents();
    try {
      const response = await fetch("/api/explain/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: contents, filename: file.name }),
      });
      if (!response.ok) throw new Error(String(response.status));
      state.result = await response.json();
    } catch (error) {
      text($("status"), fill(c.error, { msg: error.message || error }));
      $("status").className = "status warn";
      return;
    }
    $("status").className = "status";
    text($("status"), "");
    render(state.result);
  }

  async function init() {
    const response = await fetch("/assets/i18n.json");
    state.catalog = await response.json();
    paintChrome();
    $("form").addEventListener("submit", submit);
    document.querySelectorAll("[data-lang]").forEach((button) => {
      button.addEventListener("click", () => {
        state.lang = button.getAttribute("data-lang");
        localStorage.setItem("resilimes.lang", state.lang);
        paintChrome();
      });
    });
  }
  init();
})();
