# Sponsor technology

ResiliMES uses Zetaris as the plant's data layer, Meterless Nightshift as the primary model provider with NVIDIA Nemotron behind it, and three Meterless engines. Scout Intent is the engine this submission claims. World Model and Markovian are wired behind the contract Scout signs, which is how the public engine stack is specified to compose.

Cursor was the development environment for the recovery loop, the console, the tests, and these docs.

## Which engine, and the test that shows it works

**Engine: Scout Intent** (`resilimes/engines/scout/engine.py`).

Scout is the gate in front of every recovery. The console does not reschedule from a raw sentence. It reschedules from a signed execution contract: intent, bound entities, risk, tool plan, model profile, scope, expiry, HMAC.

The test file is `tests/test_scout_engine.py`. Run it with:

```bash
pytest tests/test_scout_engine.py -q
```

What that file proves:

| Behavior | Test |
| --- | --- |
| "Machine Litho-02 Down" classifies as `plant.machine_down`, binds `LITHO-02`, and verifies the HMAC | `test_machine_down_classifies_and_signs` |
| Rush orders and material shortages classify and bind product or material ids | `test_rush_and_shortage_intents` |
| The rework and queue-time sentences classify at 0.92 or better | `test_rework_and_qtime_clear_the_floor` |
| Prompt injection yields `risk.level = block` and no contract | `test_prompt_injection_is_blocked` |
| A viewer cannot invoke a reschedule | `test_viewer_cannot_reschedule` |
| An emergency stop on a disallowed surface is blocked | `test_surface_is_enforced` |
| A mutated contract fails signature checks, and a contract past `expiresAt` is refused | `test_tamper_and_expiry_are_refused` |
| A high-risk contract with no approval is refused by the downstream verifier | `test_high_risk_without_approval_is_refused_downstream` |
| `replan` keeps the trace id and sets `parentId` | `test_replan_keeps_trace_and_sets_parent` |
| The deterministic trigger scan stays under 16 ms median | `test_trigger_scan_stays_under_16ms` |
| An intent with no examples is rejected at load | `test_registry_requires_examples` |
| Live mode selects a local Nightshift profile whose model id is a Nemotron | `test_live_profile_is_local_nemotron` |

`tests/test_recovery.py::test_orchestrator_litho_path_is_explainable` shows the same contract on the real feature: a machine breakdown produces a verified contract, five Markovian chunks, a world-model commit, and a tardiness reduction. `test_viewer_and_injection_do_not_commit` shows the guard on that feature.

The implementation follows the public spec at [engines/scout-intent](https://github.com/Meterless/Meterless/blob/main/engines/scout-intent/AGENTS.md). `@meterless/scout` is not a published package. Canonical JSON is specified as HMAC input but not pinned to an RFC. ResiliMES uses sorted-key compact UTF-8 JSON with nulls removed. That choice is in [ASSUMPTIONS.md](ASSUMPTIONS.md).

## How the other two engines are used

They are not extra demos. The recovery refuses to run without them.

**World Model** (`resilimes/engines/world_model/engine.py`) is the plant log. After the critic accepts, each tool observation and each lot assignment is ingested under the Scout contract. `world.sync` is required to observe, `schedule.commit` is required to assign, and a second ingest with the same idempotency key does not duplicate the event. Replay is how the report counts committed jobs. A payload field cannot overwrite the entity type, so a job assignment stays a job. Tests live in `tests/test_engines.py` (`test_ingest_is_idempotent_and_replayable`, `test_world_model_refuses_unsigned_and_out_of_scope`).

**Markovian** (`resilimes/engines/markovian/engine.py`) is the agent loop. Sense, plan, critique, explain, and commit are chunks. Each chunk receives a checkpoint. A raised exception stays inside its chunk. Transcript fields are dropped. The litho run reports checkpoint tokens against the quadratic cost of resending history (about 500 versus about 1600). Tests: `test_compress_drops_transcript_and_keeps_decisions`, `test_chunk_failure_is_contained`, `test_markovian_token_cost_stays_below_naive_history`, `test_markovian_refuses_a_contract_without_memory_write`.

A read-only "what is the fab status?" contract does not carry `memory.write`, so Markovian will not start a recovery from it.

## Zetaris

Zetaris is the system of record for equipment, WIP, routes, route steps, queue-time rules, BOM, stock, operators, and maintenance.

The client is the scaffold in `agent/tools_zetaris.py`:

- `POST {ZETARIS_REST_URL}{ZETARIS_SQL_PATH}`
- `Authorization: Bearer <ZETARIS_API_KEY>`
- `X-Org-ID: <ZETARIS_ORG_ID>`
- `X-Request-ID: <uuid>`
- Body: `{"sql": "<one statement>"}`

`resilimes/data/zetaris_source.py` issues one `SELECT` per table from `resilimes/data/sql_catalog.py` and builds the same `Plant` the scheduler uses. The schema identifier is validated so it cannot carry a second statement.

`data/sql/seed.sql` and `data/zetaris/*.csv` are generated from `data/sample` by `python scripts/export_zetaris_sql.py`. `tests/test_sql_export.py` fails if those files drift. `python scripts/load_zetaris.py --execute` sends the seed, one statement per request.

In mock mode the specialist still records those SQL strings and answers them from the sample files. The trace labels the mode `sample-equivalent`, so a recording does not imply a live warehouse call. `tests/test_recovery.py::test_zetaris_headers_and_row_shape` checks the bearer token, org header, request id, URL, and the `headers` + `data` row shape, including a body wrapped in `result`.

`python smoke_test.py` (no `--mock`) is the live probe: Zetaris web origin, `SELECT 1`, and a Nightshift chat completion.

## Meterless Nightshift and NVIDIA Nemotron

Nightshift is the only model provider on the live path. The client is `resilimes/llm/nightshift.py`, shared with `agent/llm.py`.

- Base URL normalized to `<origin>/v1`. A pasted `/v1/chat/completions` or `/healthz` does not become `/v1/v1`.
- `Authorization: Bearer <METERLESS_RUNTIME_TOKEN>`. The placeholder `rt-local` is rejected.
- `meterless-app: resilimes` and `meterless-scope: user` on chat calls.
- The explainer calls `NEMOTRON_MODEL`. Nightshift explains. The planner and the critic do not call the model. The critic is `critique_schedule`.
- Timeout defaults to 180 seconds. Rate limits and connection errors retry three times.
- Logs record lane, model id, and latency. They do not record the token.

The committed schedule does not come from the model. The model rewrites the supervisor narrative from a fact sheet. If it fails or returns an unusable payload, the deterministic narrative stands and the schedule is unchanged. That is a deliberate use of Nemotron: language in the lane where language helps, a solver in the lane where a wrong digit moves a wafer.

Mock mode uses `MockProvider` with the same `complete()` signature. The report field `provider_call.mocked` is true, and the console banner says offline mock. `make demo` forces this mode so a fresh machine can film the product. To film the required live request, set the token and run `python -m resilimes recover --scenario litho_down`. The JSON includes `provider_call.provider = "nightshift"`, the Nemotron model id, and latency. Crop or scroll so `.env` is not on screen.

`tests/test_recovery.py::test_nightshift_retries_rate_limits` drives two 429s and then a successful completion without a real hotspot.

## Cursor

The scaffold (`agent/`, `prompts/`, the original sample files, `smoke_test.py`) and this completion were written in Cursor. Cursor's agent mode produced the scheduler, the three engines, the console, the test suite, CI, and the submission docs in this branch. The team should say that on the slide and in the HackOS sponsor field: Cursor was the build environment, not a runtime dependency of the fab.

## What is unusual about the combination

Most hackathon agents let the model both decide and explain. Here the model is behind Nightshift, the decision is a tested scheduler, and Scout will not let the loop run without a fresh contract. Zetaris, or its sample twin with the same SQL, is the only source of lots and tools. The world model is the only place a committed assignment exists. A viewer, an injection, an expired contract, or a missing approval stops the write. That is the sponsor stack used as the control plane of a manufacturing decision, not as three logos on a chat window.
