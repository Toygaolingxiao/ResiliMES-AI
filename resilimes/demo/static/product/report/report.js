// Read-only report of one Evidence Schema bundle.
// Each statement shows its tier and sources. The content_hash is checked again
// by posting the same bundle back to /api/explain/report/verify.
(function () {
  const IDLE_REASON = "a tool was idle and the record has no cause (pin, gate or wake latency)";
  const state = {
    lang: localStorage.getItem("resilimes.lang") || "ja",
    catalog: null,
    payload: null,
    lots: [],
    rangeArmed: false,
  };

  const $ = (id) => document.getElementById(id);

  function copy() {
    return (state.catalog && (state.catalog[state.lang] || state.catalog.ja) || {}).report || {};
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

  const SEED_RANGE_FALLBACK = "Seed must be a whole number between {min} and {max}.";
  const HORIZON_RANGE_FALLBACK = "Run length must be greater than 0 and at most {max}.";

  // A number input's value is a string, and native validation never
  // reaches the screen on this page: the control reads as invalid to
  // assistive tech but the user sees nothing and the request still
  // fires. The page therefore checks each value against the domain
  // the server actually enforces and says so, visibly. The domains
  // differ per field: the seed is an integer in [min, max]; the
  // horizon is a float in (0, max] — fractional horizons are legal
  // (the Gantt deep-links carry them), so the horizon is not held
  // to the seed's integer rule.
  function rangeProblem(value, min, max) {
    if (value === "" || value === null || value === undefined) return true;
    const n = Number(value);
    if (!Number.isFinite(n) || !Number.isInteger(n)) return true;
    return n < min || n > max;
  }

  function horizonProblem(value, max) {
    if (value === "" || value === null || value === undefined) return true;
    const n = Number(value);
    if (!Number.isFinite(n)) return true;
    return n <= 0 || n > max;
  }

  function paintRangeError(inputId, errorId, template, problem, params) {
    const input = $(inputId);
    const error = $(errorId);
    if (!input || !error) return false;
    const bad = problem(input.value);
    input.classList.toggle("invalid", bad);
    if (bad) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
    error.hidden = !bad;
    if (bad) {
      const message = fill(template, params);
      // Rewrite only on change: the element is role="alert", and
      // re-setting identical text re-announces it on every keystroke.
      if (error.textContent !== message) text(error, message);
    } else if (error.textContent) {
      // Clear, don't just hide: aria-describedby still reads a
      // hidden element, so a stale message would keep describing
      // the field as wrong after it was fixed.
      text(error, "");
    }
    return bad;
  }

  // Returns the id of the first invalid input, or null when both
  // pass. Both errors are always painted: returning early on the
  // seed would leave a stale horizon message on screen.
  function paintRangeErrors() {
    const c = copy();
    const seed = $("seed");
    const horizon = $("horizon");
    const seedBad = paintRangeError(
      "seed", "seed-error", c.seedRange || SEED_RANGE_FALLBACK,
      (value) => rangeProblem(value, Number(seed.getAttribute("min")), Number(seed.getAttribute("max"))),
      { min: seed.getAttribute("min"), max: seed.getAttribute("max") },
    );
    const horizonBad = paintRangeError(
      "horizon", "horizon-error", c.horizonRange || HORIZON_RANGE_FALLBACK,
      (value) => horizonProblem(value, Number(horizon.getAttribute("max"))),
      { max: horizon.getAttribute("max") },
    );
    if (seedBad || horizonBad) state.rangeArmed = true;
    if (seedBad) return "seed";
    if (horizonBad) return "horizon";
    return null;
  }

  // Live repaint only once an error has been shown: painting on
  // every keystroke from the start would flash the alert while the
  // user is still clearing and retyping a field.
  function onRangeInput() {
    if (state.rangeArmed) paintRangeErrors();
  }

  function tierName(tier) {
    return copy()[tier] || tier;
  }

  function bucketName(key) {
    const buckets = copy().buckets || {};
    if (key === "lateness") return copy().lateness || key;
    if (key.startsWith("overrun.")) return buckets[key.slice("overrun.".length)] || key;
    return key;
  }

  function reasonText(reason) {
    if (!reason) return "";
    if (reason === IDLE_REASON) return (copy().reasons || {}).idleNoCause || reason;
    return reason;
  }

  function unitText(unit) {
    if (unit === "sec") return copy().seconds || unit;
    return unit || "";
  }

  function valueText(row) {
    if (row.value === null || row.value === undefined) return "";
    const unit = unitText(row.unit);
    return unit ? `${row.value} ${unit}` : String(row.value);
  }

  function paintChrome() {
    const c = copy();
    document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang;
    document.title = c.title || "説明報告書";
    text($("title"), c.title);
    const back = document.querySelector(".back");
    if (back) text(back, c.back || "ResiliMES");
    const importLink = document.getElementById("import-link");
    const imported = (state.catalog[state.lang] || {}).import || {};
    if (importLink) text(importLink, imported.link || "");
    text($("lead"), c.lead);
    text($("seed-label"), c.seed);
    text($("horizon-label"), c.horizon);
    text($("horizon-unit"), c.horizonUnit);
    text($("lot-label"), c.lot);
    text($("show"), c.show);
    text($("print"), c.print);
    text($("note"), c.slow);
    document.querySelectorAll("[data-lang]").forEach((button) => {
      button.setAttribute("aria-pressed", button.getAttribute("data-lang") === state.lang ? "true" : "false");
    });
    const selected = $("lot").value;
    fillLots(state.lots, selected);
    if (state.payload) {
      render(state.payload);
      checkHash(state.payload);
    }
    paintRangeErrors();
  }

  function setStatus(message, warn) {
    const node = $("status");
    text(node, message || "");
    node.className = warn ? "status warn" : "status";
  }

  function statementNode(row) {
    const block = el("section", "statement");
    const head = el("p");
    head.append(document.createTextNode(`${bucketName(row.key)}${valueText(row) ? "  " + valueText(row) : ""}`));
    head.append(el("span", `tier tier-${row.tier}`, tierName(row.tier)));
    block.appendChild(head);
    const sources = el("div", "sources");
    sources.append(el("span", "", (copy().sources || "") + ":"));
    const list = el("ul");
    const items = row.sources || [];
    if (!items.length) list.append(el("li", "", copy().none || ""));
    for (const source of items) list.append(el("li", "", source));
    sources.appendChild(list);
    block.appendChild(sources);
    if (row.tier === "unknown") {
      block.appendChild(el("p", "reason", `${copy().missing || ""}: ${reasonText(row.reason)}`));
    }
    return block;
  }

  function section(host, title, hint, rows) {
    host.appendChild(el("h2", "", title));
    if (hint) host.appendChild(el("p", "hint", hint));
    if (!rows.length) {
      host.appendChild(el("p", "hint", copy().none || ""));
      return;
    }
    for (const row of rows) host.appendChild(statementNode(row));
  }

  function render(payload) {
    const c = copy();
    const host = $("report");
    host.hidden = false;
    host.replaceChildren();
    const meta = el("dl", "meta");
    const kind = (payload.subject && payload.subject.kind) || "";
    const kindName = (c.kinds && c.kinds[kind]) || kind;
    const run = payload.run || {};
    const pairs = [
      [c.subject, `${kindName} ${payload.subject ? payload.subject.id : ""}`.trim()],
      [c.run, `seed ${run.seed} · ${payload.horizon_h} ${c.horizonUnit || "h"} · ${run.policy || ""}`],
      [c.schema, payload.schema_version || ""],
      [c.hashLabel, ""],
    ];
    for (const [name, value] of pairs) {
      meta.append(el("dt", "", name), el("dd", "", value));
    }
    const hash = el("p", "hash", payload.content_hash || "");
    meta.lastChild.appendChild(hash);
    host.appendChild(meta);

    const check = el("p", "status", c.checking || "");
    check.id = "check";
    host.appendChild(check);

    const coverage = el("ul", "coverage");
    const percent = (payload.coverage && payload.coverage.percent) || {};
    for (const tier of ["recorded", "attributed", "unknown"]) {
      coverage.append(el("li", `tier-${tier}`, `${tierName(tier)} ${percent[tier] ?? 0}%`));
    }
    host.appendChild(el("h2", "", c.coverage));
    host.appendChild(coverage);

    const byKey = new Map((payload.statements || []).map((row) => [row.key, row]));
    const take = (keys) => (keys || []).map((key) => byKey.get(key)).filter(Boolean);
    section(host, c.what, "", take(payload.sections && payload.sections.what));
    section(host, c.why, c.whyNote, take(payload.sections && payload.sections.why));
    const unknown = (payload.sections && payload.sections.unconfirmed) || [];
    section(host, c.unconfirmed, c.unconfirmedNote, unknown.map((row) => byKey.get(row.key)).filter(Boolean));

    const details = el("details");
    details.append(el("summary", "", c.canonical));
    details.append(el("pre", "canonical", payload.canonical || ""));
    host.appendChild(details);
  }

  async function checkHash(payload) {
    const node = $("check");
    if (!node || !payload || !payload.bundle) return;
    try {
      const response = await fetch("/api/explain/report/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload.bundle),
      });
      if (!response.ok) throw new Error(String(response.status));
      const body = await response.json();
      const match = body.verified && body.recomputed === payload.content_hash;
      text(node, match ? copy().verified : copy().mismatch);
      node.className = match ? "status" : "status warn";
    } catch (error) {
      text(node, fill(copy().error, { msg: error.message || error }));
      node.className = "status warn";
    }
  }

  function fillLots(lots, selected) {
    const select = $("lot");
    select.replaceChildren();
    for (const item of lots || []) {
      const label = item.late_sec == null
        ? item.lot
        : `${item.lot} · ${item.late_sec} ${copy().seconds || ""}`;
      const option = el("option", "", label);
      option.value = item.lot;
      if (item.lot === selected) option.selected = true;
      select.appendChild(option);
    }
  }

  async function loadReport(event) {
    if (event) event.preventDefault();
    const badField = paintRangeErrors();
    if (badField) {
      // Say the standing report was not updated, and move focus to
      // the field only when the user actually submitted the form —
      // a lot-change or a deep-link load must not steal focus from
      // what the user is doing.
      setStatus(copy().notUpdated || "Not updated.", true);
      if (event && event.type === "submit") $(badField).focus();
      return;
    }
    const c = copy();
    // Send the validated values in canonical form: "3.0" passes the
    // numeric check as 3, and the server's integer parser must see
    // "3", not the raw literal, or it 422s a value the page accepted.
    const seed = String(Number($("seed").value));
    const horizon = String(Number($("horizon").value));
    // A later Show or a lot change must use the lot on the form, not the old URL.
    const picked = event && $("lot").options.length ? $("lot").value : "";
    setStatus(c.loading);
    $("report").hidden = true;
    let lots;
    try {
      const response = await fetch(`/api/explain/report/lots?seed=${encodeURIComponent(seed)}&horizon_h=${encodeURIComponent(horizon)}`);
      if (!response.ok) throw new Error(String(response.status));
      lots = await response.json();
    } catch (error) {
      setStatus(fill(c.error, { msg: error.message || error }), true);
      return;
    }
    state.lots = lots.lots || [];
    const wanted = picked || new URLSearchParams(location.search).get("lot") || "";
    // A Gantt "why?" link names the lot even when it is not in the late list.
    if (wanted && !state.lots.some((item) => item.lot === wanted)) {
      state.lots = [{ lot: wanted, late_sec: null }, ...state.lots];
    }
    fillLots(state.lots, wanted);
    if (!state.lots.length) {
      setStatus(c.empty);
      return;
    }
    if (!$("lot").value) $("lot").selectedIndex = 0;
    const lot = $("lot").value;
    try {
      const response = await fetch(`/api/explain/report?lot=${encodeURIComponent(lot)}&seed=${encodeURIComponent(seed)}&horizon_h=${encodeURIComponent(horizon)}`);
      if (!response.ok) throw new Error(String(response.status));
      state.payload = await response.json();
    } catch (error) {
      setStatus(fill(c.error, { msg: error.message || error }), true);
      return;
    }
    const url = new URL(location.href);
    url.searchParams.set("seed", seed);
    url.searchParams.set("horizon_h", horizon);
    url.searchParams.set("lot", lot);
    history.replaceState(null, "", url);
    setStatus("");
    render(state.payload);
    checkHash(state.payload);
  }

  async function init() {
    const response = await fetch("/assets/i18n.json");
    state.catalog = await response.json();
    const params = new URLSearchParams(location.search);
    if (params.get("seed")) $("seed").value = params.get("seed");
    if (params.get("horizon_h")) $("horizon").value = params.get("horizon_h");
    paintChrome();
    $("pick").addEventListener("submit", loadReport);
    $("seed").addEventListener("input", onRangeInput);
    $("horizon").addEventListener("input", onRangeInput);
    $("print").addEventListener("click", () => window.print());
    $("lot").addEventListener("change", (event) => {
      if ($("lot").value) loadReport(event);
    });
    document.querySelectorAll("[data-lang]").forEach((button) => {
      button.addEventListener("click", () => {
        state.lang = button.getAttribute("data-lang");
        localStorage.setItem("resilimes.lang", state.lang);
        paintChrome();
      });
    });
    if (params.get("lot")) loadReport();
  }

  window.ResiliReport = { render, statementNode, rangeProblem, horizonProblem };
  init();
})();
