// AI evidence panel: investigator (and, in later PRs, late-lot explainer and
// shift handover). Answers are advice only; every number in them is checked
// against the tool results that produced it.
const AI = { busy: {}, out: {}, cases: null };
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

async function aiLoad() {
  if (AI.cases !== null) return;
  AI.cases = [];
  try {
    AI.cases = (await getJson("/api/ai/investigator/cases")).cases || [];
  } catch (error) {
    AI.cases = [];
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
    section.render(card, copy);
    host.appendChild(card);
  }
  aiLoad();
}
