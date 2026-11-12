// Explanation page: why one late lot is late. Advice only.

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
        AI.out.explainer = await aiPost("/api/ai/explain", { lot_id: select.value, seed: 1, lang: state.lang || "ja" });
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
    renderReplay(host, copy, result);
  },
});

