# Claim ledger (claim/v0)

The fact-check gate (`resilimes/explain/factcheck.py`) rejects an explanation
whose numbers or ids are not in the evidence. The claim ledger is what the
gate leaves behind: one record per quoted value, so a later review can ask
"which number was claimed, in which sentence, and did it check out?" without
re-running the explainer. It answers that question only; it does not record
which run produced the explanation, which model said it, or what the registry
contained at check time (see Limits).

## Model

- `Claim`: one quoted value.
  - `claim_id`: deterministic (`claim-<sha256[:12]>` of kind + value +
    statement), so the same quotation always gets the same id. The id
    identifies a quotation, not one claim in one run: the same sentence in
    another lot or run gets the same id, and its result there can differ.
    Do not use it as a cross-ledger key.
  - `kind`: `number` or `id`.
  - `value`: normalised — numbers via `common.textfacts._norm` (`120.0` →
    `120`), ids upper-cased (`Lot-1` → `LOT-1`).
  - `statement`: the sentence the value was quoted in. One claim per
    quotation: the same number in two sentences is two claims; twice in one
    sentence is one claim.
  - `sources`: evidence row references (e.g. `lateness.while_late_min`),
    supplied by the caller, ledger-wide for now (see limits). When the text
    yields no claims, `sources` has nowhere to be recorded.
  - `result`: `passed` | `failed` | `unchecked`. `unchecked` is only for
    claims recorded by hand when no registry was available at audit time;
    `build_ledger` never produces it, and an `unchecked` claim must carry a
    `reason`. A `failed` claim carries the gate's miss text as its `reason`
    (e.g. `unknown number 999`).
  - `checked_at`: ISO 8601 UTC timestamp of the check (validated on
    construction).
  - `reason`: why unchecked, or the gate's miss text on a failure.
- `ClaimLedger`: `ledger_version` (`claim/v0`, locked with `Literal`),
  `subject` (e.g. the lot id), `source` (what produced the text, e.g.
  `explainer`), `claims`, `content_hash` (`sha256:<hex>` over the canonical
  JSON without the hash and without `checked_at`, same pattern as Evidence
  Schema v0). `sealed()` / `verify()` mirror `EvidenceBundle`.

## Generation

- `build_ledger(text, registry, *, subject, source, sources, checked_at)`:
  extracts every claimed number and id from plain text and checks each one.
  The result of every claim is derived from the gate's own misses
  (`factcheck.check`), so the ledger can never disagree with the gate on the
  same text.
- `ledger_for_explanation(explanation, registry, *, sources, checked_at)`:
  builds a ledger for an `Explanation` (explanation text plus its claim
  sentence), with the lot id as subject and `explainer` as source. It
  reproduces the registry the gate actually used: the explainer adds the
  counterfactual's `expected_saving_min` and the lot id to its registry copy
  before checking, so a claim sentence quoting the saving passes here exactly
  as it passed the gate. The saving itself is the model's own estimate and is
  never quoted as a claim unless the text says it; verifying it is
  `verify_counterfactual`'s job, and the re-run result is not part of this
  ledger.

Extraction follows the gate's own rule for what counts as a claim: an
id-shaped token only counts when it carries a digit (`Diffusion_FE_120`,
`Lot-1` count; `tool-hours`, `re-run` are prose and are not recorded).
Counting words 0–10 are always allowed by the gate and are recorded as
passed when they appear as digits. Numbers are taken exactly as the gate
sees them, including digits inside an id: `Lot-1` also quotes the number 1,
and `Diffusion_FE_120` also quotes 120. The ledger's `total` therefore
counts quotations, not distinct data values; do not use it as a denominator
for a rate without accounting for that.

## Query

- `failed()` / `passed()` / `unchecked()`: claims by result.
- `by_value(value, kind=None)`: all claims quoting that value. The query is
  normalised like storage: `by_value("Lot-1")` and `by_value("120.0")` hit
  the stored `LOT-1` and `120`.
- `summary()`: counts only (`total` / `passed` / `failed` / `unchecked`).
  Rates belong to the quality module (`explain.quality`), not the ledger.

## Limits of v0 (declared, not hidden)

- `sources` are ledger-level. Per-claim source attribution (which evidence
  row a value came from) needs `FactRegistry` to record provenance, which it
  does not do yet. That is a later increment.
- The ledger records what was quoted and whether it checked out. It does not
  record which run produced the explanation (no seed / horizon / policy /
  label), which provider or model said it, when the explanation was
  generated, or what the registry contained at check time. `content_hash`
  covers the ledger only, not the evidence it was checked against. An audit
  that needs that binding has to keep the explanation and its evidence bundle
  next to the ledger. Recording the run reference and a registry fingerprint
  is a later increment.
- The ledger is an adapter: nothing in `explain()` writes to a ledger yet.
  Wiring it into the explainer flow (so every explanation leaves a ledger
  behind) is a separate decision, proposed in the PR that introduced this
  module.
- A failed claim is a named misattribution. The ledger is not yet wired to
  any consumer: no report or page shows it, and the quality metrics do not
  read it yet.
- Shared blind spots with the gate (the ledger follows the gate's rules, so
  it shares them): sentence splitting protects only `e.g.` / `i.e.` /
  `etc.` / `Fig.` / `vs.`; a thousands separator splits a number (`1,200`
  becomes claims for `1` and `200`, and `000` can be recorded as failed
  even when `1,000` was correctly quoted); an id that starts with a digit
  (`3M_Lot_9`) or mixes hyphen and underscore (`Diffusion_FE-120`,
  `Lot-1_FE_2`) is invisible to both the gate and the ledger — a forged id
  of those shapes is not recorded at all, which the ledger must not be read
  as "passed". These are gate-level gaps in `common/textfacts.py` and
  `explain/factcheck.py`; fixing the extraction patterns is a separate
  proposal, not part of this increment, because it changes what the gate
  itself accepts.
- `content_hash` covers what was claimed and the verdicts, not `checked_at`
  (so the same text and registry always build the same hash). It is a
  self-consistency check, not a signature: anyone who can rewrite the ledger
  can recompute it.

## Version rule

`claim/v0`. Changing a field, a result value or the extraction rule is a new
version, not an edit. Contract tests: `tests/test_explain_claims.py`.
