// Import one MES event log. The page says which evidence tier the file can
// reach, and shows the lateness report when the file is complete enough.
(function () {
  const IDLE_REASON = "a tool was idle and the record has no cause (pin, gate or wake latency)";
  const DUE_REASON = "the log has no due time";
  const state = { lang: localStorage.getItem("resilimes.lang") || "ja", catalog: null, result: null };
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
    text(document.querySelector(".back"), c.back);
    document.querySelectorAll("[data-lang]").forEach((button) => {
      button.setAttribute("aria-pressed", button.getAttribute("data-lang") === state.lang ? "true" : "false");
    });
    if (state.result) render(state.result);
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
    let contents;
    try {
      contents = await file.text();
    } catch (error) {
      text($("status"), fill(c.error, { msg: error.message || error }));
      $("status").className = "status warn";
      return;
    }
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
