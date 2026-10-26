# Fab notes panel (Plan-2 demo UI)

Read-only demo surface for the Plan-2 notes pipeline in the console's AI tab:
the `fab_notes` dataset, what the extractor makes of each note, what the
fact check lets through (and what it blocks, with the reason), each note's
hand-labeled gold, and the A/B/C comparison summary once that run exists.

## Endpoint

```
GET /api/ai/notes?extractor=scripted|live|regex&limit=1..46
```

Response:

```json
{
  "enabled": true,
  "extractor": "scripted" | "live" | "regex",
  "mocked": true,
  "limit": 46,
  "truncated": false,
  "summary": {"notes": 46, "accepted": 48, "rejected": 0, "gold_events": 48},
  "notes": [
    {
      "note_id": "n01",
      "ts": "2026-10-22T05:30:00Z",
      "source": "maintenance",
      "lang": "en",
      "hard_for_regex": false,
      "text": "…",
      "events": [{"type": "planned_down", "equipment": "…", "start": "…", "duration_min": 360}],
      "rejected": [{"event": {"…": "…"}, "reason": "unknown equipment '…'"}],
      "gold": [{"type": "planned_down", "…": "…"}]
    }
  ],
  "comparison": null
}
```

- `extractor=scripted` (default) drives `LlmExtractor` with the offline
  `ScriptedNotesCompleter` — the full prompt → JSON → validate pipe, no
  network, always labeled `mocked: true`.
- `extractor=live` uses the configured Nightshift provider and labels
  `mocked: false`, `extractor: "live"`. If no live model is configured the
  endpoint falls back to scripted and **says so** in the response
  (`extractor: "scripted"`, `mocked: true`) — it never relabels scripted
  output as live. Live extraction is serial (one model call per note), so
  pass a small `limit` for a live spot check.
- `extractor=regex` is the honest keyword baseline.
- `comparison` is the verbatim `comparison` block (plus `b_extractor`) of
  `outputs/notes_ab.json` as written by `scripts/compare_notes_ab.py`
  (path override: `RESILIMES_NOTES_AB_JSON`). It is `null` until that run
  has been executed; the panel then states that the live comparison has
  not run instead of showing invented numbers. When the report came from
  the mock ledger runner (`is_mock: true`) the panel flags the numbers as
  a pipeline demo, not fab results.
- Every note carries the stable `note_id` (`n01`…`n46` from
  `data/notes/fab_notes.json`); context-investigation citations can
  reference notes by this id.

## Switch and missing data

`RESILIMES_NOTES_PANEL` — default `1` (enabled). Set to `0` and
`GET /api/ai/notes` returns 404; the panel section then says that no notes
data is available (`ai.ntUnavailable`) and nothing else changes. The same
message appears if the request fails for any other reason (with the status
in brackets) or if the response has no notes. The endpoint is read-only and
additive: no existing route, KPI or scheduling path is touched, and extracted
events are displayed only — applying them to a schedule stays with the A/B/C
comparison runner.

## Contract

The route is the one merged in #62 (`resilimes/api/insight.py`, `fab_notes`).
The panel lives in `resilimes/demo/static/ai.js` (section `id: "notes"`), with
copy keys `ai.nt*` in `i18n.json` (en/zh/ja) and styles `.nt-*` in
`styles.css`. `tests/test_notes_panel_contract.py` pins every field the panel
reads (`data.*`, `summary.*`, `note.*`, `cmp.*`, `arm.*`, `collateral.*`) to
the fields the route returns, checks every `copy.*` key exists in all three
languages, and checks the graceful paths above are wired.

## Live numbers (owner's machine only)

1. `python3 scripts/compare_notes_ab.py --runner live` runs the arms on the
   real simulator with scripted extraction and writes `outputs/notes_ab.json`;
   the panel reads that file by default.
2. `python3 scripts/run_notes_ab_live.py` is the same comparison with the B
   arm on the live Nightshift model; it writes `outputs/notes_ab_live.json`
   (same `comparison` block). To show it in the panel, start the console with
   `RESILIMES_NOTES_AB_JSON=outputs/notes_ab_live.json`.
3. Spot-check real extraction with
   `GET /api/ai/notes?extractor=live&limit=5` against the running console
   (Nightshift on `127.0.0.1:8088`); the chip must read live, not offline.
4. `python3 scripts/score_notes.py` for the extraction precision/recall
   report (regex baseline kept on the same set).
