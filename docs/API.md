# Dispatch API

Nemotron does not compute a schedule. It returns one tool call. This service validates that call, Scout signs it, and a later confirm runs the transactional operation. The scheduling branch owns the real database transaction and the optional Redis `StateStore`. This repository ships the interface and an in-memory default. It does not edit `schedule_plant`.

## Tool call

One JSON object. `validation_rules` is the same on every intent.

```json
{
  "intent": "insert_hot_lot",
  "parameters": {
    "lot_id": "LOT-9921",
    "target_station_group": "LITHO-03",
    "priority_override": true,
    "reason": "Engineering sample requested by customer urgent test"
  },
  "validation_rules": {
    "check_inventory": true,
    "notify_pe": "Yamamoto-san"
  }
}
```

`priority_override` is a boolean. `notify_pe` is a person's name. An empty string means nobody is named.

| Intent | Parameters |
| --- | --- |
| `insert_hot_lot` | `lot_id`, `target_station_group`, `priority_override`, `reason` |
| `move_pm` | `equipment_id`, `new_start_min` (0–10080), `duration_min` (1–10080), `reason` |
| `mark_tool_down` | `equipment_id`, `eta_min` (0–10080), `reason`, optional `fault_code` |
| `hold_lot` | `lot_id`, `reason` |
| `release_lot` | `lot_id`, `reason` |
| `what_if` | `question`, optional `equipment_id`, `lot_id`, `eta_min` |

`POST /api/intents` body: `incident`, `actor_id`, `actor_role`.

1. The injection guard runs on the raw text before any model call. A hit returns `status: rejected` and no contract.
2. Nightshift emits the tool call on lane `intent`. Mock mode, a transport error, or a schema failure uses the regex parser and sets `source` to `deterministic-fallback`. That path never claims the text came from Nemotron.
3. The schema is checked, then lot, equipment, and station-group ids are checked against the loaded plant. `LOT-9921` and `LITHO-03` are valid shapes and are rejected on the sample bay because they are not in the data. The error is `Unknown lot LOT-9921.` or `Unknown equipment LITHO-03.` A failure has `contract: null`.
4. Scout signs the mapped registry intent (`insert_hot_lot` → `plant.rush_order`, `mark_tool_down` and `move_pm` → `plant.machine_down`, `hold_lot` → `plant.hold_lot`, `release_lot` → `plant.release_lot`, `what_if` → `plant.explain`). The full tool call is stored beside the contract.
5. The response is `pending_confirmation` with `confirmation_id`, `call`, the public contract, `source`, and `meterless_request_id`. The plant is unchanged.

`POST /api/intents/confirm` body: `confirmation_id`.

1. The stored contract is verified again.
2. `check_inventory: true` runs the BOM check (material on hand versus `qty_per_lot`) before the change. A shortfall aborts. The plant is not saved.
3. `notify_pe` appends `{type, to, channel: "trace-only", sent: false}` on the response trace. Nothing is emailed or messaged.
4. The engine acquires a `lock_token` for the tools the change touches. A second acquire of the same tool fails with `LITHO-01 is already locked.`
5. The change is applied on a copy. `schedule_plant` re-dispatches. `critique_schedule` runs. A `reject` verdict aborts and does not keep the change. `what_if` always leaves `committed: false` and does not persist.
6. The response carries KPIs, affected lots, the critique verdict, business feedback, and the qualitative review panel. The lock is released.

Business feedback is lane `feedback`. Every number and lot or tool id in the model text is checked against the engine result. A mismatch or a raised call keeps the deterministic sentence, with `narrative_degraded: true` and `source: deterministic-fallback`.

A running lot on an up tool cannot be held. The error names the lot and the tool. The fix hint is to leave it in place.

## What the other branch implements

```python
class StateStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def compare_and_set(self, key: str, expected: str | None, value: str) -> bool: ...

class EngineTransaction(Protocol):
    def acquire_lock(self, equipment_ids: list[str]) -> MachineLock: ...
    def apply(self, lock: MachineLock, intent: dict, plant: Plant) -> TxnResult: ...
    def abort(self, lock: MachineLock) -> None: ...
```

`compare_and_set` is the lock. The in-memory default stores `lock:{equipment_id} = lock_token`. Redis `SET key value NX` is the same contract. `expected is None` means the key is absent.

`apply` is the database transaction. It must:

- run `check_inventory` before mutating, and roll back when stock is short
- record `notify_pe` in the trace only
- mutate the plant, re-dispatch with the public `schedule_plant`, and run `critique_schedule`
- commit only when the verdict is not `reject`
- leave `what_if` unpersisted
- release nothing itself; the caller calls `abort` in a `finally` to drop the lock. `abort` does not roll back a plant `apply` already committed.

`InMemoryEngine` in `resilimes/txn/engine.py` is the default. A held lot is removed from the returned book after dispatch, because this branch does not change the scheduler. `recover` already reads priority. `preferred_equipment` is written when the target tool can run a remaining step. A PM with `new_start_min == 0` sets the tool to `MAINTENANCE` until `duration_min`. A later start is recorded on the maintenance log and does not take the tool down yet.

The plant snapshot lives at key `plant`. Pending confirmations live at `confirm:{id}`.

## Qualitative review

Three reviewers, lanes `review.process`, `review.production`, and `review.risk`. Verdicts are `approve`, `approve-with-changes`, or `reject`. Concerns must cite real ids. A hallucinated id replaces that reviewer with the labeled fallback and keeps the request id. Aggregation is `unanimous`, `majority`, or `split`. The recommendation does not change the committed book.

The same panel is attached to `/api/recover` after the critic and before explain. It is not an extra Markovian chunk. The recovery loop stays five chunks. The refused alternative on that report is `label: "safety test"`.

## Privacy option

Nightshift can serve a local on-prem model under `NEMOTRON_MODEL` and keep these lanes: `intent`, `feedback`, `review.process`, `review.production`, `review.risk`, `explainer`. ResiliMES does not ship a second client. Nightshift remains the provider.

## What the console should render

Another branch owns the UI. Render these fields. Do not treat the safety-test refusal as a Nemotron round.

- Confirmation card before execute: the parsed `call`, validation rules, and Scout signature prefix. Status `pending_confirmation`, `rejected`, `executed`, or `aborted`.
- Validation errors verbatim (`Unknown lot …`, `Unknown equipment …`, `Prompt injection detected.`). No contract block when `contract` is null.
- `source == "deterministic-fallback"` as a visible banner on the intent, the feedback, and each reviewer. Show `meterless_request_id` when it is non-empty.
- `notify_pe` as a trace-only notice: the name, channel `trace-only`, and `sent: false`. Do not draw it as a sent message.
- `review_panel.reviewers` with role, verdict, concerns, suggestions, request id, and `hallucinated_ids`. Show `agreement` and `recommendation`, plus the note that suggestions do not change the book.
- KPIs, affected lots, and critic verdict from the confirm response. Feedback text, and a degraded banner when `feedback.narrative_degraded` is true.
- On `/api/recover`, `rejected_alternative.label == "safety test"`. Render `propose_loop.rounds` only when the list is non-empty. It is empty unless a live provider actually produced rounds.
