# Fab notes dataset (`fab_notes.json`)

Synthetic-but-realistic short fab notes with hand-labeled gold events, for the
Plan-2 core feature "text notes -> structured events"
(`resilimes/insight/notes.py`, scored by `scripts/score_notes.py`).

## Composition

- 46 notes, 48 gold events. Sources: maintenance 13, planning 12,
  engineering 11, shift 10.
- Languages: English 31, Chinese 8, Japanese 7.
- Event types: `planned_down` 20, `priority_change` 11, `hold` 8,
  `capacity_derate` 9. Three notes are deliberate zero-event traps
  (a past-tense recap, a negated hold, a "back to full capacity" note).
- 13 notes carry `hard_for_regex: true`: spelled-out numbers, combined units
  (`2h45m`), fractions (`two-thirds`, `half speed`), implicit downtime
  wording, pronouns sharing an earlier subject, relative/spelled clock times,
  and the negation/past traps. They exist to measure the gap a language model
  is supposed to close; the regex baseline's recall on this subset is 0.0.

## Naming (real names only)

Gold equipment/lot names come from this repository's own data, never invented:

- SMT2020 station families and tools from `data/smt2020/tool.txt.1l`
  (tools are named `f"{family}-{n}"` by `resilimes/smt/fab.py`), e.g.
  `Litho_FE_92-1`, `Diffusion_FE_94-2`, `Dielectric_BE_28-1`, `Implant_91`.
- SMT2020 WIP lots use the simulator-generated `Init_Lot_<product>_<n>` form
  (e.g. `Init_Lot_2_13`, the tight-book spotlight lot in the tests).
- Sample-bay names from `data/sample/` are used for the six-lot bay:
  equipment `LITHO-01`, `LITHO-02`, `ETCH-01`, `ETCH-02`, `CMP-01`, `DEP-01`,
  `MEAS-01`, `WET-01`; lots `LOT-1001`..`LOT-1006`; route steps `DEP`,
  `LITHO`, `MEAS`, `ETCH`, `CMP`, `CLEAN` (incl. `-L2` variants).

## Gold annotation rules

- All notes carry a UTC timestamp `ts` on the scenario day 2026-10-22;
  relative expressions ("tomorrow", "in 6 hours", "今晚十点") are resolved
  against `ts`.
- `planned_down.start` is the resolved absolute ISO UTC time;
  `duration_min` is total minutes (combined units are summed: `2h45m` = 165).
- `priority_change.new_due_h` is hours from the note's `ts` to the new due
  time (rounded to 2 decimals). `priority` is one of `vip|hot|normal`.
  A note may carry either field or both, never neither.
- `hold.reason` uses the closed vocabulary of `resilimes/insight/notes.py`
  (`material_shortage`, `quality_review`, `customer_request`, `metrology`,
  `equipment`, `other`). A lot hold may also name the `step` it is held at.
- `capacity_derate.factor` is the fraction of normal capacity that remains
  (70% -> 0.7, "two-thirds speed" -> 0.67); `window_h` is how long the derate
  lasts from the note's `ts`.
- Only future, actionable instructions are events. Completed/past work,
  negated instructions and status recaps have empty gold.

## Scoring

`python3 scripts/score_notes.py` prints per-type precision/recall for the
regex baseline and the (offline, scripted) LLM pipeline, after the
fact-check layer (`validate_events`). Measured on this dataset:

| extractor | precision | recall | plain recall | hard recall |
|---|---|---|---|---|
| regex baseline | 0.973 | 0.750 | 1.000 | 0.000 |
| llm (scripted stand-in) | 1.000 | 1.000 | 1.000 | 1.000 |

The scripted stand-in is a deterministic offline completer written against
these constructions — it proves the pipeline, not live-model quality. A live
Nightshift run is future work.

## A/B/C schedule comparison

`python3 scripts/compare_notes_ab.py` runs the evaluation arms defined in
`resilimes/insight/notes_ab.py`: A = no notes, B = extractor events after
validation, C = gold events. Fixed reporting caliber:

- **Headline: gap closure (A-B)/(A-C)** on avoidable Q-time violations
  (`n/a` when A=C).
- **Collateral damage (target 0)**: B events that took effect but match no
  gold event, plus avoidable violations B added over A — reported separately.
- Per-type extraction precision/recall for both extractors on this same set.

Offline it runs on a mock ledger runner (deterministic, labeled MOCK in the
report — ledger units, not fab results): scripted B closes 1.0 of the gap
with 0 collateral; regex B closes 0.7069 with 1 collateral event. The live
runner (real `run_policy` wiring) is supplied on the owner's machine as
`resilimes/insight/notes_ab_live.py` and selected with `--runner live`.
