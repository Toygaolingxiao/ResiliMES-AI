// AI evidence panel: investigator, late-lot explainer and shift handover. Answers are advice only; every number in them is checked
// against the tool results that produced it.
const AI = { busy: {}, out: {}, cases: null, lots: null, shifts: null, notes: null };
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
        AI.out.handover = await aiPost("/api/ai/handover", { seed: Number(seed), start_h: Number(start), lang: state.lang || "ja" });
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

function ntEventText(event) {
  const parts = Object.entries(event || {})
    .filter(([key]) => key !== "type")
    .map(([key, value]) => `${key}=${value}`);
  return `${(event && event.type) || "?"}${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
}

AI_SECTIONS.push({
  id: "notes",
  render(host, copy) {
    host.appendChild(aiEl("h3", "", copy.ntTitle));
    host.appendChild(aiEl("p", "muted", copy.ntHelp));
    const data = AI.notes;
    if (!data || data.loading) {
      host.appendChild(aiEl("p", "muted", copy.working));
      return;
    }
    if (data.error) {
      // 404 = panel switched off (RESILIMES_NOTES_PANEL=0); anything else is a load failure. Either way, say so and stop.
      host.appendChild(aiEl("p", data.status === 404 ? "muted" : "ai-warn", data.status === 404 ? copy.ntUnavailable : `${copy.ntUnavailable} (${data.error})`));
      return;
    }
    if (!Array.isArray(data.notes) || !data.notes.length) {
      host.appendChild(aiEl("p", "muted", copy.ntUnavailable));
      return;
    }
    const head = aiEl("p", "");
    const summary = data.summary || {};
    head.append(
      aiBadge(copy, data),
      aiEl(
        "span",
        "muted",
        ` ${copy.ntExtractor}: ${data.extractor} · ${summary.notes ?? 0} · ✓ ${summary.accepted ?? 0} · ✗ ${summary.rejected ?? 0}`,
      ),
    );
    host.appendChild(head);
    if (data.truncated) host.appendChild(aiEl("p", "muted", `${copy.ntTruncated} (${data.limit})`));

    // A/B/C comparison summary (verbatim backend numbers; nothing invented).
    host.appendChild(aiEl("p", "", aiEl("strong", "", copy.ntAbcTitle).textContent));
    const cmp = data.comparison;
    if (!cmp) {
      host.appendChild(aiEl("p", "muted", copy.ntNotRun));
    } else {
      if (cmp.is_mock) host.appendChild(aiEl("p", "ai-warn", copy.ntMockNumbers));
      host.appendChild(aiEl("p", "muted", `${copy.ntRunner}: ${cmp.runner ?? "—"} · B ${copy.ntExtractor}: ${cmp.b_extractor ?? "—"}`));
      const arms = cmp.arms || {};
      const armLine = (label, arm) =>
        `${label}: ${copy.ntAvoidable} ${arm?.avoidable_qtime ?? "—"} · ${copy.ntApplied} ${arm?.applied_events ?? "—"}`;
      const list = aiEl("ul", "ai-split");
      list.appendChild(aiEl("li", "", armLine(`A · ${copy.ntArmBlind}`, arms.A)));
      list.appendChild(aiEl("li", "", armLine(`B · ${copy.ntArmAi}`, arms.B)));
      list.appendChild(aiEl("li", "", armLine(`C · ${copy.ntArmGold}`, arms.C)));
      host.appendChild(list);
      const closure = cmp.gap_closure === null || cmp.gap_closure === undefined
        ? "—"
        : `${Math.round(cmp.gap_closure * 1000) / 10}%`;
      const collateral = cmp.collateral || {};
      host.appendChild(
        aiEl(
          "p",
          "",
          `${copy.ntGapClosure}: ${closure} · ${copy.ntWrongEvents}: ${collateral.wrong_events_applied ?? "—"} · ${copy.ntNewViolations}: ${collateral.new_violations ?? "—"}`,
        ),
      );
    }

    const toggle = aiEl("button", "run", AI.out.notesGold ? copy.ntGoldHide : copy.ntGoldShow);
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      AI.out.notesGold = !AI.out.notesGold;
      paintAi();
    });
    const toggleRow = aiEl("div", "ai-row");
    toggleRow.appendChild(toggle);
    host.appendChild(toggleRow);

    const listHost = aiEl("div", "nt-list");
    for (const raw of data.notes) {
      const note = { ...raw, text: raw.text || "", events: raw.events || [], rejected: raw.rejected || [], gold: raw.gold || [] };
      const open = AI.out.notesOpen === note.note_id;
      const headBtn = aiEl("button", "nt-head");
      headBtn.type = "button";
      const when = (note.ts || "").replace("T", " ").replace("Z", "");
      const summaryText = note.text.length > 110 ? `${note.text.slice(0, 110)}…` : note.text;
      headBtn.append(
        aiEl("span", "nt-when", when),
        aiEl("span", "chip", note.source || "?"),
        aiEl("span", "chip", note.lang || "?"),
        ...(note.hard_for_regex ? [aiEl("span", "chip nt-hard", copy.ntHard)] : []),
        aiEl("span", "nt-text", summaryText),
        aiEl("span", "muted", `${open ? "▾" : "▸"} ${note.events.length} ✓ · ${note.rejected.length} ✗`),
      );
      headBtn.addEventListener("click", () => {
        AI.out.notesOpen = open ? null : note.note_id;
        paintAi();
      });
      listHost.appendChild(headBtn);
      if (!open) continue;
      const body = aiEl("div", "nt-body");
      body.appendChild(aiEl("p", "", note.text));
      body.appendChild(aiEl("p", "", aiEl("strong", "", copy.ntEvents).textContent));
      if (note.events.length) {
        const events = aiEl("ul", "ai-split");
        for (const event of note.events) events.appendChild(aiEl("li", "", ntEventText(event)));
        body.appendChild(events);
      } else {
        body.appendChild(aiEl("p", "muted", copy.ntNoEvents));
      }
      for (const rejected of note.rejected || []) {
        body.appendChild(
          aiEl("p", "ai-warn nt-rejected", `✗ ${copy.ntRejected}: ${rejected.reason} — ${ntEventText(rejected.event)}`),
        );
      }
      if (AI.out.notesGold) {
        body.appendChild(aiEl("p", "", aiEl("strong", "", copy.ntGoldLabel).textContent));
        if ((note.gold || []).length) {
          const gold = aiEl("ul", "ai-split nt-gold");
          for (const event of note.gold) gold.appendChild(aiEl("li", "", ntEventText(event)));
          body.appendChild(gold);
        } else {
          body.appendChild(aiEl("p", "muted", copy.ntNoEvents));
        }
      }
      listHost.appendChild(body);
    }
    host.appendChild(listHost);
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
  if (AI.notes === null) {
    AI.notes = { loading: true };
    try {
      AI.notes = await getJson("/api/ai/notes");
    } catch (error) {
      const status = Number((String(error.message || "").match(/\((\d{3})\)/) || [])[1]) || null;
      AI.notes = { error: String(error.message || error), status };
    }
    paintAi();
  }
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
