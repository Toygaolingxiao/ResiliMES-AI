// Evidence page: the investigator. Advice only.

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
    if (answer.degraded) {
      const rule = answer.system || {};
      host.appendChild(
        aiEl("p", "ai-warn", `${copy.degraded} (${answer.degrade_reason || "—"}): ${aiCause(copy, rule.primary_cause)}`),
      );
    }
    const head = aiEl("p", "");
    head.append(aiBadge(copy, result), aiEl("strong", "", ` ${copy.cause}: ${aiCause(copy, answer.primary_cause)}`));
    if (answer.secondary_cause) head.append(aiEl("span", "muted", ` (${copy.second}: ${aiCause(copy, answer.secondary_cause)})`));
    host.appendChild(head);
    const list = aiEl("ol", "");
    for (const step of answer.causal_chain || []) list.appendChild(aiEl("li", "", step));
    host.appendChild(list);
    host.appendChild(aiEl("p", "", `${copy.lever}: ${answer.lever || "—"} (${copy.adviceOnly})`));
    host.appendChild(aiEl("p", "muted", `${copy.calls}: ${(answer.calls || []).map((c) => c.tool).join(" → ")}`));
    if ((answer.trace || []).length) {
      const steps = aiEl("details", "muted");
      steps.appendChild(aiEl("summary", "", `${copy.steps} · ${copy.stop}: ${answer.stop_reason || "—"}`));
      const stepList = aiEl("ol", "");
      for (const step of answer.trace) stepList.appendChild(aiEl("li", "", `${step.action || "—"} · ${step.status || "—"}`));
      steps.appendChild(stepList);
      host.appendChild(steps);
    }
    host.appendChild(aiFact(copy, answer.fact_ok, answer.fact_misses));
    host.appendChild(
      aiEl("p", "muted", `${copy.truth}: ${aiCause(copy, result.truth)} · ${copy.baseline}: ${(result.baseline || []).map((x) => aiCause(copy, x)).join(", ")}`),
    );
  },
});

