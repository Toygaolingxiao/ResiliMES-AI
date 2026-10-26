# Stress-set protocol amendment — 2026-10-26 (before any live run)

This addendum does not modify `docs/STRESS_GEN_PREREG.md`. It records what
the pre-registered validation found, and the one protocol change made —
and declared — before the live C-arm run.

## What the pre-registered validation found

The registered selection rule was: a scenario joins the live run set iff
the no-AI gate run under the **shipped** escalation mode (`exception`)
escalates at least once. Result (`study_stress_gen/validation.md`,
2026-10-26): **16/16 validated, 0 triggered, 16 excluded.** Across the 16
scenarios the gate evaluated 60–84 exceptions each and escalated none.
Together with the zero-call study (58 exceptions, 0 escalations on the
published book), the shipped gate — escalate only when the rule default's
twin projection (mean over futures) shows an avoidable Q-time violation or
a late hot lot — essentially never fires on SMT2020-derived data. That is
a finding about the shipped system's reach, and it is reported as one in
the deck: the AI actuation path is nearly unreachable under the shipped
gate on this data.

## The amendment

For the B-vs-C comparison only, the escalation mode is the study mode
used by the K-curve (flat — no headroom on this book; `SHIFT_LEAD_ESCALATE=always`, the legacy kind
filter). The shipped gate is not changed; nothing about the product
default changes. Under this mode the same validator (same scenarios, same
fork/futures/horizon/seed) reports **16/16 triggered**, with 35–49
escalations per scenario (`study_stress_gen_always/validation.md` — its
header text says "exception mode" because that string was hardcoded in
the validator at the time (the validator now records and prints the mode
from `SHIFT_LEAD_ESCALATE`); the run itself was made with
`SHIFT_LEAD_ESCALATE=always`, git_commit a52671c, and the zero gate-check
counts in its table confirm no gate projection ran).

## Tonight's run set and command

All 16 scenarios, arms A/B/C as registered, same metrics (Q-time-first
lexicographic), same budgets (K=3, max 3 plans). The live script reads its
escalation mode from the environment, so it must be invoked as:

```
SHIFT_LEAD_ESCALATE=always python scripts/run_stress_live.py --validation study_stress_gen_always/validation.json
```

The live report must state both trigger facts side by side: 0/16 under
the shipped gate, 16/16 under the study escalation used for the run.
