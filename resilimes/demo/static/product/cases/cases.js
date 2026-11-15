// Cases page: the lot-first follow-up list.
// Loaded after the run console so it can call the shared helpers.
//
// Data source (v0): a CaseBook JSON file exported by cases.py (to_json).
// There is no server endpoint yet — cases.py lives in unmerged PR #90 —
// so the page reads a file the user picks, validates it against the
// cases/v0 contract, and renders it read-only. The book stays in memory
// only; reloading the page unloads it.
//
// Read-only on purpose: changing a case would break its content_hash,
// and the seal is a SHA-256 over Python's canonical JSON. Recomputing
// it here would disagree on float formatting (30.0 vs 30) and report
// good seals as broken. Hashes are shown, not verified, on this page;
// seal checks run in cases.py (verify_all). Status changes, notes and
// persistence need the server endpoint; see docs/CASES_PAGE.md.
//
// The validator mirrors cases.py (from_json) as closely as a browser
// can: pydantic defaults and lax numeric coercion are accepted, and the
// payload is normalized (defaults filled, numeric strings coerced,
// lot/title/reason trimmed) before it is stored. Two deliberate
// divergences remain, both recorded in docs/CASES_PAGE.md: history
// transition legality is enforced here (from_json only checks the
// chain), and validation error details stay English field paths.

const CASES_VERSION = "cases/v0";
const CASES_SEVERITIES = ["critical", "major", "minor", "info"];
const CASES_SEVERITY_ORDER = { critical: 0, major: 1, minor: 2, info: 3 };
const CASES_STATUSES = ["open", "investigating", "resolved", "dismissed"];
const CASES_OPEN = ["open", "investigating"];
const CASES_TRANSITIONS = {
  open: ["investigating", "resolved", "dismissed"],
  investigating: ["open", "resolved", "dismissed"],
  resolved: ["open", "dismissed"],
  dismissed: ["open", "investigating"],
};
const CASES_HASH_RE = /^sha256:[0-9a-f]{64}$/;
const CASES_ID_RE = /^case-(\d+)$/;
const CASES_ISO_RE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/;
const CASES_NUMERIC_RE = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;
const CASES_MAX_ERRORS = 20;
const CASES_MAX_FILE_BYTES = 5 * 1024 * 1024;
const CASES_MAX_CASES_PER_LOT = 200;

const CASES_BOOK_KEYS = ["book_version", "cases", "next_seq"];
const CASES_CASE_KEYS = [
  "cases_version", "case_id", "lot", "run", "title", "severity",
  "severity_reason", "status", "lateness_min", "evidence_hash",
  "notes", "history", "created_at", "updated_at", "content_hash",
];
const CASES_RUN_KEYS = ["seed", "horizon_sec", "policy", "label", "sched_mode"];
const CASES_EVENT_KEYS = ["previous", "status", "at", "note"];

let casesBook = null;
let casesFileName = "";
let casesErrors = [];
let casesExpandedLots = new Set();
let casesStatusFilter = "all";
let casesLoadSeq = 0;

function casesCopy() {
  const copy = t();
  return (copy && copy.cases) || {};
}

// Every cases.* string falls back to the English label before "".
function casesText(key) {
  const copy = casesCopy();
  if (typeof copy[key] === "string" && copy[key]) return copy[key];
  const en = ((COPY.en || {}).cases || {})[key];
  return typeof en === "string" ? en : "";
}

function casesLabel(severityOrStatus, group) {
  const copy = casesCopy();
  const table = (copy && copy[group]) || {};
  if (typeof table[severityOrStatus] === "string" && table[severityOrStatus]) {
    return table[severityOrStatus];
  }
  // Missing key falls back to the English label, never to the raw key.
  const en = ((COPY.en || {}).cases || {})[group] || {};
  if (typeof en[severityOrStatus] === "string" && en[severityOrStatus]) {
    return en[severityOrStatus];
  }
  return severityOrStatus;
}

// Single-pass placeholder expansion: a value containing "{total}" must
// not be re-expanded by a later placeholder (e.g. a file named so).
function casesFill(template, params) {
  const known = params || {};
  return String(template || "").replace(/\{(\w+)\}/g, (match, name) => (
    Object.prototype.hasOwnProperty.call(known, name)
      ? String(known[name] == null ? "" : known[name])
      : match
  ));
}

function casesIsPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// Parse an ISO 8601 timestamp with a timezone, or null. Accepts the
// forms pydantic's fromisoformat accepts (space separator, optional
// seconds, +HHMM offsets) and rejects impossible calendar dates.
// Component ranges are checked directly: Date.parse alone rolls
// 2026-02-30 over to March 2, so it cannot be trusted for validity.
function casesDaysInMonth(year, month) {
  if (month === 2) return (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)) ? 29 : 28;
  return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

function casesParseIso(value) {
  if (typeof value !== "string") return null;
  const match = CASES_ISO_RE.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute, second, , tz] = match;
  const y = Number(year);
  const mo = Number(month);
  const d = Number(day);
  const h = Number(hour);
  const mi = Number(minute);
  const s = Number(second || 0);
  if (mo < 1 || mo > 12 || d < 1 || d > casesDaysInMonth(y, mo)) return null;
  if (h > 23 || mi > 59 || s > 59) return null;
  if (tz !== "Z") {
    const off = /^([+-])(\d{2}):?(\d{2})$/.exec(tz);
    if (!off || Number(off[2]) > 23 || Number(off[3]) > 59) return null;
  }
  let norm = value.replace(" ", "T");
  if (second === undefined) norm = norm.replace(/([+-]\d{2}:?\d{2}|Z)$/, ":00$1");
  norm = norm.replace(/([+-])(\d{2})(\d{2})$/, "$1$2:$3");
  const date = new Date(norm);
  return Number.isNaN(date.getTime()) ? null : date;
}

function casesIsIso(value) {
  return casesParseIso(value) !== null;
}

function casesToNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && CASES_NUMERIC_RE.test(value.trim())) {
    const num = Number(value.trim());
    if (Number.isFinite(num)) return num;
  }
  return null;
}

function casesCheckKeys(obj, allowed, where, errors) {
  for (const key of Object.keys(obj)) {
    if (!allowed.includes(key)) errors.push(`${where}: unknown key ${JSON.stringify(key)}`);
  }
}

function casesCheckRun(run, where, errors) {
  if (!casesIsPlainObject(run)) {
    errors.push(`${where}: run must be an object`);
    return;
  }
  casesCheckKeys(run, CASES_RUN_KEYS, `${where}.run`, errors);
  if (run.seed === undefined) {
    errors.push(`${where}.run.seed: must be an integer`);
  } else if (casesToNumber(run.seed) === null) {
    errors.push(`${where}.run.seed: must be a finite number`);
  } else if (!Number.isInteger(casesToNumber(run.seed))) {
    errors.push(`${where}.run.seed: must be an integer`);
  }
  if (run.horizon_sec === undefined) {
    errors.push(`${where}.run.horizon_sec: must be a finite number`);
  } else if (casesToNumber(run.horizon_sec) === null) {
    errors.push(`${where}.run.horizon_sec: must be a finite number`);
  }
  if (run.policy === undefined || typeof run.policy !== "string") {
    errors.push(`${where}.run.policy: must be a string`);
  }
  if (run.label !== undefined && typeof run.label !== "string") {
    errors.push(`${where}.run.label: must be a string`);
  }
  if (run.sched_mode !== undefined && run.sched_mode !== null && typeof run.sched_mode !== "string") {
    errors.push(`${where}.run.sched_mode: must be a string or null`);
  }
}

function casesCheckHistory(history, status, where, errors) {
  if (!Array.isArray(history)) {
    errors.push(`${where}.history: must be an array`);
    return;
  }
  if (!history.length) {
    if (status !== "open") errors.push(`${where}: a case with no history must be open`);
    return;
  }
  let previous = null;
  history.forEach((event, index) => {
    const at = `${where}.history[${index}]`;
    if (!casesIsPlainObject(event)) {
      errors.push(`${at}: must be an object`);
      return;
    }
    casesCheckKeys(event, CASES_EVENT_KEYS, at, errors);
    const prev = event.previous === undefined ? null : event.previous;
    if (index === 0 && (prev !== null || event.status !== "open")) {
      errors.push(`${where}.history: must start with the creation event (previous null, open)`);
    }
    if (prev !== previous) {
      errors.push(`${at}.previous: ${JSON.stringify(prev)} does not follow ${JSON.stringify(previous)}`);
    }
    if (!CASES_STATUSES.includes(event.status)) {
      errors.push(`${at}.status: unknown status ${JSON.stringify(event.status)}`);
    }
    if (!casesIsIso(event.at)) errors.push(`${at}.at: must be an ISO 8601 timestamp with a timezone`);
    if (event.note !== undefined && typeof event.note !== "string") {
      errors.push(`${at}.note: must be a string`);
    }
    // Deliberately stricter than from_json: the chain alone does not
    // prove the move was legal. A genuine to_json export can never
    // contain an illegal move (transition() enforces TRANSITIONS).
    if (index > 0 && CASES_STATUSES.includes(event.status)
      && !(CASES_TRANSITIONS[previous] || []).includes(event.status)) {
      errors.push(`${at}: illegal transition ${JSON.stringify(previous)} -> ${JSON.stringify(event.status)}`);
    }
    previous = event.status;
  });
  const last = history[history.length - 1];
  if (casesIsPlainObject(last) && last.status !== status) {
    errors.push(`${where}: history ends at ${JSON.stringify(last.status)} but status is ${JSON.stringify(status)}`);
  }
}

function casesCheckCase(item, where, seenIds, errors) {
  if (!casesIsPlainObject(item)) {
    errors.push(`${where}: must be an object`);
    return;
  }
  casesCheckKeys(item, CASES_CASE_KEYS, where, errors);
  if (item.cases_version !== undefined && item.cases_version !== CASES_VERSION) {
    errors.push(`${where}.cases_version: must be ${JSON.stringify(CASES_VERSION)}`);
  }
  if (typeof item.case_id !== "string" || !item.case_id.trim()) {
    errors.push(`${where}.case_id: must be a non-empty string`);
  } else if (seenIds.has(item.case_id)) {
    errors.push(`${where}.case_id: duplicate ${JSON.stringify(item.case_id)}`);
  } else {
    seenIds.add(item.case_id);
  }
  if (typeof item.lot !== "string" || !item.lot.trim()) {
    errors.push(`${where}.lot: must be a non-empty string`);
  }
  if (typeof item.title !== "string" || !item.title.trim() || /[\r\n]/.test(item.title)) {
    errors.push(`${where}.title: must be a non-empty single line`);
  }
  if (!CASES_SEVERITIES.includes(item.severity)) {
    errors.push(`${where}.severity: unknown severity ${JSON.stringify(item.severity)}`);
  }
  if (typeof item.severity_reason !== "string" || !item.severity_reason.trim()) {
    errors.push(`${where}.severity_reason: must be a non-empty string`);
  }
  const status = item.status === undefined ? "open" : item.status;
  if (!CASES_STATUSES.includes(status)) {
    errors.push(`${where}.status: unknown status ${JSON.stringify(status)}`);
  }
  const lateness = item.lateness_min === undefined ? null : item.lateness_min;
  if (lateness !== null && casesToNumber(lateness) === null) {
    errors.push(`${where}.lateness_min: must be null or a finite number`);
  } else if (lateness !== null && casesToNumber(lateness) < 0) {
    errors.push(`${where}.lateness_min: must be >= 0`);
  }
  if (item.evidence_hash !== undefined && item.evidence_hash !== null && !CASES_HASH_RE.test(item.evidence_hash)) {
    errors.push(`${where}.evidence_hash: must be sha256:<64 lowercase hex chars> or null`);
  }
  if (item.notes !== undefined) {
    if (!Array.isArray(item.notes) || item.notes.some((n) => typeof n !== "string" || !n.trim())) {
      errors.push(`${where}.notes: must be an array of non-empty strings`);
    }
  }
  if (item.content_hash !== undefined && typeof item.content_hash !== "string") {
    errors.push(`${where}.content_hash: must be a string`);
  }
  if (!casesIsIso(item.created_at)) {
    errors.push(`${where}.created_at: must be an ISO 8601 timestamp with a timezone`);
  }
  if (!casesIsIso(item.updated_at)) {
    errors.push(`${where}.updated_at: must be an ISO 8601 timestamp with a timezone`);
  }
  casesCheckRun(item.run, where, errors);
  casesCheckHistory(item.history === undefined ? [] : item.history, status, where, errors);
}

// Validate a parsed JSON value against the cases/v0 book contract.
// Returns a list of error strings; an empty list means the book is valid.
// Pydantic defaults are accepted (missing book_version / cases /
// next_seq / status / notes / history / label), as is lax numeric
// coercion ("45" for a number). The Python model stays authoritative;
// the two intentional divergences (history legality, error language)
// are recorded in docs/CASES_PAGE.md.
function validateCaseBook(payload) {
  const errors = [];
  if (!casesIsPlainObject(payload)) return ["book: must be a JSON object"];
  casesCheckKeys(payload, CASES_BOOK_KEYS, "book", errors);
  if (payload.book_version !== undefined && payload.book_version !== CASES_VERSION) {
    errors.push(`book.book_version: must be ${JSON.stringify(CASES_VERSION)}`);
  }
  const cases = payload.cases === undefined ? [] : payload.cases;
  if (!Array.isArray(cases)) {
    errors.push("book.cases: must be an array");
    return errors;
  }
  const nextSeq = payload.next_seq === undefined ? 1 : payload.next_seq;
  if (!Number.isInteger(nextSeq) || nextSeq < 1) {
    errors.push("book.next_seq: must be an integer >= 1");
  }
  const seenIds = new Set();
  cases.forEach((item, index) => {
    casesCheckCase(item, `cases[${index}]`, seenIds, errors);
  });
  if (Number.isInteger(nextSeq)) {
    let highest = 0;
    for (const item of cases) {
      if (casesIsPlainObject(item) && typeof item.case_id === "string") {
        const match = CASES_ID_RE.exec(item.case_id);
        if (match) highest = Math.max(highest, Number(match[1]));
      }
    }
    if (highest && nextSeq <= highest) {
      errors.push(`book.next_seq: must be above the highest case number ${highest}`);
    }
  }
  return errors;
}

// Normalize a validated payload the way pydantic does: fill defaults,
// coerce numeric strings, trim the three stripped text fields. Returns
// a new object; the caller's payload is untouched.
function normalizeCaseBook(payload) {
  const book = JSON.parse(JSON.stringify(payload));
  if (book.book_version === undefined) book.book_version = CASES_VERSION;
  if (!Array.isArray(book.cases)) book.cases = [];
  if (book.next_seq === undefined) book.next_seq = 1;
  for (const item of book.cases) {
    if (item.cases_version === undefined) item.cases_version = CASES_VERSION;
    if (typeof item.lot === "string") item.lot = item.lot.trim();
    if (typeof item.title === "string") item.title = item.title.trim();
    if (typeof item.severity_reason === "string") item.severity_reason = item.severity_reason.trim();
    if (item.status === undefined) item.status = "open";
    if (item.lateness_min !== undefined && item.lateness_min !== null) {
      item.lateness_min = casesToNumber(item.lateness_min);
    }
    if (item.lateness_min === undefined) item.lateness_min = null;
    if (item.evidence_hash === undefined) item.evidence_hash = null;
    if (!Array.isArray(item.notes)) item.notes = [];
    if (!Array.isArray(item.history)) item.history = [];
    if (item.content_hash === undefined) item.content_hash = "";
    if (casesIsPlainObject(item.run)) {
      if (item.run.seed !== undefined) item.run.seed = casesToNumber(item.run.seed);
      if (item.run.horizon_sec !== undefined) item.run.horizon_sec = casesToNumber(item.run.horizon_sec);
      if (item.run.label === undefined) item.run.label = "baseline";
      if (item.run.sched_mode === undefined) item.run.sched_mode = null;
    }
    for (const event of item.history) {
      if (casesIsPlainObject(event)) {
        if (event.previous === undefined) event.previous = null;
        if (event.note === undefined) event.note = "";
      }
    }
  }
  return book;
}

function casesSummary(book) {
  const byStatus = Object.fromEntries(CASES_STATUSES.map((s) => [s, 0]));
  const bySeverity = Object.fromEntries(CASES_SEVERITIES.map((s) => [s, 0]));
  for (const item of book.cases) {
    const status = item.status || "open";
    if (byStatus[status] !== undefined) byStatus[status] += 1;
    if (bySeverity[item.severity] !== undefined) bySeverity[item.severity] += 1;
  }
  return {
    total: book.cases.length,
    lots: new Set(book.cases.map((item) => item.lot)).size,
    openTotal: book.cases.filter((item) => CASES_OPEN.includes(item.status || "open")).length,
    byStatus,
    bySeverity,
  };
}

function casesCompareStr(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

// Mirror _case_id_key: numeric order for book-assigned ids
// (case-9999 before case-10000); anything else sorts after, by string.
function casesCompareCaseId(a, b) {
  const ma = CASES_ID_RE.exec(String(a));
  const mb = CASES_ID_RE.exec(String(b));
  if (ma && mb) return Number(ma[1]) - Number(mb[1]);
  if (ma) return -1;
  if (mb) return 1;
  return casesCompareStr(String(a), String(b));
}

function casesSortCases(items) {
  return items.slice().sort((a, b) => (
    CASES_SEVERITY_ORDER[a.severity] - CASES_SEVERITY_ORDER[b.severity]
    || casesParseIso(a.created_at) - casesParseIso(b.created_at)
    || casesCompareCaseId(a.case_id, b.case_id)
  ));
}

// Mirror CaseBook.lots(): one row per lot, worst *open* severity first.
// A lot whose only critical case is resolved sorts behind lots with open
// major cases; lots with no open case sort last. Ties break by open
// count (more open first), then lot id (code-point order, like Python).
function casesLotRows(book) {
  const grouped = new Map();
  for (const item of book.cases) {
    const lot = item.lot;
    if (!grouped.has(lot)) grouped.set(lot, []);
    grouped.get(lot).push(item);
  }
  const rows = [];
  for (const [lot, items] of grouped) {
    const openItems = items.filter((item) => CASES_OPEN.includes(item.status || "open"));
    const sorted = casesSortCases(items);
    const sortedOpen = casesSortCases(openItems);
    const worstOpen = sortedOpen.length ? sortedOpen[0] : null;
    const latest = items.slice().sort((a, b) => casesParseIso(b.updated_at) - casesParseIso(a.updated_at))[0];
    rows.push({
      lot,
      total: items.length,
      openCount: openItems.length,
      worstOpenSeverity: worstOpen ? worstOpen.severity : null,
      worstOpenLateness: worstOpen ? worstOpen.lateness_min : null,
      latestUpdatedAt: latest.updated_at,
      cases: sorted,
    });
  }
  rows.sort((a, b) => (
    (a.worstOpenSeverity === null ? 1 : 0) - (b.worstOpenSeverity === null ? 1 : 0)
    || (a.worstOpenSeverity ? CASES_SEVERITY_ORDER[a.worstOpenSeverity] : 99)
      - (b.worstOpenSeverity ? CASES_SEVERITY_ORDER[b.worstOpenSeverity] : 99)
    || b.openCount - a.openCount
    || casesCompareStr(a.lot, b.lot)
  ));
  return rows;
}

// The visible subset under the status filter. "all" shows the whole
// book; otherwise only cases in that status, with lots re-derived from
// the subset so ordering and counts stay consistent.
function casesFilteredBook(book, filter) {
  if (!filter || filter === "all") return book;
  return { ...book, cases: book.cases.filter((item) => (item.status || "open") === filter) };
}

function casesEl(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value == null ? "" : String(value);
  return node;
}

function casesSeverityBadge(severity) {
  return casesEl("span", `sev sev-${severity}`, casesLabel(severity, "severity"));
}

function casesLatenessText(lateness) {
  if (lateness === null || lateness === undefined) return casesText("latenessUnknown");
  if (lateness > 0 && lateness < 1) return casesText("lessThanMinute");
  return formatDuration(lateness);
}

function casesHashCell(hash) {
  if (!hash) return casesEl("td", "mono", casesText("noHash"));
  const cell = casesEl("td", "mono");
  const shown = document.createElement("span");
  shown.textContent = `${String(hash).slice(0, 14)}…`;
  shown.title = String(hash);
  cell.appendChild(shown);
  return cell;
}

function casesRunCell(run) {
  const cell = casesEl("td", "mono");
  if (!casesIsPlainObject(run)) return cell;
  const parts = [`seed ${run.seed}`, `${run.policy}`];
  if (typeof run.horizon_sec === "number" && Number.isFinite(run.horizon_sec)) {
    const hours = run.horizon_sec / 3600;
    parts.push(`${Number.isInteger(hours) ? String(hours) : hours.toFixed(1)}h`);
  }
  if (run.label && run.label !== "baseline") parts.push(String(run.label));
  if (run.sched_mode) parts.push(String(run.sched_mode));
  cell.textContent = parts.join(" · ");
  return cell;
}

function casesDetailRow(item, columns) {
  const row = document.createElement("tr");
  row.className = "case-detail";
  const cell = casesEl("td");
  cell.colSpan = columns;
  if (item.severity_reason) {
    cell.appendChild(casesEl("p", "note-inline", item.severity_reason));
  }
  const facts = document.createElement("dl");
  facts.className = "case-facts";
  const addFact = (label, value) => {
    facts.appendChild(casesEl("dt", "", label));
    const dd = casesEl("dd", "mono", value);
    facts.appendChild(dd);
  };
  addFact(casesText("colCreated"), item.created_at || "");
  addFact(casesText("colEvidence"), item.evidence_hash || casesText("noHash"));
  addFact(casesText("colSeal"), item.content_hash || casesText("noHash"));
  cell.appendChild(facts);
  const notes = Array.isArray(item.notes) ? item.notes : [];
  cell.appendChild(casesEl("p", "case-subhead", casesText("colNotes")));
  if (notes.length) {
    const list = document.createElement("ul");
    list.className = "case-notes";
    for (const note of notes) {
      list.appendChild(casesEl("li", "", note));
    }
    cell.appendChild(list);
  } else {
    cell.appendChild(casesEl("p", "note-inline", casesText("noNotes")));
  }
  const history = Array.isArray(item.history) ? item.history : [];
  cell.appendChild(casesEl("p", "case-subhead", casesText("colHistory")));
  if (history.length) {
    const list = document.createElement("ol");
    list.className = "case-history";
    for (const event of history) {
      const from = event.previous === null || event.previous === undefined
        ? "—"
        : casesLabel(event.previous, "status");
      const line = `${from} → ${casesLabel(event.status, "status")} · ${event.at || ""}`;
      list.appendChild(casesEl("li", "", event.note ? `${line} · ${event.note}` : line));
    }
    cell.appendChild(list);
  } else {
    cell.appendChild(casesEl("p", "note-inline", casesText("noHistory")));
  }
  row.appendChild(cell);
  return row;
}

function casesLotTable(rows) {
  const table = casesEl("table", "compare");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const [label, klass] of [
    [casesText("colLot"), ""],
    [casesText("colWorstOpen"), ""],
    [casesText("colLateness"), "num"],
    [casesText("colOpen"), "num"],
    [casesText("colTotal"), "num"],
    [casesText("colUpdated"), ""],
    ["", ""],
  ]) {
    headRow.appendChild(casesEl("th", klass || undefined, label || ""));
  }
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.appendChild(casesEl("td", "mono", row.lot));
    const worstCell = document.createElement("td");
    if (row.worstOpenSeverity) worstCell.appendChild(casesSeverityBadge(row.worstOpenSeverity));
    else worstCell.textContent = "—";
    tr.appendChild(worstCell);
    tr.appendChild(casesEl("td", "num", casesLatenessText(row.worstOpenLateness)));
    tr.appendChild(casesEl("td", "num", row.openCount));
    tr.appendChild(casesEl("td", "num", row.total));
    tr.appendChild(casesEl("td", "mono", row.latestUpdatedAt));
    const toggleCell = document.createElement("td");
    const toggle = casesEl("button", "run quiet", casesFill(casesText("caseCount"), { n: row.total }));
    toggle.type = "button";
    toggle.dataset.lot = row.lot;
    const expanded = casesExpandedLots.has(row.lot);
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggle.addEventListener("click", () => {
      if (casesExpandedLots.has(row.lot)) casesExpandedLots.delete(row.lot);
      else casesExpandedLots.add(row.lot);
      paintCases();
    });
    toggleCell.appendChild(toggle);
    tr.appendChild(toggleCell);
    body.appendChild(tr);
    if (expanded) {
      const detail = document.createElement("tr");
      detail.className = "lot-detail";
      const cell = casesEl("td");
      cell.colSpan = 7;
      const inner = casesEl("table", "compare");
      const innerHead = document.createElement("thead");
      const innerHeadRow = document.createElement("tr");
      for (const [label, klass] of [
        [casesText("colCase"), ""],
        [casesText("colTitle"), ""],
        [casesText("colSeverity"), ""],
        [casesText("colStatus"), ""],
        [casesText("colLateness"), "num"],
        [casesText("colEvidence"), ""],
        [casesText("colRun"), ""],
      ]) {
        innerHeadRow.appendChild(casesEl("th", klass || undefined, label || ""));
      }
      innerHead.appendChild(innerHeadRow);
      inner.appendChild(innerHead);
      const innerBody = document.createElement("tbody");
      const shown = row.cases.slice(0, CASES_MAX_CASES_PER_LOT);
      for (const item of shown) {
        const caseRow = document.createElement("tr");
        caseRow.appendChild(casesEl("td", "mono", item.case_id));
        caseRow.appendChild(casesEl("td", "", item.title));
        const sevCell = document.createElement("td");
        sevCell.appendChild(casesSeverityBadge(item.severity));
        caseRow.appendChild(sevCell);
        caseRow.appendChild(casesEl("td", "", casesLabel(item.status || "open", "status")));
        caseRow.appendChild(casesEl("td", "num", casesLatenessText(item.lateness_min)));
        caseRow.appendChild(casesHashCell(item.evidence_hash));
        caseRow.appendChild(casesRunCell(item.run));
        innerBody.appendChild(caseRow);
        innerBody.appendChild(casesDetailRow(item, 7));
      }
      inner.appendChild(innerBody);
      cell.appendChild(inner);
      if (row.cases.length > CASES_MAX_CASES_PER_LOT) {
        cell.appendChild(casesEl("p", "note-inline", casesFill(casesText("capped"), {
          shown: CASES_MAX_CASES_PER_LOT,
          total: row.cases.length,
        })));
      }
      detail.appendChild(cell);
      body.appendChild(detail);
    }
  }
  table.appendChild(body);
  return table;
}

function casesSummaryLine(summary) {
  return casesEl("p", "note-inline", casesFill(casesText("summary"), {
    total: summary.total,
    lots: summary.lots,
    open: summary.openTotal,
  }));
}

function casesBreakdown(summary) {
  const parts = [];
  for (const status of CASES_STATUSES) {
    parts.push(`${casesLabel(status, "status")} ${summary.byStatus[status] || 0}`);
  }
  const byStatus = casesEl("p", "note-inline", parts.join(" · "));
  const sevParts = [];
  for (const severity of CASES_SEVERITIES) {
    sevParts.push(`${casesLabel(severity, "severity")} ${summary.bySeverity[severity] || 0}`);
  }
  const bySeverity = casesEl("p", "note-inline", sevParts.join(" · "));
  return [byStatus, bySeverity];
}

function casesFilterRow() {
  const row = casesEl("div", "filter-row");
  row.appendChild(casesEl("span", "", casesText("filterBy")));
  const options = ["all", ...CASES_STATUSES];
  for (const option of options) {
    const button = casesEl("button", "run quiet", option === "all"
      ? casesText("filterAll")
      : casesLabel(option, "status"));
    button.type = "button";
    button.setAttribute("aria-pressed", casesStatusFilter === option ? "true" : "false");
    button.addEventListener("click", () => {
      casesStatusFilter = option;
      paintCases();
    });
    row.appendChild(button);
  }
  return row;
}

async function casesLoadFile(file) {
  const mySeq = ++casesLoadSeq;
  if (file.size > CASES_MAX_FILE_BYTES) {
    casesBook = null;
    casesFileName = "";
    casesErrors = [casesFill(casesText("fileTooLarge"), { mb: (file.size / 1048576).toFixed(1) })];
    paintCases();
    return;
  }
  let text = "";
  try {
    text = await file.text();
  } catch (error) {
    if (mySeq !== casesLoadSeq) return;
    casesBook = null;
    casesFileName = "";
    casesErrors = [casesFill(casesText("invalidJson"), { reason: String((error && error.message) || error) })];
    paintCases();
    return;
  }
  if (mySeq !== casesLoadSeq) return;
  let payload = null;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    casesBook = null;
    casesFileName = "";
    casesErrors = [casesFill(casesText("invalidJson"), { reason: String((error && error.message) || error) })];
    paintCases();
    return;
  }
  const errors = validateCaseBook(payload);
  if (errors.length) {
    casesBook = null;
    casesFileName = "";
    casesErrors = errors;
    paintCases();
    return;
  }
  casesBook = normalizeCaseBook(payload);
  casesFileName = file.name || "";
  casesErrors = [];
  casesExpandedLots = new Set();
  paintCases();
}

function paintCases() {
  const host = document.getElementById("panel-cases");
  if (!host) return;
  // Rebuilding the panel drops scroll and focus; keep both so expanding
  // a lot far down the list does not throw the reader back to the top.
  const savedScroll = host.scrollTop;
  const active = document.activeElement;
  const activeLot = active && host.contains(active) && active.dataset ? active.dataset.lot : null;
  host.innerHTML = "";
  const wrap = casesEl("div", "cases");
  const loadCard = casesEl("article", "card wide");
  loadCard.appendChild(cardHead(casesText("title"), casesText("lead")));
  const fileRow = casesEl("div", "file-row");
  const label = casesEl("label", "", casesText("loadFile"));
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json,application/json";
  input.id = "cases-file";
  label.htmlFor = "cases-file";
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (file) casesLoadFile(file);
  });
  fileRow.append(label, input);
  if (casesBook) {
    const unload = casesEl("button", "run quiet", casesText("unload"));
    unload.type = "button";
    unload.addEventListener("click", () => {
      casesBook = null;
      casesFileName = "";
      casesErrors = [];
      casesExpandedLots = new Set();
      const picker = document.getElementById("cases-file");
      if (picker) picker.value = "";
      paintCases();
    });
    fileRow.appendChild(unload);
  }
  loadCard.appendChild(fileRow);
  loadCard.appendChild(casesEl("p", "note-inline", casesText("loadHint")));
  if (casesBook) {
    const summary = casesSummary(casesBook);
    loadCard.appendChild(casesEl("p", "note-inline", casesFill(casesText("loaded"), {
      name: casesFileName,
      total: summary.total,
      lots: summary.lots,
    })));
  }
  loadCard.appendChild(casesEl("p", "note-inline", casesText("sealNote")));
  wrap.appendChild(loadCard);

  if (casesErrors.length) {
    const errorCard = casesEl("article", "card wide");
    errorCard.appendChild(cardHead(casesText("fileError"), ""));
    const list = document.createElement("ul");
    list.className = "case-errors";
    for (const error of casesErrors.slice(0, CASES_MAX_ERRORS)) {
      list.appendChild(casesEl("li", "mono", error));
    }
    errorCard.appendChild(list);
    if (casesErrors.length > CASES_MAX_ERRORS) {
      errorCard.appendChild(casesEl("p", "note-inline", casesFill(casesText("moreErrors"), {
        n: casesErrors.length - CASES_MAX_ERRORS,
      })));
    }
    wrap.appendChild(errorCard);
  }

  if (!casesBook) {
    const emptyCard = casesEl("article", "card wide");
    emptyCard.appendChild(emptyLine(casesText("empty")));
    emptyCard.appendChild(casesEl("p", "note-inline", casesText("emptyWhy")));
    wrap.appendChild(emptyCard);
    host.appendChild(wrap);
    host.scrollTop = savedScroll;
    return;
  }

  const summary = casesSummary(casesBook);
  const listCard = casesEl("article", "card wide");
  listCard.appendChild(cardHead(casesText("title"), casesText("sortNote")));
  listCard.appendChild(casesEl("p", "note-inline", casesText("unverified")));
  listCard.appendChild(casesSummaryLine(summary));
  for (const line of casesBreakdown(summary)) listCard.appendChild(line);
  listCard.appendChild(casesFilterRow());
  const visible = casesFilteredBook(casesBook, casesStatusFilter);
  const rows = casesLotRows(visible);
  if (casesStatusFilter !== "all") {
    listCard.appendChild(casesEl("p", "note-inline", casesFill(casesText("filterNote"), {
      status: casesLabel(casesStatusFilter, "status"),
    })));
  }
  if (!rows.length) {
    listCard.appendChild(emptyLine(casesText("emptyLots")));
  } else {
    listCard.appendChild(casesLotTable(rows));
  }
  wrap.appendChild(listCard);
  host.appendChild(wrap);
  host.scrollTop = savedScroll;
  if (activeLot) {
    const toggle = host.querySelector(`button[data-lot="${CSS.escape(activeLot)}"]`);
    if (toggle) toggle.focus();
  }
}
