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

## Switch

`RESILIMES_NOTES_PANEL` — default `1` (enabled). Set to `0` and
`GET /api/ai/notes` returns 404; the panel section then shows the fetch
error and nothing else changes. The endpoint is read-only and additive:
no existing route, KPI or scheduling path is touched, and extracted events
are displayed only — applying them to a schedule stays with the A/B/C
comparison runner.

## Tonight on the owner's machine (live numbers)

1. `python3 scripts/compare_notes_ab.py --runner live` (needs
   `resilimes/insight/notes_ab_live.py` with `build_runner()`) → writes
   `outputs/notes_ab.json`; the panel's A/B/C block then renders the real
   gap closure, collateral counts and per-arm violations.
2. Spot-check real extraction in the panel by calling
   `GET /api/ai/notes?extractor=live&limit=5` against the running console
   (Nightshift on `127.0.0.1:8088`); the chip must read live, not mocked.
3. `python3 scripts/score_notes.py` for the extraction precision/recall
   report (regex baseline kept on the same set).
