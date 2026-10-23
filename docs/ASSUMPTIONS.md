# Assumptions about sponsor APIs

These are the contracts we could confirm from public docs, and the choices we made where the docs do not pin a byte-level format. The code sits behind `ZetarisSource`, `NightshiftProvider`, and the engine classes, so a correction is a local change.

## Zetaris

Confirmed from the scaffold, the Zetaris knowledge base article on pipeline scheduling, and the Zetaris getting-started client guide:

- Direct REST base ends in `/api/v1.0`. The web UI origin is a different URL.
- SQL runs as `POST` with JSON `{"sql": "..."}`.
- Headers are `Authorization: Bearer <api key>`, `X-Org-ID` (numeric organisation id), `X-Request-ID` (fresh UUID), and `Content-Type: application/json`.
- A documented success shape is `{"headers": [...], "data": [[...]]}`. `rows_as_dicts` also accepts `columns`/`rows`, a list of objects, and a body wrapped in `result`.
- The knowledge-base example path is `/sql-editor/sqls/run-query`. The scaffold default, which this repo keeps, is `/sql-editor/sqls/run`. Set `ZETARIS_SQL_PATH` to the path your tenant returns 200 for.
- Organisation id comes from Management → Organisation → ID.

Not confirmed, so we did not depend on it:

- Whether `CREATE TABLE` is allowed in every Lightning tenant. `data/sql/seed.sql` uses ordinary `CREATE TABLE` plus `INSERT`, with every column as `VARCHAR(256)`. If the editor rejects that DDL, register `data/zetaris/*.csv` as tables with the same names and set `ZETARIS_SCHEMA`.
- The database name. We use `resilimes` unless `ZETARIS_SCHEMA` overrides it. The value must match `^[A-Za-z_][A-Za-z0-9_]*$`.
- Extra response envelopes beyond `result`. If a tenant wraps rows differently, extend `rows_as_dicts` only.

Reads on the recovery path are `SELECT` only. The load script is explicit and off by default.

## Meterless Nightshift

Confirmed from the Meterless provider contract published on the engines page and the Nightshift product docs:

- Default base URL `http://127.0.0.1:8088/v1`.
- OpenAI-compatible `POST /v1/chat/completions`.
- Bearer runtime token from `<stateDir>/proxy-token`. The placeholder `rt-local` is rejected.
- Header `meterless-app` is a stable lowercase app id. Chat also sends `meterless-scope: user`.
- Model ids may be concrete models or `meterless/*` routing modes. `GET /v1/models` is how you discover them. `GET /healthz` only means the process is up.
- A pasted URL may include `/v1`, `/v1/chat/completions`, `/v1/models`, or `/healthz` and must normalize to `<origin>/v1` exactly once.
- First-call timeout of 180 seconds, because a model load can be slow.
- 429 retries with backoff. This client uses 0.5s, 1s, and 2s across three attempts.

Assumption: the Nemotron id installed for the hackathon is passed in `NEMOTRON_MODEL`. The default `nvidia/NVIDIA-Nemotron-Nano-9B-v2` matches the scaffold. The Meterless model library also lists Nemotron 3.5 Lightning and Nemotron 3 Nano. Use whichever id your Nightshift `/v1/models` list actually serves. We do not call `integrate.api.nvidia.com` directly. NVIDIA is reached through Nightshift, which is what the Academy FAQ requires.

Assumption: unknown JSON fields are not sent. Nightshift explains. The critic is deterministic code in `resilimes.domain.critique` and does not call a model, so there is no critic-model setting.

The explainer asks for a JSON object `{"narrative": "..."}`. If the server ignores `response_format`, the client parses the text and falls back to the deterministic narrative. We do not send `response_format` today, because support varies across OpenAI-compatible runtimes.

## Scout Intent

Source: `engines/scout-intent` in the Meterless repository. Status there is "implementation spec". `@meterless/scout` is not on npm and has no `src/`.

We implemented the public surface in Python:

- `decide({prompt, user, surface})` → intent, risk, tool plan, execution contract.
- `classify({prompt, surface})` → top candidates.
- `replan({parent, reason, state})` → new contract, same trace id, `parentId` set.
- Contract fields follow `docs/execution-contract.md`: `contractId`, `traceId`, intent, risk, `toolPlan`, `modelProfile`, scope, `issuedAt`, `expiresAt`, `registryVersion`, `policyPackVersion`, `signature`, `signedBy: "scout"`.
- Signature: `HMAC_SHA256(secret, canonical_json(contract_without_signature))`.
- Default TTL five minutes. Downstream engines refuse a missing signature, a bad signature, an expiry, a capability outside scope, and a high-risk contract with no approval.

Assumption, because the spec says "canonical JSON" and does not name RFC 8785: canonical form is UTF-8 JSON, keys sorted, separators `,` and `:`, `null` fields removed, floats rounded to 4 decimal places. Contract ids are ULIDs (48-bit time, 80-bit randomness, Crockford base32), monotonic within the process.

Assumption: a Guard result of `block` produces no contract. The spec's contract risk enum is `low | medium | high`. `block` is a guard outcome, not a signed plan.

Assumption: plant data is a sensitive class, so Recommend only selects profiles with `local: true` and `plant` in `dataClasses`. The shipped catalog has a mock profile and two Nightshift Nemotron routing labels. The schedule critic does not call either label. Nightshift explains; `critique_schedule` commits.

The registry in `resilimes/engines/scout/intents.json` is the manufacturing catalog (machine down, rush order, material shortage, explain, status, emergency stop). It uses the spec's intent record: examples are mandatory, `riskClass` is a floor, `surfaces` and `roles` are enforced.

## World Model and Markovian

Source: the engine overview in the Meterless repository.

World Model, the parts the recovery uses:

- Append-only events are the source of truth.
- Ingest is idempotent: the same type, entity, payload, and idempotency key produce the same event id and do not append twice.
- Replay rebuilds entity state. There is no second store.
- Schema version is on each event (`schemaVersion: 1`).

Not built: the spec's browser control plane for merge and repair, content-addressable alias merges, and derived graph indexes beyond the entity map. The ResiliMES console is the operator view of the schedule, not a general world-model admin UI.

Markovian, the parts the recovery uses:

- A chunk receives a compressed checkpoint, not the full history.
- Markers are `STATE_CHECKPOINT` and `TASK_COMPLETE`.
- A failed chunk does not abort the rest of the run.
- Token accounting reports flat checkpoint cost against quadratic history cost.

Not built: the reference TypeScript conformance runner and the marker strings inside a model completion. Our chunks are Python functions. The checkpoint is what would be sent onward. The compression rules are tested directly.

## Scheduling assumptions that affect the KPIs

- A tool processes one lot at a time. `max_wip` is the simultaneous limit, so a non-overlapping plan is legal when `max_wip >= 1`.
- Setup time is charged on a family change. The family already on the tool at the horizon is unknown, so the first lot pays no setup.
- Lots running on an up tool are not preempted.
- Material on the BOM is consumed when a lot that has not started is dispatched. In-progress lots have already consumed theirs.
- A down tool's `available_at_min` is the repair ETA from the horizon when a scenario sets `eta_from_horizon`. Otherwise it is `down_since + latest maintenance estimate`, or 240 minutes if nothing is known.
- A held lot has no completion. It counts as late for on-time delivery and, at priority 1 or 2, as a lot at risk. Weighted tardiness does not charge it a finish time.
- Priority weights are 8, 4, 2, and 1 for priorities 1 through 4.

The litho headline (83.3% → 100% on-time, weighted tardiness 784 → 0) depends on the 600-minute revised ETA in the machine-breakdown scenario. The maintenance log's older estimate of 180 minutes is not what that scenario uses. The narrative says the ETA was revised. DEP-01's morning PM is in that log and is complete by 06:20, so the tool is up at the scenario clock and the routes use it.

Each lithography layer has two physical reticle copies. A copy is mounted on one scanner at a time. The first mount, and any later move onto a different scanner, takes 5 minutes inside the scheduled interval. The same scanner keeps the copy for the next lot with no extra load. On the rush book the running lot keeps RET-A28-L1-1 on LITHO-01, and LOT-2001 takes RET-A28-L1-2 on LITHO-02. The hot lot finishes 36 minutes late because the rest of the route still passes the three-hour due. The scale fab uses the same rule: two copies per product-layer, ids `RET-{product}-{layer}-1` and `RET-{product}-{layer}-2`. The 15-minute queue-time scenario holds LOT-1003, whose clean ended before the clock. LOT-1006 still reaches its cap film inside the window. A lot may not start before `release_min`. The sample value is 0. An inhibit row keeps a product or a recipe off one tool. PROD-C07 stays off LITHO-01. The lot on the clock is already at CMP, so that inhibit does not move today's sensor lot.

Each PROD-A28 layer is deposition, one lithography step (coat, expose, and develop), overlay and CD metrology, etch, one wet clean (strip plus rinse), and CMP. L2 repeats the loop. Rework of a failed measure is strip, one re-expose, and one re-measure. The counted pass is the re-measure.

The Scale preset is a seeded synthetic fab (`seed` 20261022), not a second copy of the six-lot bay. It has 1,000 lots and 36 tools, one operator per tool, so staffing does not search. A lot is released only through the end of its current layer. The same catalog columns are written to `data/sql/scale_seed.sql`. Furnace batching, implant, metal PVD, and AMHS stay out of scope on this fab too.

The scale baseline is EDD dispatch. It orders ready steps by due date, then by the minute they become ready, and places each step on the qualified tool that can start soonest. It does not use priority weights or the bottleneck. On the seeded book that rule already finishes every lot on time (on-time delivery 100%, weighted tardiness 0, lots at risk 0). Priority recovery matches those three figures. It cuts mean inter-step wait from 389 minutes to 125 and lengthens makespan from 4,522 minutes to 5,116. The five-minute reticle mount is inside those figures. The hero scenarios still compare a frozen book with the recovery.

CP-SAT is a reference. The committed book stays the list scheduler. CP-SAT models the same rules the critic checks, including sequence-dependent setup (the first lot on a tool pays none), one scanner per physical reticle copy, and the same hold rule as the KPI: a lot is left unfinished only when completing it is infeasible, and that hold adds no weighted tardiness. Hero scenarios get up to five seconds and report OPTIMAL or FEASIBLE with the bound. The scale fab gets a two-second neighborhood around late lots and the makespan-setting lot, hinted from the list schedule. On the seeded book that neighborhood does not shorten the list schedule, so the badge keeps it. A candidate that fails the critic is discarded. The list schedule is always computed first, and the KPI cards use it.

## Production would add

These are real fab constraints and they are out of this demo:

- Furnace batching
- Implant
- Metal PVD
- Transfer and AMHS capacity
- Conditioning dummy wafers
- Cumulative maintenance counters
- Interval setups
- Tact time
- Cross-fab flow restrictions
- Pilot and split lots
- MES-specific compliance checks
