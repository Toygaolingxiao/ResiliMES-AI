// AI evidence panel: investigator, late-lot explainer and shift handover. Answers are advice only; every number in them is checked
// against the tool results that produced it.
const AI = { busy: {}, out: {}, cases: null, lots: null, shifts: null };
const AI_SECTIONS = [];

function aiCause(copy, id) {
  if (!id) return "—";
  return (copy.causes && copy.causes[id]) || id;
}

async function aiPost(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

function aiEl(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function aiBadge(copy, payload) {
  const mocked = payload && (payload.mocked ?? (payload.answer && payload.answer.mocked));
  return aiEl("span", "chip", mocked ? copy.mock : copy.live);
}

function aiFact(copy, ok, misses) {
  return aiEl("p", ok ? "ai-ok" : "ai-warn", ok ? copy.factOk : `${copy.factFlag} ${(misses || []).join(", ")}`);
}

AI_SECTIONS.push({
  id: "investigator",
  render(host, copy) {
    host.appendChild(aiEl("h3", "", copy.invTitle));
    host.appendChild(aiEl("p", "muted", copy.invHelp));
    const row = aiEl("div", "ai-row");
    const select = aiEl("select", "");
    select.id = "ai-case";
    for (const item of AI.cases || []) {
      const option = aiEl("option", "", item.question);
      option.value = item.case_id;
      if (AI.out.investigatorCase === item.case_id) option.selected = true;
      select.appendChild(option);
    }
    const button = aiEl("button", "run", AI.busy.investigator ? copy.working : copy.invRun);
    button.type = "button";
    button.disabled = !!AI.busy.investigator || !(AI.cases || []).length;
    button.addEventListener("click", async () => {
      AI.busy.investigator = true;
      AI.out.investigatorCase = select.value;
      paintAi();
      try {
        AI.out.investigator = await aiPost("/api/ai/investigate", { case_id: select.value });
      } catch (error) {
        AI.out.investigator = { error: String(error.message || error) };
      }
      AI.busy.investigator = false;
      paintAi();
    });
    row.append(select, button);
    host.appendChild(row);
    const result = AI.out.investigator;
    if (!result) return;
    if (result.error) {
      host.appendChild(aiEl("p", "ai-warn", result.error));
      return;
    }
    const answer = result.answer || {};
    const head = aiEl("p", "");
    head.append(aiBadge(copy, result), aiEl("strong", "", ` ${copy.cause}: ${aiCause(copy, answer.primary_cause)}`));
    if (answer.secondary_cause) head.append(aiEl("span", "muted", ` (${copy.second}: ${aiCause(copy, answer.secondary_cause)})`));
    host.appendChild(head);
    const list = aiEl("ol", "");
    for (const step of answer.causal_chain || []) list.appendChild(aiEl("li", "", step));
    host.appendChild(list);
    host.appendChild(aiEl("p", "", `${copy.lever}: ${answer.lever || "—"} (${copy.adviceOnly})`));
    host.appendChild(aiEl("p", "muted", `${copy.calls}: ${(answer.calls || []).map((c) => c.tool).join(" → ")}`));
    host.appendChild(aiFact(copy, answer.fact_ok, answer.fact_misses));
    host.appendChild(
      aiEl("p", "muted", `${copy.truth}: ${aiCause(copy, result.truth)} · ${copy.baseline}: ${(result.baseline || []).map((x) => aiCause(copy, x)).join(", ")}`),
    );
  },
});

AI_SECTIONS.push({
  id: "explainer",
  render(host, copy) {
    host.appendChild(aiEl("h3", "", copy.expTitle));
    host.appendChild(aiEl("p", "muted", copy.expHelp));
    const row = aiEl("div", "ai-row");
    const select = aiEl("select", "");
    select.id = "ai-lot";
    for (const item of AI.lots || []) {
      const option = aiEl("option", "", `${item.lot} · ${copy.lateBy} ${item.late_h} h`);
      option.value = item.lot;
      if (AI.out.explainerLot === item.lot) option.selected = true;
      select.appendChild(option);
    }
    const button = aiEl("button", "run", AI.busy.explainer ? copy.working : copy.expRun);
    button.type = "button";
    button.disabled = !!AI.busy.explainer || !(AI.lots || []).length;
    button.addEventListener("click", async () => {
      AI.busy.explainer = true;
      AI.out.explainerLot = select.value;
      paintAi();
      try {
        AI.out.explainer = await aiPost("/api/ai/explain", { lot_id: select.value, seed: 1, lang: state.lang || "en" });
      } catch (error) {
        AI.out.explainer = { error: String(error.message || error) };
      }
      AI.busy.explainer = false;
      paintAi();
    });
    row.append(select, button);
    host.appendChild(row);
    const result = AI.out.explainer;
    if (!result) return;
    if (result.error) {
      host.appendChild(aiEl("p", "ai-warn", result.error));
      return;
    }
    const answer = result.answer || {};
    const late = result.lateness || {};
    const head = aiEl("p", "");
    head.append(aiBadge(copy, result), aiEl("strong", "", ` ${late.lot}: ${copy.lateBy} ${late.late_min} min`));
    host.appendChild(head);
    const parts = Object.entries(late.while_late_min || {}).sort((a, b) => b[1] - a[1]);
    const list = aiEl("ul", "ai-split");
    for (const [name, minutes] of parts) list.appendChild(aiEl("li", "", `${(copy.buckets || {})[name] || name}: ${minutes} min`));
    host.appendChild(list);
    const split = result.split || {};
    host.appendChild(aiEl("p", "muted", split.exact && split.shown_sum_ok ? copy.sumOk : copy.sumBad));
    host.appendChild(aiEl("p", "", answer.explanation || answer.error || "—"));
    host.appendChild(aiFact(copy, answer.fact_ok, answer.fact_misses));
    const cf = result.counterfactual;
    if (cf && cf.verified) {
      const lever = `${(copy.levers || {})[cf.lever] || cf.lever}${cf.family ? ` · ${cf.family}` : ""}`;
      host.appendChild(aiEl("p", "", `${copy.cfTitle}: ${lever} (${copy.adviceOnly})`));
      host.appendChild(
        aiEl(
          "p",
          cf.hit ? "ai-ok" : "ai-warn",
          `${copy.cfExpected} ${cf.expected_saving_min} min · ${copy.cfActual} ${cf.saving_min} min (${cf.late_before_min} → ${cf.late_after_min} min) · ${cf.hit ? copy.cfHit : copy.cfMiss}`,
        ),
      );
    }
  },
});

AI_SECTIONS.push({
  id: "handover",
  render(host, copy) {
    host.appendChild(aiEl("h3", "", copy.hoTitle));
    host.appendChild(aiEl("p", "muted", copy.hoHelp));
    const row = aiEl("div", "ai-row");
    const select = aiEl("select", "");
    select.id = "ai-shift";
    for (const item of AI.shifts || []) {
      const key = `${item.seed}:${item.start_h}`;
      const option = aiEl("option", "", `${copy.hoShift} ${item.start_h}–${item.end_h} h · seed ${item.seed}`);
      option.value = key;
      if (AI.out.handoverShift === key) option.selected = true;
      select.appendChild(option);
    }
    const button = aiEl("button", "run", AI.busy.handover ? copy.working : copy.hoRun);
    button.type = "button";
    button.disabled = !!AI.busy.handover || !(AI.shifts || []).length;
    button.addEventListener("click", async () => {
      AI.busy.handover = true;
      AI.out.handoverShift = select.value;
      const [seed, start] = select.value.split(":");
      paintAi();
      try {
        AI.out.handover = await aiPost("/api/ai/handover", { seed: Number(seed), start_h: Number(start), lang: state.lang || "en" });
      } catch (error) {
        AI.out.handover = { error: String(error.message || error) };
      }
      AI.busy.handover = false;
      paintAi();
    });
    row.append(select, button);
    host.appendChild(row);
    const result = AI.out.handover;
    if (!result) return;
    if (result.error && !result.report) {
      host.appendChild(aiEl("p", "ai-warn", result.error));
      return;
    }
    const head = aiEl("p", "");
    head.append(
      aiBadge(copy, result),
      aiEl("span", "muted", ` ${copy.hoEngine}: ${result.engine} · ${copy.hoChunks} ${result.chunks_ok}/${(result.chunks || []).length} · ${copy.hoRecall} ${Math.round((result.must_recall || 0) * 100)}%`),
    );
    host.appendChild(head);
    host.appendChild(aiEl("pre", "ai-md", result.markdown || "—"));
    host.appendChild(aiFact(copy, result.fact_ok, result.fact_misses));
  },
});

async function aiLoad() {
  if (AI.cases !== null) return;
  AI.cases = [];
  AI.lots = [];
  try {
    AI.cases = (await getJson("/api/ai/investigator/cases")).cases || [];
  } catch (error) {
    AI.cases = [];
  }
  paintAi();
  try {
    AI.lots = (await getJson("/api/ai/explainer/lots?seed=1")).lots || [];
  } catch (error) {
    AI.lots = [];
  }
  paintAi();
  try {
    AI.shifts = (await getJson("/api/ai/handover/shifts")).shifts || [];
  } catch (error) {
    AI.shifts = [];
  }
  paintAi();
}

function paintAi() {
  const host = document.querySelector("#panel-ai");
  if (!host) return;
  const copy = (t().ai || COPY.en.ai);
  host.innerHTML = "";
  host.appendChild(aiEl("p", "muted", copy.intro));
  for (const section of AI_SECTIONS) {
    const card = aiEl("article", "plan-card ai-card");
    const busy = Boolean(AI.busy[section.id]);
    card.classList.toggle("busy", busy);
    card.setAttribute("aria-busy", String(busy));
    section.render(card, copy);
    host.appendChild(card);
  }
  aiLoad();
}
