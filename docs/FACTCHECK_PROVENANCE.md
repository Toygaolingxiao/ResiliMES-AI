# FactRegistry provenance (provenance/v0)

## What it is

The fact-check gate (`resilimes/explain/factcheck.py`) already rejects an
explanation whose numbers or ids are not in the evidence. What it never
recorded is *where* each registered value came from — which tool result,
which question, which run record supplied it. Provenance is a first step
toward that record: an optional, caller-supplied source label attached to
a value at registration time.

What the map delivers is **per-value candidate source labels at
whole-payload granularity, in first-seen order** — not per-occurrence,
per-row attribution. A value seen in two sources carries both labels; a
label means "this value appeared in that source", not "that source
supports the quantity being claimed". Labels are caller-supplied and
**not verified**: quote them as "reported source", never as a verified
fact. `provenance()` carries no hash or seal, so it must not be
presented to an auditor as verified provenance until the
registry-fingerprint increment lands.

The claim ledger consumes this map (`docs/CLAIM_LEDGER.md`). Policy,
fixed there and in `tests/test_explain_claims.py`: list every label in
first-seen order, then any caller-wide labels, without dropping
duplicates or picking a winner. Digits that only occur inside an id
token stay unattributed (`sources()` is `()`). Counting words 0–10 are
not special-cased. `explainer.py` and `ledger_for_explanation` copy the
registry with `copy()` before they add the expected saving and the lot
id.

## Contract: provenance/v0

- `FactRegistry.add_text(text, *, source=None)`,
  `add(payload, *, source=None)`, `add_ids(ids, *, source=None)` accept
  an optional keyword-only `source` label. `source` is keyword-only so a
  second positional argument can never be misread as a label.
- `sources(kind, value) -> tuple[str, ...]` returns the labels recorded
  for one value, first-seen order, deduplicated; `()` when the value was
  registered without a source or not registered at all. `kind` is `"id"`
  or `"number"` (case-sensitive; anything else raises `ValueError`). The
  value is normalised exactly as registration normalises it (ids
  upper-cased, numbers via `common.textfacts._norm`, surrounding
  whitespace stripped), so `sources("id", "init_lot_3_17")` finds a value
  registered as `"Init_Lot_3_17"`, and `sources("number", "42.0")` finds
  `"42"`. A non-string value raises `TypeError`.
- `provenance() -> {"ids": {...}, "numbers": {...}}` returns a JSON-ready
  snapshot with sorted keys (a copy; mutating it never touches the
  registry). Values without a recorded source are omitted.
- A source label is stored stripped: `"tool:a "` and `"tool:a"` are the
  same source, and a trailing newline is stripped away rather than
  stored. It must be a non-empty string of at most 200 characters
  containing no control characters after stripping (Unicode categories
  Cc/Cf, so an interior tab or a zero-width character is rejected): a
  non-string raises `TypeError`, an empty/whitespace-only label, a
  label with a control character, or an over-long label raises
  `ValueError`. A rejected call registers nothing, and `add()`
  validates the label before serialising the payload.
- **The gate never reads provenance.** `check()`, `number_known()` and
  `facts()` behave identically with and without sources (pinned by
  `test_gate_is_unchanged_by_provenance` and
  `test_gate_parity_includes_number_known`). A value added without a
  source is registered exactly as before, with empty provenance.

## What counts as a number's source — and what does not

- Digits that only occur **inside an id token** are registered as
  numbers by the gate, but carry **no** number provenance:
  `add_text("Init_Lot_3_17 waited 42 min.", source="tool:a")` records a
  source for `"42"` and for the id, but not for `"3"` or `"17"`. A later
  claim quoting `"3"` therefore reads `()` — correctly, because no row
  contained `3` as a standalone datum. (The ledger already documents
  that `Lot-1` also quotes the number `1`; the attribution increment
  must treat such claims as unattributed, not as failed.)
- A number that occurs both inside an id and standalone in the same
  text does get a source.
- `add()` JSON-dumps the whole payload before scanning, so one label
  covers every value inside it — including dict keys and fragments of
  float exponents (`1e20` yields `1` and `20`) — and cannot name a row
  within it. Row-level attribution requires per-row `add_text` /
  `add_ids` calls; `add()` on a whole payload is whole-payload
  granularity by construction.
- Numbers `0`–`10` are always allowed by the gate regardless of
  evidence. The ledger does not drop them: a source recorded for one
  (e.g. `"5"` from `"5 lots."`) is quoted like any other reported
  label. It is still a counting word, not a measured quantity.
- Leading zeros are a known `_norm` limit, inherited from the gate:
  evidence containing `042` registers `"042"`, and
  `sources("number", "42")` returns `()`. Fixing `_norm` would change
  gate behaviour, so it is a separate change, not part of this
  increment.
- An empty-string id is still registered (gate behaviour, unchanged)
  but never carries provenance.

## Copying a registry

Copy a registry through `FactRegistry.copy()`, which copies `ids`,
`numbers` **and** `_provenance` (source lists deep-copied). Rebuilding
one by copying only `ids`/`numbers` silently drops provenance.
`explainer._explain` and `ledger_for_explanation` both use `copy()`.
`build_ledger`'s `sources` argument is the caller-wide label tuple; the
lookup method is `registry.sources`, called from `_sources_for`, so the
parameter does not shadow the method.

## Source labels

Labels are free-form strings, caller-supplied and **not verified** — the
registry trusts that the caller names the real origin. Suggested shapes
for future call sites (only the first two are realistic today; the third
is speculative — see below):

| Caller | Label shape |
| --- | --- |
| `explain/toolkit.py` tool results | `tool:<name>` (the tool name is available in `Toolkit._out`) |
| `explain/explainer.py` / `investigator.py` question | `question` |
| `evidence/adapters.py` run records | `run:<label> row:<ref>` — **speculative**: no call site has a row concept today, `evidence/` never touches a registry, and `adapters.py`'s `record.ref` is a run-level reference, not a row. Row-level attribution requires restructuring registration into per-row calls — a design decision for the wiring increment, not something this map already enables. |

Do not invent a label for a value whose origin is unknown: register it
without a source and let it stay unattributed. A forged-looking label is
worse than an empty one, because the ledger will quote it as evidence.

## What this increment does not do

- **No row-level labels.** Call sites now pass a reported source
  (`tool:<name>`, `tool:sql`, `question`, `context:*`, `gap:facts`,
  `explainer:expected_saving_min`, `explainer:lot`, `handover:*`,
  `deliberation:*`). `add()` on a whole payload is still one label for
  every value in it. A label built from data must be valid at
  construction: a bad label raises out of the explain path instead of
  degrading to unattributed registration (fail-closed).
- **No registry fingerprint.** Binding a ledger to the exact registry
  contents it was checked against (a hash of the registry, as named in
  `docs/CLAIM_LEDGER.md`) is a later increment.
- **No claim version change in that increment.** The ledger reads
  `sources()` and keeps every label. The claim field set was unchanged,
  and a registry with no provenance still produces the previous
  caller-wide `sources` tuple. (The ledger later moved to claim/v1 for
  an extraction-rule change; its field set is still unchanged.)
- **No verification of labels.** A label is a claim about origin, not
  proof of it. The ledger quotes labels as "reported source", never as
  a verified fact.

## Tests

`tests/test_explain_factcheck_provenance.py` (36 contract tests):
registration with source on all three `add_*` paths, normalisation,
first-seen order and dedup, unattributed registration, id-interior
digits, rejected sources (empty / control character / over-long /
non-string, validated before serialisation), keyword-only `source`,
`copy()` preservation and independence, kind namespacing, gate parity
(`check` and `number_known`), snapshot copy, JSON round-trip and sorted
keys, empty-id handling. The standalone package carries one boundary
test
(`packages/resilimes-explain/tests/test_standalone.py::test_fact_registry_provenance_round_trip`).
