// Quality page: the ResiliTrace trust-metrics view.
// Loaded before quality.js so paintAnalyze can call into it.
//
// Data source (v0): a QualityReport JSON file exported by
// resilimes.explain.quality.evaluate() (quality/v0). There is no
// server endpoint yet — quality.py lives in unmerged PR #88 — so the
// page reads a file the user picks, validates it against the
// quality/v0 contract, and renders it read-only. The report stays in
// memory only; reloading the page unloads it.
//
// Read-only on purpose: the page presents the numbers exactly as the
// file reports them and never recomputes a rate. A hand-written file
// is indistinguishable from a real export, so the page says so
// (quality.unverified) instead of claiming the numbers are checked.
//
// The validator mirrors quality.py (QualityReport) as closely as a
// browser can: pydantic defaults are accepted (missing
// metrics_version / calibration_bins / expected_calibration_error,
// and a missing Rate.value when the denominator is 0) and lax
// numeric coercion is accepted ("12" for a count, "12.0" too —
// pydantic lax mode accepts both, but not exponent strings such as
// "1e3" for an integer field), and the payload is normalized
// (defaults filled, numeric strings coerced) before it is stored.
// Four deliberate divergences remain, all recorded in
// docs/QUALITY_PAGE.md: (1) a calibration bin with count 0 must
// carry null mean/accuracy; (2) ECE and bin mean/accuracy must lie
// in [0, 1]; (3) cross-field consistency is enforced (counts add
// up, denominators match their totals, bin counts sum to the
// calibration sample count); (4) bin geometry must be sane
// (lower < upper, non-decreasing). Validation error details stay
// English field paths.

const QUALITY_VERSION = "quality/v0";
const QUALITY_BIN_COUNT = 10;
const QUALITY_MAX_ERRORS = 20;
const QUALITY_MAX_FILE_BYTES = 5 * 1024 * 1024;

const QUALITY_REPORT_KEYS = [
  "metrics_version", "total_samples", "answered", "unknown_answers",
  "truth_known", "misattribution", "over_unknown", "unknown_share",
  "calibration_samples", "calibration_excluded_no_confidence",
  "calibration_bins", "expected_calibration_error",
];
const QUALITY_RATE_KEYS = ["numerator", "denominator", "value"];
const QUALITY_BIN_KEYS = ["lower", "upper", "count", "mean_confidence", "accuracy"];
const QUALITY_COUNT_KEYS = [
  "total_samples", "answered", "unknown_answers", "truth_known",
  "calibration_samples", "calibration_excluded_no_confidence",
];
const QUALITY_NUMERIC_RE = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;

let qualityReport = null;
let qualityFileName = "";
let qualityErrors = [];
let qualityLoadSeq = 0;

function qualityCopy() {
  const copy = t();
  return (copy && copy.quality) || {};
}

// Every quality.* string falls back to the English label before "".
function qualityText(key) {
  const copy = qualityCopy();
  if (typeof copy[key] === "string" && copy[key]) return copy[key];
  const en = ((COPY.en || {}).quality || {})[key];
  return typeof en === "string" ? en : "";
}

// Single-pass placeholder expansion: a value containing "{total}" must
// not be re-expanded by a later placeholder (e.g. a file named so).
function qualityFill(template, params) {
  const known = params || {};
  return String(template || "").replace(/\{(\w+)\}/g, (match, name) => (
    Object.prototype.hasOwnProperty.call(known, name)
      ? String(known[name] == null ? "" : known[name])
      : match
  ));
}

function qualityIsPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function qualityToNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && QUALITY_NUMERIC_RE.test(value.trim())) {
    const num = Number(value.trim());
    if (Number.isFinite(num)) return num;
  }
  return null;
}

function qualityToInt(value) {
  // Pydantic lax mode accepts "12.0", "+12" and " 12 " for an int,
  // but rejects exponent strings such as "1e3" — mirror that.
  if (typeof value === "string" && /[eE]/.test(value.trim())) return null;
  const num = qualityToNumber(value);
  return num !== null && Number.isInteger(num) ? num : null;
}

function qualityCheckKeys(obj, allowed, where, errors) {
  for (const key of Object.keys(obj)) {
    if (!allowed.includes(key)) errors.push(`${where}: unknown key ${JSON.stringify(key)}`);
  }
}

function qualityCheckRate(rate, where, errors) {
  if (!qualityIsPlainObject(rate)) {
    errors.push(`${where}: must be an object`);
    return;
  }
  qualityCheckKeys(rate, QUALITY_RATE_KEYS, where, errors);
  const numerator = qualityToInt(rate.numerator);
  const denominator = qualityToInt(rate.denominator);
  if (numerator === null || numerator < 0) {
    errors.push(`${where}.numerator: must be an integer >= 0`);
  }
  if (denominator === null || denominator < 0) {
    errors.push(`${where}.denominator: must be an integer >= 0`);
  }
  if (numerator === null || denominator === null) return;
  if (numerator > denominator) {
    errors.push(`${where}: numerator ${numerator} exceeds denominator ${denominator}`);
    return;
  }
  if (denominator === 0) {
    // Rate.value defaults to None in quality.py, so a missing value
    // is as legal as an explicit null here.
    if (rate.value !== null && rate.value !== undefined) {
      errors.push(`${where}.value: must be null when the denominator is 0`);
    }
    return;
  }
  if (rate.value === undefined || rate.value === null || qualityToNumber(rate.value) === null) {
    errors.push(`${where}.value: must be a finite number`);
    return;
  }
  if (Math.abs(qualityToNumber(rate.value) - numerator / denominator) > 1e-9) {
    errors.push(`${where}.value: must equal numerator / denominator`);
  }
}

function qualityCheckBin(bin, where, errors) {
  if (!qualityIsPlainObject(bin)) {
    errors.push(`${where}: must be an object`);
    return;
  }
  qualityCheckKeys(bin, QUALITY_BIN_KEYS, where, errors);
  if (qualityToNumber(bin.lower) === null) errors.push(`${where}.lower: must be a finite number`);
  if (qualityToNumber(bin.upper) === null) errors.push(`${where}.upper: must be a finite number`);
  const count = qualityToInt(bin.count);
  if (count === null || count < 0) errors.push(`${where}.count: must be an integer >= 0`);
  for (const field of ["mean_confidence", "accuracy"]) {
    if (bin[field] !== undefined && bin[field] !== null && qualityToNumber(bin[field]) === null) {
      errors.push(`${where}.${field}: must be a finite number or null`);
    }
  }
  // Deliberately stricter than quality.py: ECE, mean and accuracy
  // are defined on [0, 1] but the Python model puts no range on
  // them, so nothing anywhere in the chain checks. This page does.
  for (const field of ["mean_confidence", "accuracy"]) {
    const num = bin[field] === undefined || bin[field] === null ? null : qualityToNumber(bin[field]);
    if (num !== null && (num < 0 || num > 1)) {
      errors.push(`${where}.${field}: must be within [0, 1]`);
    }
  }
  // Deliberately stricter than quality.py: a bin with no samples
  // cannot carry a mean or an accuracy. A genuine evaluate() export
  // never does (empty bins carry nulls); see docs/QUALITY_PAGE.md.
  if (count === 0) {
    if (bin.mean_confidence !== null && bin.mean_confidence !== undefined) {
      errors.push(`${where}.mean_confidence: must be null when count is 0`);
    }
    if (bin.accuracy !== null && bin.accuracy !== undefined) {
      errors.push(`${where}.accuracy: must be null when count is 0`);
    }
  }
}

// Validate a parsed JSON value against the quality/v0 report contract.
// Returns a list of error strings; an empty list means the report is
// valid. Pydantic defaults are accepted (missing metrics_version /
// calibration_bins), as is lax numeric coercion ("12" for a count).
// The Python model stays authoritative; the two intentional
// divergences (empty-bin mean/accuracy, error language) are recorded
// in docs/QUALITY_PAGE.md.
function validateQualityReport(payload) {
  const errors = [];
  if (!qualityIsPlainObject(payload)) return ["report: must be a JSON object"];
  qualityCheckKeys(payload, QUALITY_REPORT_KEYS, "report", errors);
  if (payload.metrics_version !== undefined && payload.metrics_version !== QUALITY_VERSION) {
    errors.push(`report.metrics_version: must be ${JSON.stringify(QUALITY_VERSION)}`);
  }
  for (const field of QUALITY_COUNT_KEYS) {
    const value = qualityToInt(payload[field]);
    if (value === null || value < 0) {
      errors.push(`report.${field}: must be an integer >= 0`);
    }
  }
  for (const field of ["misattribution", "over_unknown", "unknown_share"]) {
    if (payload[field] === undefined) {
      errors.push(`report.${field}: is required`);
    } else {
      qualityCheckRate(payload[field], `report.${field}`, errors);
    }
  }
  if (payload.expected_calibration_error === undefined) {
    // Expected_calibration_error defaults to None in quality.py.
  } else if (payload.expected_calibration_error !== null) {
    const ece = qualityToNumber(payload.expected_calibration_error);
    if (ece === null) {
      errors.push("report.expected_calibration_error: must be a finite number or null");
    } else if (ece < 0 || ece > 1) {
      // Deliberately stricter than quality.py (see qualityCheckBin).
      errors.push("report.expected_calibration_error: must be within [0, 1]");
    }
  }
  const bins = payload.calibration_bins === undefined ? [] : payload.calibration_bins;
  if (!Array.isArray(bins)) {
    errors.push("report.calibration_bins: must be an array");
  } else {
    // Cap the stored errors: a 5 MB file of tiny invalid bins could
    // otherwise grow this array into the tens of thousands. The
    // truncation line keeps the displayed "N more" count honest as a
    // lower bound.
    for (let index = 0; index < bins.length; index += 1) {
      if (errors.length >= 50) {
        errors.push("report.calibration_bins: too many errors, showing the first 50");
        break;
      }
      qualityCheckBin(bins[index], `report.calibration_bins[${index}]`, errors);
    }
  }
  // Deliberately stricter than quality.py: evaluate() outputs are
  // always internally consistent, so a report whose numbers
  // contradict each other is not a genuine export. Only checked
  // when every involved field parsed, so one bad field does not
  // cascade into spurious consistency errors.
  const total = qualityToInt(payload.total_samples);
  const answered = qualityToInt(payload.answered);
  const unknownAnswers = qualityToInt(payload.unknown_answers);
  const truthKnown = qualityToInt(payload.truth_known);
  const calibSamples = qualityToInt(payload.calibration_samples);
  if (total !== null && answered !== null && unknownAnswers !== null
    && answered + unknownAnswers !== total) {
    errors.push("report: answered + unknown_answers must equal total_samples");
  }
  const rateDen = (field) => {
    const rate = payload[field];
    return qualityIsPlainObject(rate) ? qualityToInt(rate.denominator) : null;
  };
  const misDen = rateDen("misattribution");
  const overDen = rateDen("over_unknown");
  const shareDen = rateDen("unknown_share");
  if (truthKnown !== null && overDen !== null && overDen !== truthKnown) {
    errors.push("report.over_unknown.denominator: must equal truth_known");
  }
  if (truthKnown !== null && misDen !== null && misDen > truthKnown) {
    errors.push("report.misattribution.denominator: must not exceed truth_known");
  }
  if (total !== null && shareDen !== null && shareDen !== total) {
    errors.push("report.unknown_share.denominator: must equal total_samples");
  }
  if (Array.isArray(bins) && calibSamples !== null) {
    let binSum = 0;
    let binsUsable = true;
    let prevLower = null;
    for (const bin of bins) {
      if (!qualityIsPlainObject(bin)) { binsUsable = false; break; }
      const count = qualityToInt(bin.count);
      const lower = qualityToNumber(bin.lower);
      const upper = qualityToNumber(bin.upper);
      if (count === null || lower === null || upper === null) { binsUsable = false; break; }
      binSum += count;
      if (!(lower < upper)) {
        errors.push("report.calibration_bins: each bin needs lower < upper");
        binsUsable = false;
        break;
      }
      if (prevLower !== null && lower < prevLower) {
        errors.push("report.calibration_bins: bins must be in non-decreasing lower order");
        binsUsable = false;
        break;
      }
      prevLower = lower;
    }
    if (binsUsable && binSum !== calibSamples) {
      errors.push("report: calibration bin counts must sum to calibration_samples");
    }
  }
  return errors;
}

// Normalize a validated payload the way pydantic does: fill defaults
// and coerce numeric strings. Returns a new object; the caller's
// payload is untouched.
function normalizeQualityReport(payload) {
  const report = JSON.parse(JSON.stringify(payload));
  if (report.metrics_version === undefined) report.metrics_version = QUALITY_VERSION;
  for (const field of QUALITY_COUNT_KEYS) {
    if (report[field] !== undefined) report[field] = qualityToInt(report[field]);
  }
  for (const field of ["misattribution", "over_unknown", "unknown_share"]) {
    const rate = report[field];
    if (qualityIsPlainObject(rate)) {
      if (rate.numerator !== undefined) rate.numerator = qualityToInt(rate.numerator);
      if (rate.denominator !== undefined) rate.denominator = qualityToInt(rate.denominator);
      if (rate.value !== undefined && rate.value !== null) rate.value = qualityToNumber(rate.value);
      if (rate.value === undefined && rate.denominator === 0) rate.value = null;
    }
  }
  if (report.expected_calibration_error === undefined) report.expected_calibration_error = null;
  if (report.expected_calibration_error !== null) {
    report.expected_calibration_error = qualityToNumber(report.expected_calibration_error);
  }
  if (!Array.isArray(report.calibration_bins)) report.calibration_bins = [];
  for (const bin of report.calibration_bins) {
    if (!qualityIsPlainObject(bin)) continue;
    if (bin.lower !== undefined) bin.lower = qualityToNumber(bin.lower);
    if (bin.upper !== undefined) bin.upper = qualityToNumber(bin.upper);
    if (bin.count !== undefined) bin.count = qualityToInt(bin.count);
    if (bin.mean_confidence !== undefined && bin.mean_confidence !== null) {
      bin.mean_confidence = qualityToNumber(bin.mean_confidence);
    }
    if (bin.accuracy !== undefined && bin.accuracy !== null) {
      bin.accuracy = qualityToNumber(bin.accuracy);
    }
  }
  return report;
}

function qualitySummary(report) {
  return {
    total: report.total_samples,
    answered: report.answered,
    unknownAnswers: report.unknown_answers,
    truthKnown: report.truth_known,
    calibrationSamples: report.calibration_samples,
    excludedNoConfidence: report.calibration_excluded_no_confidence,
  };
}

// "2/7 · 28.6%", or null when the denominator is 0 (not enough data:
// never reported as 0.0%). The percent is the file's own value, not a
// recomputation — the page presents, it does not re-derive.
function qualityRateText(rate) {
  if (!qualityIsPlainObject(rate) || rate.denominator === 0) return null;
  const pct = (Number(rate.value) * 100).toFixed(1);
  return `${rate.numerator}/${rate.denominator} · ${pct}%`;
}

// Print a bin edge without rounding it onto the 0.1 grid:
// "[0.05, 0.15)" must not come out as "[0.1, 0.1)".
function qualityBinEdge(value) {
  const text = Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return text === "-0" ? "0" : text;
}

// One display row per calibration bin: the range as printed, the
// sample count, and the mean/accuracy as reported (null when the bin
// is empty). The last bin reaching 1.0 is closed on both ends.
function qualityBinRows(report) {
  return (report.calibration_bins || []).map((bin) => ({
    range: `[${qualityBinEdge(bin.lower)}, ${qualityBinEdge(bin.upper)}${Number(bin.upper) === 1 ? "]" : ")"}`,
    count: bin.count,
    mean: bin.mean_confidence,
    accuracy: bin.accuracy,
  }));
}

function qualityEl(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value == null ? "" : String(value);
  return node;
}

function qualityRateCard(title, note, rate, denText) {
  const card = qualityEl("article", "card");
  card.appendChild(cardHead(title, note));
  const text = qualityRateText(rate);
  if (text === null) {
    card.appendChild(qualityEl("p", "rate-big", qualityText("noSamples")));
  } else {
    card.appendChild(qualityEl("p", "rate-big", text.split(" · ")[1]));
    card.appendChild(qualityEl("p", "rate-den", denText));
  }
  // Every content card carries the provenance warning, so a cropped
  // screenshot of one card never looks like a verified measurement.
  card.appendChild(qualityEl("p", "note-inline", qualityText("unverifiedShort")));
  return card;
}

async function qualityLoadFile(file) {
  const mySeq = ++qualityLoadSeq;
  if (file.size > QUALITY_MAX_FILE_BYTES) {
    qualityReport = null;
    qualityFileName = "";
    qualityErrors = [qualityFill(qualityText("fileTooLarge"), { mb: (file.size / 1048576).toFixed(1) })];
    paintAnalyze();
    return;
  }
  let text = "";
  try {
    text = await file.text();
  } catch (error) {
    if (mySeq !== qualityLoadSeq) return;
    qualityReport = null;
    qualityFileName = "";
    qualityErrors = [qualityFill(qualityText("invalidJson"), { reason: String((error && error.message) || error) })];
    paintAnalyze();
    return;
  }
  if (mySeq !== qualityLoadSeq) return;
  let payload = null;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    qualityReport = null;
    qualityFileName = "";
    qualityErrors = [qualityFill(qualityText("invalidJson"), { reason: String((error && error.message) || error) })];
    paintAnalyze();
    return;
  }
  const errors = validateQualityReport(payload);
  if (errors.length) {
    qualityReport = null;
    qualityFileName = "";
    qualityErrors = errors;
    paintAnalyze();
    return;
  }
  qualityReport = normalizeQualityReport(payload);
  qualityFileName = file.name || "";
  qualityErrors = [];
  paintAnalyze();
}

// The view switch at the top of the Metrics panel: the old scheduler
// KPI view stays the default (see docs/QUALITY_PAGE.md for why), the
// trust view is the parallel ResiliTrace view.
function qualityViewToggle() {
  const row = qualityEl("div", "toggles quality-view-toggle");
  for (const [id, labelKey] of [["kpi", "viewKpi"], ["trust", "viewTrust"]]) {
    const button = qualityEl("button", "", qualityText(labelKey));
    button.type = "button";
    button.id = `quality-view-${id}`;
    button.setAttribute("aria-pressed", (state.qualityView || "kpi") === id ? "true" : "false");
    button.addEventListener("click", () => {
      state.qualityView = id;
      paintAnalyze();
    });
    row.appendChild(button);
  }
  return row;
}

// Render the trust view into #panel-analyze, below the view toggle
// that paintAnalyze already placed there. The host is not cleared
// here; paintAnalyze owns the clear. Scroll is restored by the
// caller, which saved it before clearing.
function paintQualityReport() {
  const host = document.getElementById("panel-analyze");
  if (!host) return;
  const wrap = qualityEl("div", "quality-report");
  const loadCard = qualityEl("article", "card wide");
  loadCard.appendChild(cardHead(qualityText("trustTitle"), qualityText("trustLead")));
  const fileRow = qualityEl("div", "file-row");
  const label = qualityEl("label", "", qualityText("loadFile"));
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json,application/json";
  input.id = "quality-file";
  label.htmlFor = "quality-file";
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (file) qualityLoadFile(file);
  });
  fileRow.append(label, input);
  if (qualityReport) {
    const unload = qualityEl("button", "run quiet", qualityText("unload"));
    unload.type = "button";
    unload.addEventListener("click", () => {
      qualityReport = null;
      qualityFileName = "";
      qualityErrors = [];
      const picker = document.getElementById("quality-file");
      if (picker) picker.value = "";
      paintAnalyze();
    });
    fileRow.appendChild(unload);
  }
  loadCard.appendChild(fileRow);
  loadCard.appendChild(qualityEl("p", "note-inline", qualityText("loadHint")));
  if (qualityReport) {
    const summary = qualitySummary(qualityReport);
    loadCard.appendChild(qualityEl("p", "note-inline", qualityFill(qualityText("loaded"), {
      name: qualityFileName,
      total: summary.total,
      truth: summary.truthKnown,
    })));
  }
  loadCard.appendChild(qualityEl("p", "note-inline", qualityText("unverified")));
  wrap.appendChild(loadCard);

  if (qualityErrors.length) {
    const errorCard = qualityEl("article", "card wide");
    errorCard.appendChild(cardHead(qualityText("fileError"), ""));
    const list = document.createElement("ul");
    list.className = "quality-errors";
    for (const error of qualityErrors.slice(0, QUALITY_MAX_ERRORS)) {
      list.appendChild(qualityEl("li", "mono", error));
    }
    errorCard.appendChild(list);
    if (qualityErrors.length > QUALITY_MAX_ERRORS) {
      errorCard.appendChild(qualityEl("p", "note-inline", qualityFill(qualityText("moreErrors"), {
        n: qualityErrors.length - QUALITY_MAX_ERRORS,
      })));
    }
    errorCard.appendChild(qualityEl("p", "note-inline", qualityText("fileErrorNext")));
    wrap.appendChild(errorCard);
  }

  if (!qualityReport) {
    const emptyCard = qualityEl("article", "card wide");
    emptyCard.appendChild(emptyLine(qualityText("empty")));
    emptyCard.appendChild(qualityEl("p", "note-inline", qualityText("emptyWhy")));
    wrap.appendChild(emptyCard);
    host.appendChild(wrap);
    return;
  }

  const summary = qualitySummary(qualityReport);
  const ratesCard = qualityEl("div", "cards");
  ratesCard.appendChild(qualityRateCard(
    qualityText("misattribution"), qualityText("misattributionNote"),
    qualityReport.misattribution,
    qualityFill(qualityText("misattributionDen"), {
      num: qualityReport.misattribution.numerator,
      den: qualityReport.misattribution.denominator,
    }),
  ));
  ratesCard.appendChild(qualityRateCard(
    qualityText("overUnknown"), qualityText("overUnknownNote"),
    qualityReport.over_unknown,
    qualityFill(qualityText("overUnknownDen"), {
      num: qualityReport.over_unknown.numerator,
      den: qualityReport.over_unknown.denominator,
    }),
  ));
  ratesCard.appendChild(qualityRateCard(
    qualityText("unknownShare"), qualityText("unknownShareNote"),
    qualityReport.unknown_share,
    qualityFill(qualityText("unknownShareDen"), {
      num: qualityReport.unknown_share.numerator,
      den: qualityReport.unknown_share.denominator,
    }),
  ));
  wrap.appendChild(ratesCard);

  const calibCard = qualityEl("article", "card wide");
  calibCard.appendChild(cardHead(qualityText("calibrationTitle"), ""));
  const ece = qualityReport.expected_calibration_error;
  if (ece === null || ece === undefined) {
    calibCard.appendChild(qualityEl("p", "rate-big", qualityText("noSamples")));
  } else {
    calibCard.appendChild(qualityEl("p", "rate-big", Number(ece).toFixed(3)));
  }
  calibCard.appendChild(qualityEl("p", "rate-den", qualityText("ece")));
  calibCard.appendChild(qualityEl("p", "note-inline", qualityText("eceDef")));
  calibCard.appendChild(qualityEl("p", "note-inline", qualityFill(qualityText("calibrationNote"), {
    n: summary.calibrationSamples,
    excluded: summary.excludedNoConfidence,
  })));
  calibCard.appendChild(qualityEl("p", "note-inline", qualityText("unverifiedShort")));
  const rows = qualityBinRows(qualityReport);
  if (!rows.length) {
    calibCard.appendChild(qualityEl("p", "note-inline", qualityText("noBins")));
  } else {
    const table = qualityEl("table", "compare");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const [label, klass] of [
      [qualityText("binRange"), ""],
      [qualityText("binCount"), "num"],
      [qualityText("binMean"), "num"],
      [qualityText("binAccuracy"), "num"],
    ]) {
      headRow.appendChild(qualityEl("th", klass || undefined, label || ""));
    }
    head.appendChild(headRow);
    table.appendChild(head);
    const body = document.createElement("tbody");
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.appendChild(qualityEl("td", "mono", row.range));
      tr.appendChild(qualityEl("td", "num", row.count));
      tr.appendChild(qualityEl("td", "num", row.mean === null || row.mean === undefined ? "—" : Number(row.mean).toFixed(3)));
      tr.appendChild(qualityEl("td", "num", row.accuracy === null || row.accuracy === undefined ? "—" : Number(row.accuracy).toFixed(3)));
      body.appendChild(tr);
    }
    table.appendChild(body);
    calibCard.appendChild(table);
  }
  wrap.appendChild(calibCard);

  const countsCard = qualityEl("article", "card wide");
  countsCard.appendChild(cardHead(qualityText("countsTitle"), ""));
  const table = qualityEl("table", "compare");
  const body = document.createElement("tbody");
  for (const [label, value] of [
    [qualityText("totalSamples"), summary.total],
    [qualityText("answered"), summary.answered],
    [qualityText("unknownAnswers"), summary.unknownAnswers],
    [qualityText("truthKnown"), summary.truthKnown],
  ]) {
    const tr = document.createElement("tr");
    tr.appendChild(qualityEl("th", "", label));
    tr.appendChild(qualityEl("td", "num", value));
    body.appendChild(tr);
  }
  table.appendChild(body);
  countsCard.appendChild(table);
  countsCard.appendChild(qualityEl("p", "note-inline", qualityText("unverifiedShort")));
  wrap.appendChild(countsCard);

  host.appendChild(wrap);
}
