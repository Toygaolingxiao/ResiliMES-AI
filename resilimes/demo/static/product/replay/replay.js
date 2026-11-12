// Replay page: the what-if line on a late-lot explanation.
// Advice only. The numbers come from the re-run in the explain response.

function renderReplay(host, copy, result) {
  const cf = result && result.counterfactual;
  if (!(cf && cf.verified)) return;
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
